"""M13 — canonical 资源接口（REFACTOR_SPEC §5.12）。

除流/二进制资源外成功 200；所有 API prefix 为 `/api`。列表遵守 PageResult，
revision_id 默认解析见 §5.1（未知 revision 404，revision 与 paper 不一致 409）。

不把业务规则复制进 routes：这里只做 HTTP 参数验证、认证、错误映射、轻量聚合，
一律调用 ``app.modules.*`` 的公共入口（跨模块不传 Session）。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.contracts.artifacts import ByteRange
from app.contracts.common import Budget, Scope, Warning, new_ctx
from app.contracts.evidence import ReviewRequest, VerifiedStatement
from app.contracts.jobs import STAGE_ORDER, JobEvent
from app.contracts.qa import QARequest
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import DomainError, conflict, invalid_input, not_found
from app.core.security import require_admin
from app.modules import (
    claims as claims_mod,
    evaluation as eval_mod,
    evidence as evidence_mod,
    graph as graph_mod,
    papers as papers_mod,
    parse as parse_mod,
    pipeline as pipeline_mod,
    qa as qa_mod,
    retrieval as retrieval_mod,
    scene as scene_mod,
    visual as visual_mod,
)
from pydantic import BaseModel
from app.schemas.adapters import to_legacy_paper
from app.schemas.canonical import Capability, ExhibitBundle, MediaIndexItem, PaperManifest, SectionIndexItem
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api", tags=["canonical"])

#: 流式问答的整体截止时间（毫秒）。没有它时，供应商慢/卡住会让 SSE 无限挂着
#: （用户实测"一直在转"）。到点后 AI 层抛 DEADLINE_EXCEEDED，问答服务降级为
#: 抽取式作答或明确拒答 —— 总之**必须给出交代**（ADR-0063）。
QA_STREAM_DEADLINE_MS = 120_000


# ================================================================== helpers


def _resolve_scope(paper_id: int, revision_id: Optional[str]) -> tuple[Scope, Any]:
    """解析请求 scope：未指定 revision 时固定当前 published/readable revision（§5.1）。

    返回 ``(Scope, Revision|null)``。无 revision 时返回空 revision_id 的 scope。
    """
    paper = papers_mod.get_paper(paper_id)  # 不存在抛 NOT_FOUND → 404
    if revision_id:
        rev = papers_mod.get_revision(Scope(paper_id=paper_id, revision_id=revision_id))
        return Scope(paper_id=paper_id, revision_id=revision_id), rev
    rid = paper.readable_revision_id or paper.published_revision_id
    if not rid:
        return Scope(paper_id=paper_id, revision_id=""), None
    rev = papers_mod.get_revision(Scope(paper_id=paper_id, revision_id=rid))
    return Scope(paper_id=paper_id, revision_id=rid), rev


def _parse_range(header: Optional[str], total: int) -> Optional[ByteRange]:
    """解析 ``Range: bytes=start-end``；无效返回 None（按全量响应）。"""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[len("bytes="):].strip()
    if "," in spec:  # 多范围不支持（§5.12 → 416）
        raise HTTPException(416, "不支持多范围 Range")
    try:
        start_s, _, end_s = spec.partition("-")
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else total - 1
    except ValueError as exc:
        raise HTTPException(416, "Range 格式非法") from exc
    if start < 0 or start >= total or end < start:
        raise HTTPException(416, "Range 越界")
    return ByteRange(start=start, end_inclusive=min(end, total - 1))


def _capabilities(scope: Scope, has_source: bool) -> List[Capability]:
    """按各模块产物是否存在给出能力状态（不临时计算）。"""
    caps: List[Capability] = []
    pdf_state = "ready" if has_source else "unavailable"
    caps.append(Capability(name="pdf", state=pdf_state, reason=None if has_source else "无源文件"))
    try:
        pages = parse_mod.get_pages(scope, limit=1)
        caps.append(Capability(name="text", state="ready" if pages.total > 0 else "pending"))
    except DomainError:
        caps.append(Capability(name="text", state="pending", reason="尚未解析"))
    try:
        m = visual_mod.list_media(scope, limit=1)
        caps.append(Capability(name="media", state="ready" if m.total > 0 else "pending"))
    except DomainError:
        caps.append(Capability(name="media", state="pending", reason="尚未构建媒体"))
    for name, fn in (
        ("claims", claims_mod.list_claims),
        ("graph", graph_mod.get),
        ("presentation", scene_mod.get),
        ("qa", None),
        ("evaluation", eval_mod.get),
    ):
        try:
            if fn is None:
                # 暂无「预置 QA 库」产物探测器（题库未配置时本就跳过）；
                # QA 的实时问答走 SSE 端点，不在此表达。
                caps.append(Capability(name=name, state="pending"))
                continue
            result = fn(scope)
            # 各模块返回形状不同：claims 返回**列表**，graph/scene/evaluation 返回聚合对象。
            # 旧写法只探测 .items/.nodes/.scenes/.metrics，于是 list 永远判为 pending
            # （list 没有 .items 属性）——实测 30 条 claim 已落库，manifest 却仍显示
            # capabilities.claims=pending，前端据此认为"无断言"。
            if isinstance(result, (list, tuple, set)):
                ready = len(result) > 0
            else:
                ready = bool(result and (
                    getattr(result, "items", None) or getattr(result, "nodes", None)
                    or getattr(result, "scenes", None) or getattr(result, "metrics", None)
                ))
            caps.append(Capability(name=name, state="ready" if ready else "pending"))
        except DomainError:
            caps.append(Capability(name=name, state="pending", reason="尚未生成"))
    return caps


def _paper_out(paper_id: int) -> Any:
    paper = papers_mod.get_paper(paper_id)
    metadata = papers_mod.get_metadata(paper_id)
    revision = None
    rid = paper.readable_revision_id or paper.published_revision_id
    if rid:
        revision = papers_mod.get_revision(Scope(paper_id=paper_id, revision_id=rid))
    return to_legacy_paper(paper, metadata, revision)


# ================================================================== manifest


@router.get("/papers/{paper_id}/manifest", response_model=PaperManifest)
def manifest(paper_id: int, revision_id: Optional[str] = None):
    scope, revision = _resolve_scope(paper_id, revision_id)
    paper = papers_mod.get_paper(paper_id)
    out = _paper_out(paper_id)

    source = None
    page_count = 0
    section_index: List[SectionIndexItem] = []
    media_index: List[MediaIndexItem] = []
    assets: List[Any] = []
    warnings: List[Warning] = []
    if revision is not None:
        try:
            source = papers_mod.get_source(scope)
        except DomainError as exc:
            warnings.append(Warning(code="no_source", message=exc.message, stage="manifest"))
        try:
            page_count = parse_mod.get_pages(scope, limit=1).total
        except DomainError as exc:
            warnings.append(Warning(code="no_pages", message=exc.message, stage="manifest"))
        try:
            structure = claims_mod.get_structure(scope)
            section_index = [
                SectionIndexItem(id=s.id, heading=s.heading, anchor_ids=list(s.anchor_ids))
                for s in structure.sections
            ]
        except DomainError:
            pass
        try:
            media = visual_mod.list_media(scope, limit=200)
            media_index = [
                MediaIndexItem(id=m.id, kind=m.kind, label=m.original_label,
                               thumbnail_asset_id=m.thumbnail_asset_id)
                for m in media.items
            ]
        except DomainError:
            pass
        try:
            assets = papers_mod.get_assets(scope, [])
        except DomainError:
            pass

    active_job = None
    try:
        from app.modules.pipeline import repository as prepo
        from app.core.db import session_scope
        with session_scope() as db:
            row = prepo.active_job_for_paper(db, paper_id)
            if row is not None:
                active_job = prepo.job_dto(row)
    except Exception:  # noqa: BLE001 - 活动任务读取失败不阻断 manifest
        active_job = None

    return PaperManifest(
        paper=out,
        revision=revision,
        provenance_class=paper.provenance_class or "synthetic",
        source=source,
        page_count=page_count,
        section_index=section_index,
        media_index=media_index,
        assets=assets,
        capabilities=_capabilities(scope, source is not None),
        active_job=active_job,
        warnings=warnings,
    )


# ================================================================== document / assets


@router.get("/papers/{paper_id}/document")
def document(paper_id: int, request: Request, revision_id: Optional[str] = None):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    source = papers_mod.get_source(scope)
    total = source.byte_size
    byte_range = None
    range_header = request.headers.get("range")
    if range_header:
        byte_range = _parse_range(range_header, total)

    read = papers_mod.open_asset(source.asset_id, byte_range)
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{source.sha256}"',
        "Content-Length": str(read.total_size),
    }
    status = 200
    if read.range is not None:
        headers["Content-Range"] = (
            f"bytes {read.range.start}-{read.range.end_inclusive}/{read.total_size}"
        )
        headers["Content-Length"] = str(read.range.end_inclusive - read.range.start + 1)
        status = 206
    return StreamingResponse(
        _iter_bytes(read.stream),
        media_type="application/pdf",
        headers=headers,
        status_code=status,
    )


@router.get("/assets/{asset_id}")
def asset_bytes(asset_id: str, request: Request):
    # 原始 HTML/SVG 不当主动页面发送（attachment 或 text/plain）
    read = papers_mod.open_asset(asset_id)
    mime = read.asset.mime or "application/octet-stream"
    if mime in ("text/html", "image/svg+xml", "application/xhtml+xml"):
        mime = "text/plain"
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{read.asset.sha256}"',
        "Content-Length": str(read.total_size),
    }
    range_header = request.headers.get("range")
    if range_header:
        byte_range = _parse_range(range_header, read.total_size)
        read = papers_mod.open_asset(asset_id, byte_range)
        headers["Content-Range"] = (
            f"bytes {read.range.start}-{read.range.end_inclusive}/{read.total_size}"
        )
        headers["Content-Length"] = str(read.range.end_inclusive - read.range.start + 1)
        return StreamingResponse(_iter_bytes(read.stream), media_type=mime, headers=headers, status_code=206)
    return StreamingResponse(_iter_bytes(read.stream), media_type=mime, headers=headers)


def _iter_bytes(stream):
    """同步 bytes 迭代器 → 生成器（StreamingResponse 会在线程池执行）。"""
    for chunk in stream:
        yield chunk


# ================================================================== pages / media / anchors / evidence


@router.get("/papers/{paper_id}/pages")
def pages(paper_id: int, revision_id: Optional[str] = None,
          cursor: Optional[str] = None, limit: int = 50):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    return parse_mod.get_pages(scope, cursor, limit)


@router.get("/papers/{paper_id}/pages/{pdf_page_no}")
def page_content(paper_id: int, pdf_page_no: int, revision_id: Optional[str] = None):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    return parse_mod.get_page(scope, pdf_page_no)


@router.get("/papers/{paper_id}/pages/{pdf_page_no}/preview")
def page_preview(paper_id: int, pdf_page_no: int, revision_id: Optional[str] = None):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    asset = visual_mod.ensure_page_preview(scope, pdf_page_no, new_ctx(scope))
    read = papers_mod.open_asset(asset.id)
    return StreamingResponse(
        _iter_bytes(read.stream),
        media_type=asset.mime or "image/png",
        headers={"ETag": f'"{asset.sha256}"', "Content-Length": str(read.total_size)},
    )


@router.get("/papers/{paper_id}/media")
def media(paper_id: int, revision_id: Optional[str] = None, kind: Optional[str] = None,
          cursor: Optional[str] = None, limit: int = 50):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    return visual_mod.list_media(scope, kind, cursor, limit)


@router.get("/papers/{paper_id}/media/{media_id}")
def media_detail(paper_id: int, media_id: str, revision_id: Optional[str] = None):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    m = visual_mod.get_media(scope, [media_id])
    if not m:
        raise not_found("media 不存在或不属于该 revision")
    assets = papers_mod.get_assets(scope, list(m[0].original_asset_ids))
    return {"media": m[0], "assets": assets, "policy": visual_mod.get_policy(m[0])}


@router.get("/papers/{paper_id}/anchors/{anchor_id}")
def anchor(paper_id: int, anchor_id: str, revision_id: Optional[str] = None):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    return evidence_mod.get_anchor(scope, anchor_id)


@router.get("/papers/{paper_id}/evidence/{evidence_id}")
def evidence_detail(paper_id: int, evidence_id: str, revision_id: Optional[str] = None):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    return evidence_mod.get_evidence_with_validation(scope, evidence_id)


@router.get("/papers/{paper_id}/statements")
def statements(paper_id: int, revision_id: Optional[str] = None,
               ids: Optional[str] = Query(None)):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    if ids:
        id_list = [x.strip() for x in ids.split(",") if x.strip()]
        if len(id_list) > 100:
            raise invalid_input("ids 最多 100 个", field="ids")
        items = claims_mod.get_statements(scope, id_list)
    else:
        items = claims_mod.get_verified_statements(scope)
    return {"items": items}


# ================================================================== exhibits / export


@router.get("/papers/{paper_id}/exhibits", response_model=ExhibitBundle)
def exhibits(paper_id: int, revision_id: Optional[str] = None):
    scope, revision = _resolve_scope(paper_id, revision_id)
    if revision is None:
        raise conflict("尚无可读 revision，展项不可用")
    structure = claims_mod.get_structure(scope)
    claims = claims_mod.list_claims(scope)
    statements = claims_mod.get_verified_statements(scope)
    graph = graph_mod.get(scope)
    presentation = scene_mod.get(scope)
    evaluation = None
    try:
        evaluation = eval_mod.get(scope)
    except DomainError:
        pass
    return ExhibitBundle(
        scope=scope,
        structure=structure,
        claims=claims,
        statements=statements,
        graph=graph,
        presentation=presentation,
        evaluation=evaluation,
        capabilities=_capabilities(scope, True),
    )


@router.get("/papers/{paper_id}/evidence-export")
def evidence_export(paper_id: int, revision_id: Optional[str] = None):
    scope, revision = _resolve_scope(paper_id, revision_id)
    if revision is None:
        raise conflict("尚无可读 revision，无法导出")
    claims = claims_mod.list_claims(scope)
    statements = claims_mod.get_verified_statements(scope)
    media = visual_mod.list_media(scope, limit=200).items
    export = evidence_mod.export(scope, claims, statements, media)
    return export


# ================================================================== qa stream


@router.post("/papers/{paper_id}/qa/stream")
async def qa_stream(paper_id: int, body: QARequest, revision_id: Optional[str] = None):
    scope, _rev = _resolve_scope(paper_id, revision_id)
    # 必须注入 revision 固定的模型快照：``new_ctx(scope)`` 的 snapshot 默认 None，
    # 会让 QA 直接判 ``llm_unavailable`` 并 abstained —— 前端只看到空气泡。
    # **必须给 deadline**（ADR-0063）：此前没有截止时间，供应商慢/卡住时 SSE 会一直挂着
    # （用户看到"一直在转"）；有 deadline 后 ``ai.complete`` 会抛 DEADLINE_EXCEEDED，
    # 由问答服务降级为抽取式作答或明确拒答，而不是无限等待。
    ctx = new_ctx(
        scope,
        snapshot=papers_mod.snapshot_for_revision(scope),
        deadline_ms=QA_STREAM_DEADLINE_MS,
        budget=Budget(
            max_calls=24, max_input_tokens=200_000, max_output_tokens=40_000,
            max_wall_ms=QA_STREAM_DEADLINE_MS, max_repair_rounds=2,
        ),
    )
    return StreamingResponse(
        qa_mod.stream(scope, body, ctx),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ProcessBody(BaseModel):
    """`POST /papers/{id}/process` 请求体（M12）：可选续跑起点。"""

    from_stage: Optional[str] = None


@router.post("/papers/{paper_id}/resume")
def paper_resume(paper_id: int, body: ProcessBody = ProcessBody()):
    """按续跑计划起一次管线任务（M12）。

    - 不传 `from_stage` → 从**第一个未完成阶段**开始（默认安全，不重烧 AI 阶段）；
    - 传 `from_stage` → 从该阶段开始；
    - 全部阶段已完成 → `status="noop"`，**不建 job**（不产生空任务）。

    **为什么路径是 `/resume` 而不是方案里写的 `/process`**（实测发现）：
    `/api/papers/{id}/process` 已经被 **legacy** 路由占用（`api/routes.py`，先注册者胜），
    curl 实测那个路径返回的是 legacy 的 `{paper_id, job_id, status:"running"}` ——
    新端点即使注册了也**永远不可达**。硬改路由优先级会破坏 legacy 兼容契约，
    因此改为新增不冲突的 `/resume`；`/process` 的 legacy 行为保持不变。
    """
    from app.modules.pipeline import ingest as ingest_mod

    scope, revision = _resolve_scope(paper_id, None)
    if revision is None:
        return {"status": "noop", "start_stage": None, "skipped": [],
                "reason": "该论文还没有可读 revision，无法续跑"}
    return ingest_mod.resume_paper(scope, body.from_stage)


@router.get("/papers/{paper_id}/resume-plan")
def resume_plan(
    paper_id: int,
    from_stage: Optional[str] = None,
    revision_id: Optional[str] = None,
):
    """断点续跑计划（M12）：告诉调用方"重跑会从哪个阶段开始、哪些阶段会被跳过"。

    为什么需要：管线**已经**有阶段幂等键（`job_stage_keys`）与"产物 digest 命中就 skipped"，
    但**没有任何入口**能问"这篇论文续跑该从哪起"。手工从 `acquire` 重跑会重烧一遍
    AI 阶段（claims 起草 / 题库作答 / evaluate 裁判）——那是真金白银。

    - 不传 `from_stage` → 从**第一个未成功**的阶段起（默认安全）；
    - 传 `from_stage` → 从指定阶段起（之前的一律跳过）；
    - 全部已完成 → `start_stage=null` + 原因。
    """
    scope, _rev = _resolve_scope(paper_id, revision_id)
    from app.modules.pipeline import resume as resume_mod

    plan = resume_mod.resolve_start_stage(scope, from_stage)
    return {
        "scope": {"paper_id": scope.paper_id, "revision_id": scope.revision_id},
        "start_stage": plan.start_stage,
        "skipped": plan.skipped,
        "reason": plan.reason,
        "stages": list(STAGE_ORDER),
    }


@router.get("/papers/{paper_id}/qa/stream-audit")
def qa_stream_audit(paper_id: int, limit: int = 50):
    """流式问答审计（M7）：按创建时间倒序列出该 paper 的流式回答对账记录。

    为什么需要：用户报"显示被中断"时，服务端**每次都有 final** —— 没有对账数据就只能靠猜。
    这里能看到每次流的事件序列、终结类型（`none` = 服务端没发出终结事件，即"被中断"）、
    错误码与耗时。`events` 只存类型名，不含答案正文。
    """
    from app.modules.qa import audit as qa_audit

    return {"paper_id": paper_id, "items": qa_audit.list_audits(paper_id, limit=limit)}


@router.get("/papers/{paper_id}/qa/answers/{answer_id}")
def qa_answer_recover(paper_id: int, answer_id: str, db: Session = Depends(get_db)):
    """断流恢复（REFACTOR_PLAN M6 §5.2）：按 answer_id 取回**已落库**的回答。

    为什么需要：浏览器上一次 SSE 可能被网络/服务重启切断在 final 之前。答案其实
    **已经落库**（服务端在发 final 前就持久化了），但前端没有凭据去取。现在 ``meta``
    事件先发 ``answer_id``，客户端断流后可以凭它在 30 秒内把结果捞回来，
    而不是让用户重问一遍、白烧一次模型调用。
    """
    from app.modules.qa import repository as qa_repository
    from app.modules.qa import service as qa_service

    row = qa_repository.get_answer(db, answer_id)
    if row is None:
        raise not_found(f"没有这个回答：{answer_id}")
    record = qa_service._row_to_answer(row)
    if record is None:
        # 行还在写（streaming）或旧数据缺字段：如实告诉客户端"还在生成，稍后再拉"
        return {"status": "streaming", "answer_id": answer_id}
    payload = stream_mod_legacy(record)
    return {"status": "completed", "answer_id": answer_id, "legacy": payload,
            "answer": record.model_dump(mode="json")}


def stream_mod_legacy(record):
    """复用 SSE final 的 legacy 投影，保证"流里看到的"和"恢复取回的"完全一致。"""
    from app.modules.qa.stream import _legacy_answer

    return _legacy_answer(record)


# ================================================================== jobs events / cancel / retry


def _job_event_sse(event: JobEvent) -> str:
    return (
        f"id: {event.event_id}\n"
        f"event: {event.type}\n"
        f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"
    )


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: int, after: int = 0):
    async def gen() -> AsyncIterator[str]:
        async for event in pipeline_mod.events(job_id, after):
            yield _job_event_sse(event)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: int, x_admin_token: Optional[str] = Header(None)):
    actor = require_admin(x_admin_token)
    return pipeline_mod.cancel(job_id, actor)


@router.post("/jobs/{job_id}/retry")
def job_retry(job_id: int, x_admin_token: Optional[str] = Header(None)):
    actor = require_admin(x_admin_token)
    return pipeline_mod.retry(job_id, actor)


# ================================================================== reviews


@router.post("/papers/{paper_id}/reviews")
def review(paper_id: int, body: ReviewRequest, x_admin_token: Optional[str] = Header(None)):
    actor = require_admin(x_admin_token)
    if body.scope.paper_id != paper_id:
        raise conflict("scope.paper_id 与路径不一致")
    return evidence_mod.review(body, actor, new_ctx(body.scope))


# ================================================================== rebuild derived


class RebuildDerivedBody(BaseModel):
    """重建范围。默认只重建**不需要 LLM** 的派生产物。"""

    index: bool = True      # 检索索引（chunks + vectors）：问答与检索的前提
    graph: bool = True      # 研究图谱快照（节点/边）
    scene: bool = True      # 讲解分镜（确定性；基于**当前**结构，改过结构再重建）
    # 图表绑定（statement→media）：确定性、不调 LLM。绑定规则升级后**必须回填**，
    # 否则方法步骤的图表引用会一直停留在旧规则的结果上（ADR-0059）。
    bindings: bool = True
    # 模型快照回填：早期导入的 revision 没登记快照 → 问答退化成"无模型"（ADR-0067）
    snapshot: bool = True
    structure: bool = False  # 结构/论文地图/方法步骤——**会调用 LLM**，故默认关闭


@router.post("/papers/{paper_id}/rebuild-derived")
def rebuild_derived(
    paper_id: int,
    body: RebuildDerivedBody = RebuildDerivedBody(),
    revision_id: Optional[str] = None,
    x_admin_token: Optional[str] = Header(None),
):
    """重建**派生产物**（检索索引 / 图谱 / 结构），供运维与修复后回填。

    为什么需要（ADR-0037/0043）：``retrieval.index`` 与 ``graph.build`` 此前**只有脚本
    能调**。实测 papers 1–3 的 ``chunks``/``chunk_vectors`` 全为 0（行经 seed 路径入库、
    跳过了 pipeline 的 index 阶段），于是"证据问答"整块不可用；图谱快照也停留在旧算法上。
    没有任何 API 能把它们补起来，只能进容器跑脚本——这不是可运维的形态。

    幂等：``retrieval.index`` 按 ``(revision_id, content_hash)`` 去重；``graph.build``
    覆盖写同 revision 的快照。

    ``structure=true`` 会调用 LLM（结构/地图/方法步骤），因此**默认关闭**。
    """
    actor = require_admin(x_admin_token)
    scope, _rev = _resolve_scope(paper_id, revision_id)
    ctx = new_ctx(scope, snapshot=papers_mod.snapshot_for_revision(scope), deadline_ms=900_000)

    result: dict = {
        "scope": {"paper_id": scope.paper_id, "revision_id": scope.revision_id},
        "actor": getattr(actor, "kind", "") or str(actor),
    }

    if body.index:
        index_result = retrieval_mod.index(scope, ctx)
        result["index"] = {
            "chunk_count": index_result.chunk_count,
            "vector_count": index_result.vector_count,
            "status": index_result.status,
            "embedding_space": index_result.embedding_space,
            "warnings": [w.code for w in (index_result.warnings or [])],
        }

    # 模型快照回填（ADR-0067）：早期由网址/上传导入的 revision 没登记
    # ``model_snapshot_id`` → 问答退化成"无模型"（通用回答永远返回 None，界面转圈后没反应）。
    if body.snapshot:
        try:
            from app.core.db import session_scope as _scope
            from app.models.source import RevisionORM
            from app.modules.ai import capabilities as capabilities_mod
            from app.modules.papers import repository as papers_repo

            snap = capabilities_mod.get_snapshot()
            data = snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)
            with _scope() as db:
                snapshot_id = papers_repo.find_or_create_snapshot(db, data).id
                row = db.get(RevisionORM, scope.revision_id)
                if row is not None:
                    row.model_snapshot_id = snapshot_id
            result["snapshot"] = {"model_snapshot_id": snapshot_id, "backfilled": True}
        except Exception as exc:  # noqa: BLE001  回填失败不得让重建整体失败
            result["snapshot"] = {"error": f"{type(exc).__name__}: {exc}"}

    if body.bindings:
        # 绑定规则升级后的**回填入口**（ADR-0059）：方法步骤的图表引用来自这些绑定，
        # 不回填的话，规则改进（新增"同页/相邻页"位置兜底）在老 revision 上完全看不到。
        try:
            from app.modules import evidence as evidence_mod

            statements = list(claims_mod.get_verified_statements(scope))
            bound = evidence_mod.bind_media_for_statements(scope, statements, ctx)
            methods: dict = {}
            for binding in bound:
                methods[binding.method] = methods.get(binding.method, 0) + 1
            result["bindings"] = {
                "statements": len(statements), "bindings": len(bound), "by_method": methods,
            }
        except Exception as exc:  # noqa: BLE001  绑定失败不得让重建整体失败
            result["bindings"] = {"error": f"{type(exc).__name__}: {exc}"}

    if body.graph:
        artifact = graph_mod.build(scope)
        kinds: dict = {}
        for node in artifact.nodes:
            kinds[node.kind] = kinds.get(node.kind, 0) + 1
        relations: dict = {}
        for edge in artifact.edges:
            relations[edge.relation] = relations.get(edge.relation, 0) + 1
        result["graph"] = {
            "nodes": len(artifact.nodes), "node_kinds": kinds,
            "edges": len(artifact.edges), "edge_relations": relations,
            "warnings": [w.code for w in (artifact.warnings or [])],
        }

    if body.structure:
        structure = claims_mod.build_structure(scope, ctx)
        result["structure"] = {
            "sections": len(structure.sections),
            "map_items": len(getattr(structure.map, "items", []) or []),
            "method_steps": len(structure.method_steps),
        }

    if body.scene:
        # 分镜基于**当前**结构生成；若同一请求里重建了结构，则用新结构。
        current = structure if body.structure else claims_mod.get_structure(scope)
        artifact = scene_mod.build(scope, current)
        result["scene"] = {
            "scenes": len(artifact.scenes),
            "statement_ids": sum(len(s.statement_ids or []) for s in artifact.scenes),
            "warnings": [w.code for w in (artifact.warnings or [])],
        }

    return result


@router.post("/papers/{paper_id}/golden-set")
def build_golden_set(
    paper_id: int,
    revision_id: Optional[str] = None,
    source: str = Query("builtin", description="builtin=从原文挑句；ai=模型读原文起草（带逐字引文校验）"),
    x_admin_token: Optional[str] = Header(None),
):
    """构造并保存该 revision 的 **Golden Set**（真值取自原文，不由模型自证）。

    为什么需要（ADR-0046）：``golden_sets`` 表 0 行时，``overall_score`` 的四个核心
    指标里 ``support_precision`` 与 ``unanswerable_refusal_rate`` 永远没有分母，
    综合评分只能是 null（前端只能诚实显示"未评测"）。

    ``source``：
    - ``builtin``（默认）：**不调 LLM**，claim 文本逐字取自原文块；
    - ``ai``：**模型读原文起草**关键断言，但每条的 ``quote`` 必须逐字出现在原文块里
      （校验不过即丢弃），且仍按**调参集**保存（ADR-0065）—— 用来解决"句子挑选版
      参考集与抽取断言内容不重合、precision 只有 0.18"的问题。
    """
    require_admin(x_admin_token)
    scope, _rev = _resolve_scope(paper_id, revision_id)
    from app.modules.evaluation import golden_builder

    if source == "ai":
        ctx = new_ctx(scope, snapshot=papers_mod.snapshot_for_revision(scope),
                      deadline_ms=300_000,
                      budget=Budget(max_calls=6, max_input_tokens=200_000,
                                    max_output_tokens=40_000, max_wall_ms=300_000,
                                    max_repair_rounds=1))
        golden = golden_builder.build_and_save_ai(scope, ctx)
        source_used = "ai"
    else:
        golden = golden_builder.build_and_save(scope)
        source_used = "builtin"

    return {
        "scope": {"paper_id": scope.paper_id, "revision_id": scope.revision_id},
        "source": source_used,
        "golden": {
            "id": golden.id, "version": golden.version,
            "claims": len(golden.claims),
            "answerable_questions": sum(1 for q in golden.questions if q.answerable),
            "unanswerable_questions": sum(1 for q in golden.questions if not q.answerable),
            "anchors": len(golden.anchors),
        },
    }


@router.get("/papers/{paper_id}/golden-set")
def get_golden_set(
    paper_id: int,
    revision_id: Optional[str] = None,
    x_admin_token: Optional[str] = Header(None),
):
    """读取该 revision 的**金标集草案**，供人工复核。

    为什么需要（规格 §5.9）：``support_precision/recall`` 必须有**标注集**才叫 measured，
    且综合评分只在"包含人工真值的核心指标均可测"时才计算。机器自动构造的集合只是
    **草案/调参集**，必须有人看过并确认（``POST .../golden-set/confirm``）才能当真值。
    这里把草案逐条列出来，让"确认"是**看过之后的确认**，而不是盖空章。
    """
    require_admin(x_admin_token)
    scope, _rev = _resolve_scope(paper_id, revision_id)
    from app.core.db import session_scope
    from app.modules.evaluation import golden_builder

    with session_scope() as db:
        golden, is_tuning = golden_builder.find_for_scope_ex(db, scope)
    if golden is None:
        raise not_found("该 revision 尚无金标集，先 POST /golden-set 生成草案")
    return {
        "scope": {"paper_id": scope.paper_id, "revision_id": scope.revision_id},
        "golden": {
            "id": golden.id, "version": golden.version,
            "is_tuning": is_tuning,
            "status": "draft（机器构造，待人工确认）" if is_tuning else "confirmed（人工已确认）",
        },
        "claims": [
            {"id": c.id, "text": c.text, "acceptable_block_ids": c.acceptable_block_ids}
            for c in golden.claims
        ],
        "questions": [
            {"id": q.id, "question": q.question, "answerable": q.answerable}
            for q in golden.questions
        ],
    }


@router.post("/papers/{paper_id}/golden-set/confirm")
def confirm_golden_set(
    paper_id: int,
    revision_id: Optional[str] = None,
    x_admin_token: Optional[str] = Header(None),
):
    """把金标集标记为**人工已确认**（此后 precision/recall 才算 measured、才出综合评分）。

    **调用即表示人工复核通过**（admin 凭据承担确认责任）。机器自动构造的集合在此之前
    一律按调参集处理，不参与对外报告——避免"让模型给自己出卷子"。
    """
    actor = require_admin(x_admin_token)
    scope, _rev = _resolve_scope(paper_id, revision_id)
    from app.modules.evaluation import golden_builder

    golden = golden_builder.confirm_for_scope(scope)
    if golden is None:
        raise not_found("该 revision 尚无金标集，先 POST /golden-set 生成草案")
    return {
        "scope": {"paper_id": scope.paper_id, "revision_id": scope.revision_id},
        "confirmed": {"id": golden.id, "version": golden.version},
        "actor": getattr(actor, "kind", "") or str(actor),
    }


__all__ = ["router"]
