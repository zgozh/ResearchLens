"""M04 — 证据、绑定与事实发布闸门（REFACTOR_SPEC §5.4、§5.9、§5.10、§6.6）。

**全系统 Evidence Gate**：已验证事实 / 推断 / 争议 / 缺证之间有**不可绕过**的状态边界。

公共函数（§5.10 M04 行）：

- ``validate(draft, ctx, review=None) -> ValidationReport``
- ``save_report(report, ctx) -> ValidationReport``
- ``get_evidence(scope, ids) -> EvidenceRecord[]``
- ``get_anchor(scope, id) -> Anchor``
- ``resolve_legacy(scope, refs) -> ResolutionReport``
- ``bind(input, ctx) -> Binding`` / ``get_bindings(scope, from_) -> Binding[]``
- ``review(input, actor, ctx) -> ReviewRecord`` / ``get_reviews(scope, ids)``
- ``mark_review_applied(review_id, new_scope, job_id, ctx) -> ReviewRecord``
- ``export(scope, claims, statements, media) -> EvidenceExport``

边界规则：**M04 不 import M06**（避免循环）。本模块接收 ``StatementDraft``，
不调用 claims；``export`` 由 API 收集 DTO 传入。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Sequence

from app.contracts.artifacts import Media
from app.contracts.common import (
    ArtifactRef,
    CallContext,
    Id,
    Scope,
    SourceRef,
    Warning,
)
from app.contracts.documents import Anchor, Page, PageLabelMapping
from app.contracts.evidence import (
    Binding,
    CitationCandidate,
    ClaimRecord,
    EvidenceExport,
    EvidenceRecord,
    LegacyRef,
    ResolutionReport,
    ReviewRecord,
    ReviewRequest,
    StatementDraft,
    ValidationReport,
    VerifiedStatement,
)
from app.core.clock import utc_now
from app.core.db import session_scope
from app.core.errors import (
    conflict,
    invalid_input,
    not_found,
    revision_mismatch,
)
from app.core.security import Actor
from app.models.source import new_id

from . import gate as gate_mod
from . import legacy_resolver, repository as repo
from . import semantic as semantic_mod
from .gate import GateInput

#: 绑定/关系允许的端点类型（同 scope 校验）
_ARTIFACT_KINDS = {
    "claim", "statement", "section", "method_step",
    "scene", "graph_node", "graph_edge", "answer",
}
_SOURCE_KINDS = {"evidence", "media", "anchor", "block"}


# =============================================================== 世界加载


def _page_ref(block_id: str, page_id: str, page_index: int, label: Optional[str]):
    from app.modules.evidence.locator import PageRef

    return PageRef(
        block_id=block_id, page_id=page_id,
        pdf_page_index=page_index, page_label=label,
    )


def _load_gate_input(
    db, scope: Scope, *, media_items: Sequence[Media],
    llm_available: bool = False,
    semantic_model_verdict: Optional[str] = None,
    semantic_model_confidence: Optional[float] = None,
    semantic_model_reason: str = "",
) -> GateInput:
    """把 DB 世界读成纯 GateInput（读操作，短事务内完成）。"""
    from app.models.source import RevisionORM

    block_rows = repo.get_block_rows(db, scope.revision_id)
    page_rows = repo.get_page_rows(db, scope.revision_id)
    page_by_id = {p.id: p for p in page_rows}

    from app.contracts.documents import Block as BlockDTO

    blocks: Dict[str, BlockDTO] = {}
    page_of_block: Dict[str, Any] = {}
    anchor_of_block: Dict[str, str] = {}
    for row in block_rows:
        if row.origin != "source_extraction":
            # 只有原文块能作为证据来源；生成摘要不得当一级证据
            continue
        page = page_by_id.get(row.page_id)
        if page is None:
            continue
        blocks[row.id] = BlockDTO(
            scope=scope, id=row.id, page_id=row.page_id, ordinal=row.ordinal or 0,
            kind=row.kind or "paragraph", text=row.text or "",
            origin="source_extraction", anchor_id=row.anchor_id,
            media_id=row.media_id, section_path=list(row.section_path or []),
            raw_ref=None, language=row.language or "", content_hash=row.content_hash,
        )
        page_of_block[row.id] = _page_ref(
            row.id, page.id, page.pdf_page_index, page.page_label
        )
        if row.anchor_id:
            anchor_of_block[row.id] = row.anchor_id

    media_pages: Dict[str, int] = {}
    media_anchors: Dict[str, List[str]] = {}
    allowed_media = set()
    for media in media_items:
        allowed_media.add(media.id)
        media_anchors[media.id] = list(media.anchor_ids)
        # 从 anchor 反查所在页
        for anchor_row in repo.get_anchor_rows(db, scope.revision_id, media.anchor_ids[:4]):
            for seg in (anchor_row.segments or []):
                if seg.get("pdf_page_index") is not None:
                    media_pages[media.id] = int(seg["pdf_page_index"])
                    break

    source_document_id = ""
    revision = db.get(RevisionORM, scope.revision_id)
    if revision is not None and revision.source_document_id:
        source_document_id = revision.source_document_id

    return GateInput(
        scope=scope,
        blocks=blocks,
        page_of_block=page_of_block,
        anchor_of_block=anchor_of_block,
        media_pages=media_pages,
        media_anchors=media_anchors,
        allowed_media=allowed_media,
        source_document_id=source_document_id,
        llm_available=llm_available,
        semantic_model_verdict=semantic_model_verdict,
        semantic_model_confidence=semantic_model_confidence,
        semantic_model_reason=semantic_model_reason,
    )


def _media_dtos(db, scope: Scope) -> List[Media]:
    from app.modules.visual import service as visual_service

    rows = repo.get_media_rows(db, scope.revision_id)
    return [visual_service._media_dto(scope, row) for row in rows]


def _require_scope(scope: Scope) -> None:
    """校验 scope 中 paper/revision 同属且存在。"""
    from app.models.source import RevisionORM

    if scope.paper_id <= 0 or not scope.revision_id:
        raise invalid_input("scope 非法")
    with session_scope() as db:
        row = db.get(RevisionORM, scope.revision_id)
        if row is None:
            raise not_found("revision 不存在")
        if row.paper_id != scope.paper_id:
            raise revision_mismatch("revision 不属于该 paper")


def _text_digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# =============================================================== validate


def validate(
    draft: StatementDraft, ctx: CallContext, review: Optional[ReviewRecord] = None
) -> ValidationReport:
    """执行 Evidence Gate，返回报告（**gate 失败是 report，不是异常**）。

    契约顺序固定：范围/身份 → 原文精确或可回溯规范化匹配 → 页/区域
    → 数字/单位/条件 → 语义支持 → decision。
    """
    if not isinstance(draft, StatementDraft):
        raise invalid_input("draft 必须为 StatementDraft", field="draft")
    if not (draft.text or "").strip():
        raise invalid_input("陈述文本为空", field="text")

    # 身份/范围：必须先确认 revision 归属，错版本直接拒绝
    from app.models.source import RevisionORM

    with session_scope() as db:
        revision = db.get(RevisionORM, draft.scope.revision_id)
        if revision is None:
            raise not_found("revision 不存在")
        if revision.paper_id != draft.scope.paper_id:
            raise revision_mismatch("陈述 scope 的 revision 不属于该 paper")

        media_items = _media_dtos(db, draft.scope)
        llm_available = _llm_available(ctx)
        # 受信编排器可**预置**判定（如人工复核走 human assessor）；
        # 未预置时由本模块自行调用语义判定（见下方 _semantic_judge_for）。
        semantic_verdict = getattr(ctx, "_semantic_verdict", None)
        semantic_confidence = getattr(ctx, "_semantic_confidence", None)
        gate_input = _load_gate_input(
            db, draft.scope, media_items=media_items,
            llm_available=llm_available,
            semantic_model_verdict=semantic_verdict,
            semantic_model_confidence=semantic_confidence,
        )
        # ---- 第一遍：纯定位（无云调用），拿到候选与证据原文 ----
        report, candidates = gate_mod.assess(
            draft, gate_mod.GateInput(
                **{**gate_input.__dict__, "semantic_model_verdict": None,
                   "semantic_model_confidence": None}
            ), review=review,
        )

    # ---- 语义判定：在**写事务之外**调用模型（云 I/O 不占长事务） ----
    if semantic_verdict is None:
        evidence_text = gate_mod._evidence_text_for(candidates, gate_input.blocks)
        if evidence_text:
            verdict, confidence, judge_msg = semantic_mod.judge(draft.text, evidence_text, ctx)
            if verdict is not None:
                # 拿到判定后重跑 gate（纯函数，无云调用），让 ⑤ 步命中模型分支。
                # **把模型给的理由一起带进去**：界面上的"未支持"必须能解释原因（M5）。
                with session_scope() as db:
                    media_items = _media_dtos(db, draft.scope)
                    gate_input2 = _load_gate_input(
                        db, draft.scope, media_items=media_items,
                        llm_available=llm_available,
                        semantic_model_verdict=verdict,
                        semantic_model_confidence=confidence,
                        semantic_model_reason=judge_msg,
                    )
                    report, _c = gate_mod.assess(draft, gate_input2, review=review)
    return report


def _llm_available(ctx: Optional[CallContext]) -> bool:
    try:
        from app.modules.ai import is_ready

        return bool(is_ready())
    except Exception:  # noqa: BLE001 - 依赖不可用不得中断 gate
        return False


# =============================================================== save_report


def save_report(report: ValidationReport, ctx: CallContext) -> ValidationReport:
    """持久化校验报告（**保存时复查 source hash / 引用关系**）。

    幂等：同 scope/statement 重复保存覆盖同一 id，不产生重复证据。
    """
    if not isinstance(report, ValidationReport):
        raise invalid_input("report 必须为 ValidationReport", field="report")
    scope = report.scope
    _require_scope(scope)

    with session_scope() as db:
        # 复查：陈述文本未变（防止"确认了 A，落库成 B"）
        draft = _draft_from_statement(db, report)
        if draft is None:
            raise not_found(f"陈述 {report.statement_id} 不存在，无法保存校验报告")

        # 清理旧的 evidence/validation（幂等覆盖）
        for old in repo.get_validations_for_statement(db, scope.revision_id, report.statement_id):
            for ev_id in (old.evidence or []):
                for item in repo.get_evidence_rows(db, scope.revision_id, [ev_id]):
                    db.delete(item)
            db.delete(old)

        media_items = _media_dtos(db, scope)
        llm_available = _llm_available(ctx)
        gate_input = _load_gate_input(
            db, scope, media_items=media_items, llm_available=llm_available
        )
        # 用**已持久化的真实陈述**重跑定位层，拿到候选（source_text 仍来自原文切片）
        _report2, candidates = gate_mod.assess(draft, gate_input)

        evidence_records: List[EvidenceRecord] = []
        support_status = _support_status_for(report)
        for idx, cand in enumerate(candidates):
            if not cand.block_id and not cand.page_only:
                continue
            evidence_id = _evidence_id(scope, report.statement_id, cand, idx)
            anchor_id = _ensure_anchor(db, scope, cand, evidence_id)
            record = gate_mod.build_evidence_record(
                draft,
                cand,
                evidence_id=evidence_id,
                anchor_id=anchor_id,
                source_document_id=gate_input.source_document_id,
                validation_id=report.id,
                support_status=support_status,
                confidence=report.confidence if support_status == "supports" else None,
                confidence_method="rule_overlap/1" if support_status == "supports" else None,
            )
            repo.insert_evidence(db, record)
            evidence_records.append(record)

        saved = report.model_copy(update={"evidence": evidence_records})
        # 必须把本次落库的证据 id 写进 validation.evidence，
        # 否则下次幂等保存时无法找到并清理旧证据（会撞 UNIQUE 约束）。
        repo.insert_validation(db, saved, evidence_records)
        repo.audit(
            db, kind="validation_saved", scope=scope, actor="system",
            payload={"validation_id": saved.id, "statement_id": saved.statement_id,
                     "decision": saved.decision,
                     "evidence_count": len(evidence_records),
                     "text_digest": _text_digest(draft.text)},
        )
        return saved


def _draft_from_statement(db, report: ValidationReport) -> Optional[StatementDraft]:
    """从**已持久化的 StatementORM** 重建 draft（save_report 的唯一真值来源）。

    绝不用报告里的占位文本重建：报告不携带陈述原文，而陈述行才有。
    citations/qualifiers/kind 一并取回，保证重跑 gate 与首次 validate 等价。
    """
    from app.models.evidence import StatementORM

    row = db.get(StatementORM, report.statement_id)
    if row is None:
        return None
    if (row.paper_id, row.revision_id) != (report.scope.paper_id, report.scope.revision_id):
        raise revision_mismatch("陈述与报告 scope 不一致")

    citations = []
    for raw in (row.citations or []):
        if isinstance(raw, CitationCandidate):
            citations.append(raw)
        elif isinstance(raw, dict):
            citations.append(CitationCandidate(**raw))
    return StatementDraft(
        scope=report.scope, id=row.id, claim_id=row.claim_id or "",
        text=row.text or "", kind=row.kind or "fact",
        citations=citations, qualifiers=list(row.qualifiers or []),
    )


def _support_status_for(report: ValidationReport) -> str:
    if report.decision == "verified":
        return "supports"
    if report.decision == "contested":
        return "contradicts"
    if report.decision == "rejected":
        return "insufficient"
    return "unreviewed"


def _evidence_id(scope: Scope, statement_id: str, cand, idx: int) -> str:
    digest = hashlib.sha256(
        f"{scope.revision_id}|{statement_id}|{cand.block_id}|"
        f"{cand.pdf_page_index}|{idx}".encode("utf-8")
    ).hexdigest()[:32]
    return f"ev-{digest}"


def _ensure_anchor(db, scope: Scope, cand, evidence_id: str) -> str:
    """页/区域 anchor：region 才建 rect，page-only 必须 rect=None。"""
    if cand.anchor_id and repo.get_anchor_row(db, scope.revision_id, cand.anchor_id) is not None:
        return cand.anchor_id
    anchor_id = f"anc-{hashlib.sha256(evidence_id.encode('utf-8')).hexdigest()[:32]}"
    existing = repo.get_anchor_row(db, scope.revision_id, anchor_id)
    if existing is None:
        from app.models.artifacts import AnchorORM

        segment = gate_mod.candidate_to_segment(cand).model_dump()
        db.add(
            AnchorORM(
                id=anchor_id,
                paper_id=scope.paper_id,
                revision_id=scope.revision_id,
                source_document_id=getattr(cand, "source_document_id", "") or "",
                precision="region" if segment.get("rect") is not None else "page",
                segments=[segment],
            )
        )
    return anchor_id


# =============================================================== 读取


def get_evidence(scope: Scope, ids: List[Id]) -> List[EvidenceRecord]:
    """批量读取证据；跨 scope 的 ID 一律视为不存在（不静默省略，由调用方裁决）。"""
    if not ids:
        return []
    with session_scope() as db:
        rows = repo.get_evidence_rows(db, scope.revision_id, ids)
        by_id = {r.id: r for r in rows}
        ordered = [repo.evidence_dto(scope, by_id[i]) for i in ids if i in by_id]
    return ordered


def get_anchor(scope: Scope, id: str) -> Anchor:
    with session_scope() as db:
        row = repo.get_anchor_row(db, scope.revision_id, id)
        if row is None:
            raise not_found("anchor 不存在或不属于该 revision")
        return repo.anchor_dto(scope, row)


def get_evidence_with_validation(
    scope: Scope, evidence_id: str
) -> Dict[str, Any]:
    """证据 + 其校验报告（§5.12 GET /evidence/{id}）。"""
    with session_scope() as db:
        rows = repo.get_evidence_rows(db, scope.revision_id, [evidence_id])
        if not rows:
            raise not_found("evidence 不存在或不属于该 revision")
        record = repo.evidence_dto(scope, rows[0])
        validation = None
        if record.validation_id:
            vrow = repo.get_validation_row(db, scope.revision_id, record.validation_id)
            if vrow is not None:
                evs = [
                    repo.evidence_dto(scope, r)
                    for r in repo.get_evidence_rows(db, scope.revision_id, list(vrow.evidence or []))
                ]
                validation = repo.validation_dto(scope, vrow, evs)
    return {"evidence": record, "validation": validation}


# =============================================================== legacy


def resolve_legacy(scope: Scope, refs: List[LegacyRef]) -> ResolutionReport:
    """旧字符串引用解析。resolved 仅表示定位已解出，**不表示支持已验证**。"""
    if not refs:
        return ResolutionReport(scope=scope)
    _require_scope(scope)
    with session_scope() as db:
        media_items = [m for m in _media_dtos(db, scope) if not m.excluded]
        mappings = [
            PageLabelMapping(
                scope=scope, id=row.id, page_label=row.page_label,
                pdf_page_index=row.pdf_page_index, method=row.method,
                status=row.status, source_block_ids=list(row.source_block_ids or []),
                confidence=row.confidence, review_id=row.review_id,
            )
            for row in _label_rows(db, scope)
        ]
        anchor_of_media = {m.id: m.anchor_ids[0] for m in media_items if m.anchor_ids}
        return legacy_resolver.resolve_legacy_refs(
            scope, refs, media_items=media_items,
            label_mappings=mappings, anchor_of_media=anchor_of_media,
        )


def _label_rows(db, scope: Scope):
    from app.models.artifacts import PageLabelMappingORM
    from sqlalchemy import select

    return list(
        db.execute(
            select(PageLabelMappingORM).where(
                PageLabelMappingORM.revision_id == scope.revision_id
            )
        ).scalars().all()
    )


# =============================================================== binding


def bind(input: Binding, ctx: CallContext) -> Binding:
    """建立绑定。``state=verified`` 必须满足关系约束（不可凭自报）。"""
    if not isinstance(input, Binding):
        raise invalid_input("input 必须为 Binding", field="input")
    scope = input.scope
    _require_scope(scope)

    if input.from_.kind not in _ARTIFACT_KINDS:
        raise invalid_input(f"未知的 from kind：{input.from_.kind}", field="from.kind")

    with session_scope() as db:
        to_kind = input.to.kind
        to_id = input.to.id
        # 同 scope 校验：目标必须存在
        if to_kind in _SOURCE_KINDS:
            if not _source_target_exists(db, scope, to_kind, to_id):
                raise not_found(f"绑定目标不存在：{to_kind}/{to_id}")
        elif to_kind in _ARTIFACT_KINDS:
            if not _artifact_target_exists(db, scope, to_kind, to_id):
                raise not_found(f"绑定目标不存在：{to_kind}/{to_id}")
        else:
            raise invalid_input(f"未知的 to kind：{to_kind}", field="to.kind")

        if input.state == "verified" and input.relation in ("supports", "contradicts"):
            if input.relation == "supports" and not input.validation_id:
                raise invalid_input(
                    "verified 的 supports 绑定必须关联 validation_id（不支持自报）",
                    field="validation_id",
                )
            if input.validation_id:
                report = repo.get_validation_row(db, scope.revision_id, input.validation_id)
                if report is None:
                    raise not_found("validation_id 不存在或不属于该 revision")
                expected = "supports" if input.relation == "supports" else "contradicts"
                if report.decision not in ("verified", "contested") or (
                    report.semantic_status != expected
                ):
                    raise conflict("校验报告不支持该关系，不能标 verified")

        binding_id = input.id or new_id()
        existing = repo.get_binding_row(db, scope.revision_id, binding_id)
        payload = input.model_copy(update={"id": binding_id, "created_at": input.created_at or utc_now()})
        if existing is not None:
            existing.to_kind = to_kind
            existing.to_id = to_id
            existing.relation = payload.relation
            existing.method = payload.method
            existing.validation_id = payload.validation_id
            existing.state = payload.state
            existing.reason = payload.reason
            existing.score = payload.score
        else:
            repo.insert_binding(db, payload)
        repo.audit(db, kind="binding_saved", scope=scope, actor=ctx.request_id or "system",
                   payload={"binding_id": binding_id, "state": payload.state,
                            "relation": payload.relation})
        return payload


def _source_target_exists(db, scope: Scope, kind: str, target_id: str) -> bool:
    if kind == "evidence":
        return bool(repo.get_evidence_rows(db, scope.revision_id, [target_id]))
    if kind == "anchor":
        return repo.get_anchor_row(db, scope.revision_id, target_id) is not None
    if kind == "media":
        return bool(repo.get_media_rows(db, scope.revision_id, [target_id]))
    if kind == "block":
        return bool(repo.get_block_rows(db, scope.revision_id, [target_id]))
    return False


def _artifact_target_exists(db, scope: Scope, kind: str, target_id: str) -> bool:
    from app.models.artifacts import ArtifactBlobORM
    from app.models.evidence import AnswerORM, ClaimRecordORM, MethodStepORM, SectionRecordORM, StatementORM
    from sqlalchemy import select

    if kind == "claim":
        return db.get(ClaimRecordORM, target_id) is not None
    if kind == "statement":
        return db.get(StatementORM, target_id) is not None
    if kind == "section":
        return db.get(SectionRecordORM, target_id) is not None
    if kind == "method_step":
        return db.get(MethodStepORM, target_id) is not None
    if kind == "answer":
        return db.get(AnswerORM, target_id) is not None
    if kind in ("scene", "graph_node", "graph_edge"):
        # 场景/图谱存在 artifact_blobs 聚合产物中
        rows = db.execute(
            select(ArtifactBlobORM).where(ArtifactBlobORM.revision_id == scope.revision_id)
        ).scalars().all()
        for row in rows:
            payload = row.payload or {}
            for key in ("scenes", "nodes", "edges"):
                for item in payload.get(key) or []:
                    if isinstance(item, dict) and item.get("id") == target_id:
                        return True
        return False
    return False


def get_bindings(scope: Scope, from_: ArtifactRef) -> List[Binding]:
    with session_scope() as db:
        rows = repo.get_bindings_from(db, scope.revision_id, from_.kind, from_.id)
        return [repo.binding_dto(scope, row) for row in rows]


def get_verified_media_for_claims(
    scope: Scope, claim_ids: Sequence[str]
) -> Dict[str, List[str]]:
    """scene/QA 的受控媒体通道：claim → verified Binding → Media。

    仅接受 ``state=verified`` 且 ``relation=illustrates`` 的绑定；
    图号/印刷页字符串一律不在此路径产生结果。
    """
    if not claim_ids:
        return {}
    out: Dict[str, List[str]] = {cid: [] for cid in claim_ids}
    with session_scope() as db:
        claim_rows = _claim_rows_by_public_id(db, scope, claim_ids)
        for public_id, row in claim_rows.items():
            for binding in repo.get_bindings_from(db, scope.revision_id, "claim", row.id):
                if binding.state != "verified":
                    continue
                if binding.to_kind == "media":
                    out.setdefault(public_id, []).append(binding.to_id)
            for binding in repo.get_bindings_from(db, scope.revision_id, "statement", row.statement_id):
                if binding.state != "verified" or binding.to_kind != "media":
                    continue
                out.setdefault(public_id, []).append(binding.to_id)
    return out


def _claim_rows_by_public_id(db, scope: Scope, claim_ids: Sequence[str]):
    from app.models.evidence import ClaimRecordORM
    from sqlalchemy import select

    rows = db.execute(
        select(ClaimRecordORM).where(
            ClaimRecordORM.revision_id == scope.revision_id,
            ClaimRecordORM.claim_id.in_(list(claim_ids)),
        )
    ).scalars().all()
    return {row.claim_id: row for row in rows}


# =============================================================== 媒体绑定生成
#
# ADR-0009：``bindings`` 表此前**恒为 0 行**——``bind()`` 本身完整可用，但 pipeline
# 从不调用它，于是 ``scene → verified statement → Claim/Evidence → verified Binding
# → Media`` 这条**唯一合法**媒体通道永远走不通：讲解拿不到任何图表。
# 这里补上缺失的编排与判定。精度优先（唯一硬要求是"不乱"），只承认两类可复核关联。

#: caption_ref 的最低共享"区分性 token"数；证据不足即不绑定（宁缺勿造）
CAPTION_REF_MIN_SHARED_TOKENS = 2

#: 单条陈述最多绑定多少个媒体（避免一个场景被图表刷屏）
CAPTION_REF_MAX_PER_STATEMENT = 2

#: 可进入媒体通道的陈述类别（与 M09 讲解正文的 _VERIFIED_CLASSES 一致）
_BINDABLE_CLASSES = {"verified_fact", "attributed_quote", "transition"}

#: 陈述里的显式图表引用（带 kind 前缀）
_MEDIA_REF_RE = re.compile(
    r"(图|表|式|fig(?:ure)?\.?|tab(?:le)?\.?|eq(?:uation)?\.?)\s*"
    r"([A-Za-z]?\s*\d+[A-Za-z]?)",
    re.IGNORECASE,
)
_REF_KIND = {"图": "figure", "表": "table", "式": "equation"}

#: 英文/指标 token（MAE、FPA、F1-score、COOP-SC-Sol…）
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}")
#: 全大写缩写（MAE / FPA / RFR / SMOTE）——用作"区分性"判据
_ABBREV_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,7}\b")

_TOKEN_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "are", "was", "were", "has", "have", "been", "which", "than", "then",
    "our", "its", "can", "not", "but", "also", "more", "most", "such",
    "value", "values", "table", "figure", "fig", "tab", "equation", "eq",
    "paper", "result", "results", "using", "used", "based", "into", "only",
    "image", "images", "comparison", "compared", "each", "proposed",
    "original", "number", "show", "shows", "shown", "between", "among",
    "under", "over", "their", "when", "where", "while", "them", "they",
})


def bind_media_for_statements(
    scope: Scope,
    statements: Sequence[Any],
    ctx: CallContext,
    *,
    max_per_statement: int = CAPTION_REF_MAX_PER_STATEMENT,
) -> List[Binding]:
    """把**已验证陈述**绑定到能说明它的媒体（``relation=illustrates``）。

    只承认两类可复核关联（宁缺勿造）：

    - ``explicit_block_ref``：陈述正文显式写出 图/表/式 编号，且编号**整号**命中
      **同 kind** 媒体（``表 3`` 绝不会绑到 ``图 3``）；
    - ``caption_ref``：陈述与媒体 caption 共享 ≥ ``CAPTION_REF_MIN_SHARED_TOKENS``
      个 token，且其中至少一个是**区分性** token（含数字/连字符，或全大写缩写，
      如 ``F1-score`` / ``MAE`` / ``FPA``）。仅共享泛化词不算证据。

    幂等：绑定 id 由 ``(revision, statement, media)`` 派生，重复运行只更新不新增。
    未验证陈述一律不参与（媒体通道只服务已验证事实）。
    """
    bindable = [
        s for s in statements
        if getattr(s, "display_class", "unverified") in _BINDABLE_CLASSES
    ]
    if not bindable:
        return []

    _require_scope(scope)
    with session_scope() as db:
        media_items = _media_dtos(db, scope)
    if not media_items:
        return []

    created: List[Binding] = []
    # 位置兜底所需的页码（只查一次；精确匹配成功的陈述用不到）
    page_of_media: Dict[str, int] = {}
    page_of_statement: Dict[str, int] = {}
    with session_scope() as db:
        page_of_media, page_of_statement = _proximity_pages(db, scope, bindable)
    for statement in bindable:
        picks = _pick_media_for_statement(
            getattr(statement, "text", "") or "", media_items, max_per_statement
        )
        if not picks:
            # 精确方法（显式编号 / caption 重合）都没结果时，才用**位置**兜底：
            # 同页或相邻页的图表。用户反馈"有些步骤显示尚未绑定图表、于是没有引用"；
            # 但**绝不退回全篇第一张图**（D-48 的教训），且来源必须标明（ADR-0059）。
            fallback = _proximity_media_for_statement(
                page_of_statement.get(str(getattr(statement, "id", ""))),
                media_items, page_of_media,
            )
            if fallback is not None:
                picks = [fallback]
        for media_id, method, score, reason in picks:
            created.append(bind(Binding(
                scope=scope,
                id=_binding_id(scope, statement.id, media_id),
                from_=ArtifactRef(kind="statement", id=statement.id),
                to=SourceRef(kind="media", id=media_id),
                relation="illustrates",
                method=method,
                state="verified",
                reason=reason,
                score=score,
            ), ctx))
    return created


#: 位置兜底允许的最大页差（同页 = 0，相邻页 = 1）
PROXIMITY_MAX_PAGE_GAP = 1
#: 位置兜底的分值：**必须显著低于**精确匹配，便于前端/评测区分
PROXIMITY_SCORE = 0.2


def _proximity_pages(db, scope: Scope, statements: Sequence[Any]):
    """算出 ``(media_id → 0-based 页, statement_id → 0-based 页)``。

    - 媒体页：媒体自己的 ``anchor_ids`` 所指向的锚点第一段 ``pdf_page_index``；
    - 陈述页：该陈述**证据行**的 ``source_page``（1-based，`gate.build_evidence` 写的
      ``pdf_page_index + 1``）→ 换成 0-based 后与媒体同尺度比较。
    """
    from app.modules.evidence import repository as erepo

    media_rows = erepo.get_media_rows(db, scope.revision_id)
    anchor_ids = [a for row in media_rows for a in (row.anchor_ids or [])]
    anchor_page: Dict[str, int] = {}
    for row in erepo.get_anchor_rows(db, scope.revision_id, anchor_ids):
        for seg in (row.segments or []):
            idx = seg.get("pdf_page_index") if isinstance(seg, dict) else None
            if idx is not None:
                anchor_page[row.id] = int(idx)
                break
    page_of_media: Dict[str, int] = {}
    for row in media_rows:
        for anchor_id in (row.anchor_ids or []):
            if anchor_id in anchor_page:
                page_of_media[row.id] = anchor_page[anchor_id]
                break

    # 媒体**没有锚点**时（实测 papers 1–3 的 media 一个 anchor 都没有），用 caption
    # 文本反查它所在的原文块，再取该块的物理页。为什么值得做：不这么做时
    # ``page_of_media`` 恒为空 → 位置兜底永远不生效（实测 17 个媒体全 page=None）。
    if len(page_of_media) < len(media_rows):
        page_of_media.update(_media_pages_by_caption(db, scope, media_rows, page_of_media))

    ev_ids = [e for s in statements for e in (getattr(s, "evidence_ids", None) or [])]
    ev_page: Dict[str, int] = {}
    if ev_ids:
        for row in erepo.get_evidence_rows(db, scope.revision_id, ev_ids):
            ev_page[row.id] = max(0, int(row.source_page or 1) - 1)
    page_of_statement: Dict[str, int] = {}
    for statement in statements:
        pages = [ev_page[e] for e in (getattr(statement, "evidence_ids", None) or [])
                 if e in ev_page]
        if pages:
            page_of_statement[str(getattr(statement, "id", ""))] = min(pages)
    return page_of_media, page_of_statement


def _media_pages_by_caption(db, scope: Scope, media_rows, known: Dict[str, int]):
    """用 caption 文本反查媒体所在块，得到 0-based 页（``known`` 以外的媒体）。

    为什么需要：实测 papers 1–3 的 ``media`` **一个 anchor 都没有**、也没有块通过
    ``media_id`` 反向引用，于是"媒体在哪一页"在库里无迹可寻；而 caption 文本与
    caption 块是同一段文字（实测前 8 个媒体里 7 个能匹配上），匹配到块就能拿到页。
    只做**确定性**的文本包含匹配，匹配不上就**不给页**（不猜）。
    """
    from app.modules.evidence import repository as erepo

    pending = [row for row in media_rows if row.id not in known]
    if not pending:
        return {}
    page_of_block = {p.id: p.pdf_page_index for p in erepo.get_page_rows(db, scope.revision_id)}
    block_rows = erepo.get_block_rows(db, scope.revision_id)   # BlockORM 行
    out: Dict[str, int] = {}
    for row in pending:
        caption = (row.caption or "").strip()
        probe = caption[:18]
        if not probe:
            continue
        for block in block_rows:
            if probe in (block.text or ""):
                page = page_of_block.get(block.page_id)
                if page is not None:
                    out[row.id] = int(page)
                break
    return out


def _proximity_media_for_statement(
    statement_page: Optional[int],
    media_items: Sequence[Media],
    page_of_media: Dict[str, int],
) -> Optional[Any]:
    """**位置兜底**：取同页或相邻页的媒体（ADR-0059）。

    为什么需要：用户反馈"方法动画里有些步骤显示该步骤的断言尚未绑定图表，
    然后导致该步骤没有相关的引用"。精确方法（陈述显式写"图 N"、或与 caption
    共享区分性 token）在中文论文上命中率有限，而**同页图表**在排版上是真正相关的。

    纪律：① 只在精确方法都没结果时调用；② 页差 ≤ ``PROXIMITY_MAX_PAGE_GAP``；
    ③ 返回低分 + ``method="page_proximity"`` + 说明"位置推断"，**不冒充题注匹配**。
    """
    if statement_page is None:
        return None
    best: Optional[Any] = None
    best_gap: Optional[int] = None
    for media in media_items:
        media_page = page_of_media.get(media.id)
        if media_page is None:
            continue
        gap = abs(int(media_page) - int(statement_page))
        if gap > PROXIMITY_MAX_PAGE_GAP:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = media, gap
    if best is None:
        return None
    where = "同页" if best_gap == 0 else "相邻页"
    return (
        best.id, "page_proximity", PROXIMITY_SCORE,
        f"{where}图表（位置推断，非题注文字匹配；该陈述的精确引用缺失）",
    )


def _binding_id(scope: Scope, statement_id: str, media_id: str) -> str:
    """稳定绑定 id（≤36 字符），保证重复运行幂等。"""
    raw = f"{scope.revision_id}|{statement_id}|{media_id}".encode("utf-8")
    return "bnd-" + hashlib.sha1(raw).hexdigest()[:30]


def _pick_media_for_statement(
    text: str, media_items: Sequence[Media], cap: int
) -> List[Any]:
    """为一条陈述挑选媒体，返回 ``[(media_id, method, score, reason), ...]``。"""
    picked: Dict[str, Any] = {}

    # ---- 1) 显式编号引用（最高精度，优先保留）
    for kind, label in _explicit_media_refs(text):
        for media in media_items:
            if (media.kind or "") != kind:
                continue
            if _norm_ref_label(label) in legacy_resolver.normalize_media_label(media):
                picked[media.id] = (
                    "explicit_block_ref", 1.0, f"陈述显式引用 {kind} {label}",
                )

    # ---- 2) caption token 重叠（需区分性 token 才认）
    text_tokens = _distinctive_tokens(text)
    if text_tokens:
        for media in media_items:
            if media.id in picked:
                continue
            caption = getattr(media, "caption", "") or ""
            caption_tokens = _distinctive_tokens(caption)
            shared = text_tokens & caption_tokens
            if len(shared) < CAPTION_REF_MIN_SHARED_TOKENS:
                continue
            distinctive = {
                t for t in shared
                if "-" in t or any(ch.isdigit() for ch in t)
                or t in _abbrev_tokens(text) or t in _abbrev_tokens(caption)
            }
            if not distinctive:
                continue
            score = len(shared) / max(1, min(len(text_tokens), len(caption_tokens)))
            picked[media.id] = (
                "caption_ref", round(score, 4),
                f"caption 与陈述共享 {len(shared)} 个 token（区分性：{sorted(distinctive)}）",
            )

    ordered = sorted(
        picked.items(),
        key=lambda kv: (kv[1][0] != "explicit_block_ref", -float(kv[1][1])),
    )
    return [(mid, *rest) for mid, rest in ordered[: max(0, int(cap))]]


def _explicit_media_refs(text: str):
    """抽取陈述里的显式图表引用，产出 ``(kind, label)``。"""
    out = []
    for match in _MEDIA_REF_RE.finditer(text or ""):
        prefix = (match.group(1) or "").lower().rstrip(".")
        if prefix.startswith("fig"):
            kind = "figure"
        elif prefix.startswith("tab"):
            kind = "table"
        elif prefix.startswith("eq"):
            kind = "equation"
        else:
            kind = _REF_KIND.get(prefix, "")
        if kind:
            out.append((kind, match.group(2)))
    return out


def _distinctive_tokens(text: str) -> set:
    return {
        m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")
        if m.group(0).lower() not in _TOKEN_STOPWORDS
    }


def _abbrev_tokens(text: str) -> set:
    return {m.group(0).lower() for m in _ABBREV_RE.finditer(text or "")}


def _norm_ref_label(raw: str) -> str:
    return re.sub(r"\s+", "", (raw or "").strip()).lower()


# =============================================================== review


def review(input: ReviewRequest, actor: Actor, ctx: CallContext) -> ReviewRecord:
    """保存人工复核记录（**只保存记录**，不改历史版本事实）。

    - reviewer 从认证上下文取，不信任请求自报身份；
    - 幂等：同 scope/target/expected_validation_id/decision/reason 返回同记录；
    - 初始 applied_revision_id / job_id 均为 null（由 M11 后续回填）。
    """
    if not isinstance(input, ReviewRequest):
        raise invalid_input("input 必须为 ReviewRequest", field="input")
    if actor is None or not getattr(actor, "is_admin", False):
        raise invalid_input("复核需要管理权限", field="actor")
    scope = input.scope
    _require_scope(scope)

    with session_scope() as db:
        if input.expected_validation_id:
            row = repo.get_validation_row(db, scope.revision_id, input.expected_validation_id)
            if row is None:
                raise conflict("expected_validation_id 已过期或不属于该 revision")

        digest = repo.reason_digest(input)
        existing = repo.find_review_by_dedup(
            db, scope.revision_id, input.target.kind, input.target.id,
            input.decision, digest,
        )
        if existing is not None:
            return repo.review_dto(existing)

        record = ReviewRecord(
            id=new_id(),
            request=input,
            reviewer=getattr(actor, "name", "anonymous"),
            created_at=utc_now(),
            applied_revision_id=None,
            job_id=None,
        )
        repo.insert_review(db, record)
        repo.audit(db, kind="review_created", scope=scope, actor=record.reviewer,
                   payload={"review_id": record.id, "decision": input.decision,
                            "target_kind": input.target.kind, "target_id": input.target.id})
        return record


def get_reviews(scope: Scope, ids: List[Id]) -> List[ReviewRecord]:
    with session_scope() as db:
        if ids:
            rows = repo.get_review_rows(db, scope.revision_id, ids)
        else:
            rows = repo.list_review_rows(db, scope.revision_id)
        return [repo.review_dto(row) for row in rows]


def mark_review_applied(
    review_id: Id, new_scope: Scope, job_id: int, ctx: CallContext
) -> ReviewRecord:
    """追加复核应用结果（**幂等**；不修改原 ReviewRequest）。

    必须同 paper/同 source；旧 applied 结果冲突时报 CONFLICT。
    """
    with session_scope() as db:
        row = repo.get_review_row(db, review_id)
        if row is None:
            raise not_found("复核记录不存在")
        if row.paper_id != new_scope.paper_id:
            raise revision_mismatch("应用 scope 与复核记录的 paper 不一致")

        if row.applied_revision_id is not None:
            if row.applied_revision_id != new_scope.revision_id:
                raise conflict("该复核已应用到另一 revision，不能覆盖")
            if row.job_id is not None and row.job_id != job_id:
                raise conflict("该复核已由另一 job 应用")
            return repo.review_dto(row)   # 幂等重放

        # 新 scope 必须与复核来源同 source（复核不得跨论文/跨源套用）
        from app.models.source import RevisionORM

        old_revision = db.get(RevisionORM, row.revision_id)
        new_revision = db.get(RevisionORM, new_scope.revision_id)
        if new_revision is None:
            raise not_found("目标 revision 不存在")
        if new_revision.paper_id != row.paper_id:
            raise revision_mismatch("目标 revision 不属于该 paper")
        if old_revision is not None and new_revision.source_document_id != old_revision.source_document_id:
            raise revision_mismatch("复核必须应用于同一源文件的派生 revision")

        row.applied_revision_id = new_scope.revision_id
        row.job_id = job_id
        repo.audit(db, kind="review_applied", scope=new_scope,
                   actor=ctx.request_id or "system",
                   payload={"review_id": review_id, "job_id": job_id})
        return repo.review_dto(row)


# =============================================================== export


def export(
    scope: Scope,
    claims: List[ClaimRecord],
    statements: List[VerifiedStatement],
    media: List[Media],
) -> EvidenceExport:
    """导出证据清单（**仅列清单，不含论文全文/PDF/base64**）。

    M04 不调用 M06：claims/statements 由 API 查询层收集后传入。
    """
    evidence_ids: List[str] = []
    for stmt in statements:
        evidence_ids.extend(stmt.evidence_ids)
    for claim in claims:
        evidence_ids.extend(claim.evidence_ids)
    unique_ids = list(dict.fromkeys(evidence_ids))

    with session_scope() as db:
        source_hash: Optional[str] = None
        from app.models.source import RevisionORM, SourceDocumentORM

        revision = db.get(RevisionORM, scope.revision_id)
        if revision is not None and revision.source_document_id:
            src = db.get(SourceDocumentORM, revision.source_document_id)
            if src is not None:
                source_hash = src.sha256
        # 校验：claims/statements 必须属于本 scope
        for claim in claims:
            if claim.scope.paper_id != scope.paper_id or claim.scope.revision_id != scope.revision_id:
                raise revision_mismatch("导出的 claim 不属于该 scope")

        evidence: List[EvidenceRecord] = []
        validations: List[ValidationReport] = []
        seen_validations = set()
        for ev_id in unique_ids:
            rows = repo.get_evidence_rows(db, scope.revision_id, [ev_id])
            if not rows:
                continue
            record = repo.evidence_dto(scope, rows[0])
            evidence.append(record)
            if record.validation_id and record.validation_id not in seen_validations:
                seen_validations.add(record.validation_id)
                vrow = repo.get_validation_row(db, scope.revision_id, record.validation_id)
                if vrow is not None:
                    validations.append(
                        repo.validation_dto(scope, vrow, [])
                    )

    return EvidenceExport(
        scope=scope,
        source_sha256=source_hash,
        claims=list(claims),
        statements=list(statements),
        evidence=evidence,
        media=list(media),
        validations=validations,
        generated_at=utc_now(),
    )


__all__ = [
    "validate",
    "save_report",
    "get_evidence",
    "get_evidence_with_validation",
    "get_anchor",
    "resolve_legacy",
    "bind",
    "get_bindings",
    "get_verified_media_for_claims",
    "review",
    "get_reviews",
    "mark_review_applied",
    "export",
]
