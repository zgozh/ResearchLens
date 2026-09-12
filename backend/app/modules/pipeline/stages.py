"""M11 — 固定阶段执行（REFACTOR_SPEC §3.3、§5.8、§6.13）。

每个阶段：
1. 读入 staging scope（短事务）；
2. 云 I/O（解析/LLM）在**无写事务**中执行；
3. 产物提交用短事务 + 幂等键 ``(revision_id, stage, input_digest, algorithm_version)``；
4. 返回 ``StageResult``（失败是可报告结果，不把异常泄漏为 500）。

阶段顺序：acquire → parse → normalize → media → index → claims → verify →
exhibits → qa_bank → evaluate → publish。
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.contracts.ai import Usage
from app.contracts.common import CallContext, Scope, Warning
from app.contracts.evidence import ClaimDraftBatch, VerifiedStatement
from app.contracts.jobs import STAGE_ORDER, Stage, StageResult
from app.core.clock import utc_now
from app.core.db import session_scope
from app.core.errors import DomainError, ErrorCode, conflict, dependency_unavailable, invalid_input
from app.modules.pipeline import repository as repo
from app.modules.pipeline.repository import MAX_ATTEMPTS

#: 阶段算法版本——变化即让幂等键失效（受控版本号，不随意自增）
ALGORITHM_VERSION = "rl.pipeline/1"

#: 各阶段在总进度里的权重（用于 progress 展示）
STAGE_WEIGHTS: Dict[str, float] = {
    "acquire": 0.05,
    "parse": 0.20,
    "normalize": 0.05,
    "media": 0.15,
    "index": 0.10,
    "claims": 0.15,
    "verify": 0.10,
    "exhibits": 0.10,
    "qa_bank": 0.05,
    "evaluate": 0.05,
    "publish": 0.00,
}


def _cumulative_progress(stage: str) -> float:
    total = 0.0
    for name in STAGE_ORDER:
        total += STAGE_WEIGHTS.get(name, 0.0)
        if name == stage:
            return min(1.0, total)
    return 1.0


def next_stage_of(stage: str) -> Optional[str]:
    try:
        idx = STAGE_ORDER.index(stage)
    except ValueError:
        return None
    return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None


def _digest(*parts: Optional[str]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update((part or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _ok(stage: str, *, artifact_ids: Optional[List[str]] = None,
        digest: Optional[str] = None, usage: Optional[Usage] = None,
        warnings: Optional[List[Warning]] = None) -> StageResult:
    return StageResult(
        stage=stage, status="succeeded", artifact_ids=list(artifact_ids or []),
        artifact_digest=digest, usage=usage or Usage(),
        warnings=list(warnings or []),
    )


def _partial(stage: str, *, warnings: Optional[List[Warning]] = None,
             artifact_ids: Optional[List[str]] = None,
             digest: Optional[str] = None, usage: Optional[Usage] = None) -> StageResult:
    return StageResult(
        stage=stage, status="partial", artifact_ids=list(artifact_ids or []),
        artifact_digest=digest, usage=usage or Usage(), warnings=list(warnings or []),
    )


def _failed(stage: str, error: DomainError) -> StageResult:
    return StageResult(stage=stage, status="failed", error=error.to_dict())


def _skipped(stage: str, reason: str) -> StageResult:
    return StageResult(
        stage=stage, status="skipped",
        warnings=[Warning(code="stage_skipped", message=reason, stage=stage)],
    )


# ================================================================== 各阶段


def stage_acquire(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    """获取源文件：URL 下载 / pending_upload 归档 / stored 复用。

    云 I/O（HTTP 下载）不持有写事务。下载失败按 retryable 报错。
    **关键**：新论文首次 ingest 时 ``scope.revision_id`` 为空——本阶段在获取源文件后
    为其建立 ``source`` 修订版，并把 revision.id 作为 ``artifact_ids[0]`` 返回，
    由 ``run_stage`` 写回 job（后续阶段的 scope 才有 revision）。
    """
    from app.contracts.documents import SourceInput, SourceMetadata
    from app.modules import papers as papers_mod

    source_raw = spec.get("source") or {}
    try:
        source_input = SourceInput.model_validate(source_raw)
    except Exception:  # noqa: BLE001
        # 无 source 时，若论文已有源文件则直接复用（reprocess/evaluate，此时 revision 已存在）
        try:
            src = papers_mod.get_source(scope)
            return _ok("acquire", artifact_ids=[scope.revision_id, src.id], digest=src.sha256)
        except DomainError:
            return _failed("acquire", invalid_input("JobSpec 缺少可用的 source"))

    source = None
    if source_input.kind == "stored":
        source = papers_mod.get_source(scope)
    elif source_input.kind == "pending_upload":
        if not source_input.asset_id:
            return _failed("acquire", invalid_input("pending_upload 缺少 asset_id"))
        source = _promote_pending_upload(scope, source_input.asset_id, spec, ctx)
    elif source_input.kind == "url":
        url = (source_input.url or "").strip()
        if not url:
            return _failed("acquire", invalid_input("url 为空", field="url"))
        try:
            source = papers_mod.fetch_source(scope.paper_id, url, ctx)
        except DomainError as exc:
            return _failed("acquire", exc)
    else:
        return _skipped("acquire", f"未知 source.kind={source_input.kind}")

    if source is None:
        return _failed("acquire", invalid_input("acquire 未能取得源文件"))

    # 新论文首次 ingest：为源文件建立 staging revision（幂等——已有 revision 则复用）
    revision_id = scope.revision_id
    if not revision_id:
        revision = papers_mod.create_revision(scope.paper_id, source.id, "source", ctx)
        revision_id = revision.id

    return _ok("acquire", artifact_ids=[revision_id, source.id], digest=source.sha256)


def _promote_pending_upload(scope: Scope, asset_id: str, spec: Dict[str, Any], ctx: CallContext):
    """把上传的 pending asset 提升为 SourceDocument（字节只保存一次）。"""
    from app.contracts.documents import SourceMetadata
    from app.modules import papers as papers_mod
    from app.modules.papers import storage as storage_mod

    read = papers_mod.open_asset(asset_id)
    stream = _asset_chunks(read)
    metadata = SourceMetadata(
        original_filename=spec.get("original_filename") or "upload.pdf",
        acquisition="upload",
    )
    return papers_mod.store_source(scope.paper_id, stream, metadata, ctx)


def _asset_chunks(read):
    """把 AssetRead 的同步字节迭代器适配成 store_source 需要的流。"""
    import io

    chunks = list(read.stream or [])
    return io.BytesIO(b"".join(chunks))


def stage_parse(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    from app.modules import papers as papers_mod, parse as parse_mod

    try:
        source = papers_mod.get_source(scope)
    except DomainError as exc:
        return _failed("parse", exc)

    scope_ctx = _ctx_for(scope, ctx)
    try:
        result = parse_mod.parse(source, scope_ctx)
    except DomainError as exc:
        return _failed("parse", exc)
    except Exception as exc:  # noqa: BLE001 - 解析崩溃必须可重试，不能静默
        return _failed("parse", DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, f"解析失败：{type(exc).__name__}",
            retryable=True, cause=exc,
        ))

    try:
        summary = parse_mod.persist(scope, result, scope_ctx)
    except DomainError as exc:
        return _failed("parse", exc)

    digest = _digest(source.sha256, result.parser_name, result.parser_version)
    warnings = list(result.warnings or [])
    result_status = "partial" if summary.quality == "partial" else "succeeded"
    stage_result = StageResult(
        stage="parse", status=result_status,
        artifact_ids=[source.id] + list(summary.raw_asset_ids or []),
        artifact_digest=digest, warnings=warnings,
    )
    return stage_result


def stage_normalize(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    """规范化：读取页/块分布并确认可读。

    解析产物已由 ``persist`` 归一化落库；本阶段负责**设定 readable_revision_id**
    （仅解析完成才可设，§5.8）与产出质量判定。
    """
    from app.modules import papers as papers_mod, parse as parse_mod

    try:
        page_result = parse_mod.get_pages(scope, limit=1)
        revision = papers_mod.get_revision(scope)
    except DomainError as exc:
        return _failed("normalize", exc)

    if int(page_result.total or 0) <= 0:
        return _partial("normalize", warnings=[Warning(
            code="no_pages", message="解析没有产生任何物理页；仅保留源文件可读", stage="normalize",
        )])

    # 仅解析完成（存在页）才设 readable
    try:
        papers_mod.set_readable(scope, ctx)
    except DomainError as exc:
        return _failed("normalize", exc)

    digest = _digest(revision.id, str(page_result.total), revision.quality)
    return _ok("normalize", artifact_ids=[revision.id], digest=digest)


def stage_media(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    from app.contracts.documents import ParseSummary
    from app.modules import parse as parse_mod, visual as visual_mod

    try:
        pages = parse_mod.get_pages(scope, limit=200)
        summary = _parse_summary(scope, pages)
        built = visual_mod.build_media(scope, summary, ctx)
    except DomainError as exc:
        return _failed("media", exc)
    except Exception as exc:  # noqa: BLE001
        return _failed("media", DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, f"媒体构建失败：{type(exc).__name__}",
            retryable=True, cause=exc,
        ))

    digest = _digest(*[m.id for m in built.media])
    warnings = list(built.warnings or [])
    status = "partial" if warnings and not built.media else "succeeded"
    return StageResult(
        stage="media", status=status,
        artifact_ids=[m.id for m in built.media], artifact_digest=digest, warnings=warnings,
    )


def _parse_summary(scope: Scope, pages) -> Any:
    """把已持久化的页 + 重建的媒体候选还原为 Media 构建所需的 ParseSummary。

    ``build_media`` 需要 ``media_candidates`` 才能建 Media。候选本应在 parse
    阶段由 ``normalize.build_media_candidates`` 产出，但 handler 是无状态重放，
    必须从已存档的 ``parser_raw`` 资产 + 已持久化 Block 重建 —— 之前这里传的是
    空候选，导致 media 阶段 succeeded 却产出 0 条。
    """
    from app.contracts.documents import ParseSummary
    from app.modules import parse as parse_mod

    try:
        candidates = parse_mod.load_media_candidates(scope)
    except DomainError:
        raise
    except Exception as exc:  # noqa: BLE001 - 候选重建失败不应伪装成空产物
        raise DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"媒体候选重建失败：{type(exc).__name__}",
            retryable=True,
            cause=exc,
        )

    return ParseSummary(
        scope=scope,
        page_count=int(getattr(pages, "total", 0) or len(getattr(pages, "items", []) or [])),
        block_ids=[], anchor_ids=[], media_candidates=candidates, raw_asset_ids=[],
        quality="complete",
    )


def _source_block_ids(scope: Scope) -> List[str]:
    """列出该 revision 的**原文块 ID**（origin=source_extraction）。

    M02 没有「列全部块」的公共入口（``get_blocks`` 需要显式 ID）；pipeline 作为
    编排者可直接只读 canonical 表，但**不把它当作跨模块公共契约**。
    """
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.models.artifacts import BlockORM

    with session_scope() as db:
        rows = db.execute(
            select(BlockORM.id)
            .where(
                BlockORM.revision_id == scope.revision_id,
                BlockORM.origin == "source_extraction",
                BlockORM.text != "",
            )
            .order_by(BlockORM.page_id.asc(), BlockORM.ordinal.asc())
        ).scalars().all()
        return [str(r) for r in rows]


def stage_index(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    from app.modules import retrieval as retrieval_mod

    try:
        result = retrieval_mod.index(scope, ctx)
    except DomainError as exc:
        return _failed("index", exc)
    except Exception as exc:  # noqa: BLE001
        return _failed("index", DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, f"索引失败：{type(exc).__name__}",
            retryable=True, cause=exc,
        ))

    warnings = list(result.warnings or [])
    digest = _digest(scope.revision_id, str(result.chunk_count), result.embedding_space or "")
    status = "partial" if result.status == "lexical_only" and warnings else "succeeded"
    return StageResult(
        stage="index", status=status, artifact_ids=[], artifact_digest=digest, warnings=warnings,
    )


def stage_claims(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    """提取候选陈述并跑 gate（``verify_and_store`` 内含 gate + 短事务持久化）。"""
    from app.modules import claims as claims_mod

    try:
        block_ids = _source_block_ids(scope)
    except DomainError as exc:
        return _failed("claims", exc)

    if not block_ids:
        return _skipped("claims", "没有原文块，跳过断言抽取")

    scope_ctx = _ctx_for(scope, ctx)
    try:
        batch = claims_mod.extract(scope, block_ids, scope_ctx)
        built = claims_mod.verify_and_store(batch, scope_ctx)
    except DomainError as exc:
        return _failed("claims", exc)
    except Exception as exc:  # noqa: BLE001
        return _failed("claims", DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, f"断言抽取失败：{type(exc).__name__}",
            retryable=True, cause=exc,
        ))

    warnings = list(built.warnings or [])
    digest = _digest(*[c.claim_id for c in built.claims])
    status = "partial" if warnings else "succeeded"
    return StageResult(
        stage="claims", status=status,
        artifact_ids=[c.claim_id for c in built.claims],
        artifact_digest=digest, warnings=warnings,
    )


def stage_verify(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    """校验阶段：Supervisor 有界决策（accept/retrieve_more/repair/abstain，最多两轮）。

    只对**未验证/争议**陈述做补检索或修正；达到预算即降级为待核验。
    """
    from app.modules import claims as claims_mod
    from app.modules.pipeline import supervisor as supervisor_mod

    try:
        statements = claims_mod.get_statements(scope, [])
    except DomainError as exc:
        return _failed("verify", exc)

    reports = [s.validation for s in statements if s.validation is not None]
    if not reports:
        return _skipped("verify", "没有可决策的校验报告")

    decisions = supervisor_mod.decide(reports, _ctx_for(scope, ctx))
    digest = _digest(*[f"{d.statement_id}:{d.action}" for d in decisions])
    warnings = [
        Warning(code="supervisor_decision",
                message=f"{d.action} ({d.reason_code})", stage="verify")
        for d in decisions if d.action in ("retrieve_more", "repair", "abstain")
    ]
    return StageResult(
        stage="verify", status="partial" if warnings else "succeeded",
        artifact_ids=[d.statement_id for d in decisions], artifact_digest=digest,
        warnings=warnings,
    )


def stage_exhibits(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    """生成结构/图谱/场景展示产物（M06/M08/M09）。

    **媒体绑定必须先于场景装配**（ADR-0009）：scene 只走
    ``verified statement → verified Binding → Media`` 这条通道，
    绑定不存在时场景永远显示"无已验证媒体"。此前没有任何环节调用
    ``evidence.bind()``，故 ``bindings`` 恒为 0、讲解挂不上任何图表。
    """
    from app.modules import (
        claims as claims_mod,
        evidence as evidence_mod,
        graph as graph_mod,
        scene as scene_mod,
    )

    scope_ctx = _ctx_for(scope, ctx)
    artifact_ids: List[str] = []
    warnings: List[Warning] = []
    status = "succeeded"
    try:
        structure = claims_mod.build_structure(scope, scope_ctx)
        claims = claims_mod.list_claims(scope)
        statements = claims_mod.get_verified_statements(scope)
        bindings = evidence_mod.bind_media_for_statements(scope, statements, scope_ctx)
        if statements and not bindings:
            warnings.append(Warning(
                code="no_media_binding",
                message="没有陈述可复核地关联到媒体；场景将显示无已验证媒体",
                stage="exhibits",
            ))
        graph = graph_mod.build(scope, claims, scope_ctx)
        presentation = scene_mod.build(scope, structure, claims, scope_ctx)
        artifact_ids = [structure.sections[0].id] if structure.sections else []
        artifact_ids = list(artifact_ids) + [graph.id, presentation.id]
        warnings.extend(list(presentation.warnings or []))
    except DomainError as exc:
        return _failed("exhibits", exc)
    except Exception as exc:  # noqa: BLE001
        return _failed("exhibits", DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, f"展示产物生成失败：{type(exc).__name__}",
            retryable=True, cause=exc,
        ))

    if warnings:
        status = "partial"
    return StageResult(
        stage="exhibits", status=status, artifact_ids=artifact_ids,
        artifact_digest=_digest(*artifact_ids), warnings=warnings,
    )


def stage_qa_bank(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    """预置题库作答。

    **问题从哪来（ADR-0070）**：以前只认 ``spec["bank_questions"]``，而导入流程从来不设它
    → 这一步**永远 skipped** → 拒答率/引文精确率/时延全都没有分母 → 用户在"自动评测"里
    看到一片"未评测"。现在没有显式题库时**自动用金标集的问题**；没有金标集就先让
    **AI 起草参考断言**（带逐字引文校验，见 golden_builder）——这样导入完就有一套
    可核对的问题与真值，评测才有意义。
    """
    from app.modules import qa as qa_mod

    questions = list(spec.get("bank_questions") or [])
    scope_ctx = _ctx_for(scope, ctx)

    if not questions:
        try:
            from app.core.db import session_scope
            from app.modules.evaluation import golden_builder

            with session_scope() as db:
                golden = golden_builder.find_for_scope(db, scope)
            if golden is None:
                golden = golden_builder.build_and_save_ai(scope, scope_ctx)
            questions = [q.question for q in (golden.questions if golden else []) if q.question]
        except Exception:  # noqa: BLE001  题库准备失败按"没有题库"处理，不伪造问题
            questions = []
        if not questions:
            return _skipped("qa_bank", "未能取得题库问题（不生成假问答）")

    try:
        answers = qa_mod.build_bank(scope, questions, scope_ctx)
    except DomainError as exc:
        return _failed("qa_bank", exc)
    except Exception as exc:  # noqa: BLE001
        return _failed("qa_bank", DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, f"题库生成失败：{type(exc).__name__}",
            retryable=True, cause=exc,
        ))
    return _ok("qa_bank", artifact_ids=[a.id for a in answers], digest=_digest(*[a.id for a in answers]))


def stage_evaluate(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    """计算评测报告。

    **必须带上金标集与已作答的题库**（ADR-0070）：以前只传 statements + media，
    于是 ``support_precision``/拒答率/引文精确率/时延全都没有分母 → 导入完的论文在
    "自动评测"里几乎全是"未评测"。现在复用旧入口的 ``_input_for``（它会收集
    statements/answers/golden/media/navigation_checks），口径与
    ``GET /papers/{id}/evaluation`` 完全一致。
    """
    from app.modules import evaluation as eval_mod

    try:
        from app.modules.evaluation import legacy as eval_legacy

        inp = eval_legacy._input_for(scope)
        report = eval_mod.compute(inp, _ctx_for(scope, ctx))
    except DomainError as exc:
        return _failed("evaluate", exc)
    except Exception as exc:  # noqa: BLE001
        return _failed("evaluate", DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, f"评测失败：{type(exc).__name__}",
            retryable=True, cause=exc,
        ))
    return _ok("evaluate", artifact_ids=[report.id], digest=_digest(report.id))


def stage_publish(scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    """原子发布：仅当 gate 完整性清单具备且无取消请求时切换发布指针（CAS）。

    幂等：若该 revision 已是 published，直接成功（重跑场景不触发 CAS 冲突）。
    """
    from app.modules import papers as papers_mod

    quality = spec.get("publish_quality") or "partial"
    digest = spec.get("artifact_digest") or _digest(scope.revision_id)
    paper = papers_mod.get_paper(scope.paper_id)
    if paper.published_revision_id == scope.revision_id:
        # 已是当前发布版本（重跑幂等），不重复 CAS
        return _ok("publish", artifact_ids=[scope.revision_id], digest=digest)
    try:
        # expected = 当前 published（None 或旧 revision）；CAS 失败说明他人已发布
        papers_mod.publish(scope, paper.published_revision_id, digest, quality, ctx)
    except DomainError as exc:
        return _failed("publish", exc)
    return _ok("publish", artifact_ids=[scope.revision_id], digest=digest)


STAGE_HANDLERS: Dict[str, Callable[[Scope, Dict[str, Any], CallContext], StageResult]] = {
    "acquire": stage_acquire,
    "parse": stage_parse,
    "normalize": stage_normalize,
    "media": stage_media,
    "index": stage_index,
    "claims": stage_claims,
    "verify": stage_verify,
    "exhibits": stage_exhibits,
    "qa_bank": stage_qa_bank,
    "evaluate": stage_evaluate,
    "publish": stage_publish,
}


def run_stage_impl(stage: Stage, scope: Scope, spec: Dict[str, Any], ctx: CallContext) -> StageResult:
    handler = STAGE_HANDLERS.get(stage)
    if handler is None:
        return _failed(stage, invalid_input(f"未知阶段 {stage}"))
    if ctx.is_cancelled():
        return _failed(stage, DomainError(ErrorCode.CANCELLED, "已请求取消，阶段不执行"))
    try:
        return handler(scope, spec, ctx)
    except DomainError as exc:
        return _failed(stage, exc)
    except Exception as exc:  # noqa: BLE001 - 任何阶段异常都必须是可报告的失败
        return _failed(stage, DomainError(
            ErrorCode.INTERNAL_ERROR, f"阶段 {stage} 内部错误：{type(exc).__name__}",
            retryable=True, cause=exc,
        ))


def _ctx_for(scope: Scope, ctx: CallContext) -> CallContext:
    """把 job 的 CallContext 绑定到具体 scope（跨模块不传 Session）。"""
    if ctx.scope is not None and (
        ctx.scope.paper_id == scope.paper_id and ctx.scope.revision_id == scope.revision_id
    ):
        return ctx
    return ctx.model_copy(update={"scope": scope})


__all__ = [
    "ALGORITHM_VERSION", "STAGE_WEIGHTS", "STAGE_HANDLERS", "STAGE_ORDER",
    "next_stage_of", "run_stage_impl", "MAX_ATTEMPTS",
]
