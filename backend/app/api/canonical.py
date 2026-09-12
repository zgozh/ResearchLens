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
from app.contracts.common import Scope, Warning, new_ctx
from app.contracts.evidence import ReviewRequest, VerifiedStatement
from app.contracts.jobs import JobEvent
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
    scene as scene_mod,
    visual as visual_mod,
)
from app.schemas.adapters import to_legacy_paper
from app.schemas.canonical import Capability, ExhibitBundle, MediaIndexItem, PaperManifest, SectionIndexItem
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api", tags=["canonical"])


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
    ctx = new_ctx(scope, snapshot=papers_mod.snapshot_for_revision(scope))
    return StreamingResponse(
        qa_mod.stream(scope, body, ctx),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


__all__ = ["router"]
