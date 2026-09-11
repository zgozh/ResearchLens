"""M04 — 证据/校验/绑定/复核的私有持久化（REFACTOR_SPEC §5.4、§5.9、§5.14）。

私有实现：**不构成跨模块调用契约**。所有写入都在调用方给定的短事务 Session 内完成；
本层不开启事务、不做云调用。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.artifacts import Media
from app.contracts.common import ArtifactRef, Scope, SourceRef
from app.contracts.documents import Anchor, AnchorSegment, Block, CoordinateTransform, Page, RawRef
from app.contracts.evidence import (
    Binding,
    EvidenceRecord,
    ReviewRecord,
    ReviewRequest,
    ValidationReason,
    ValidationReport,
)
from app.models.artifacts import AnchorORM, BlockORM, MediaORM, PageORM
from app.models.audit import AuditLogORM, ReviewORM
from app.models.evidence import BindingORM, EvidenceRowORM, ValidationORM
from app.models.source import new_id, now


# --------------------------------------------------------------- 读取：原文


def get_block_rows(db: Session, revision_id: str, ids: Optional[Sequence[str]] = None) -> List[BlockORM]:
    stmt = select(BlockORM).where(BlockORM.revision_id == revision_id)
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(BlockORM.id.in_(list(ids)))
    stmt = stmt.order_by(BlockORM.page_id.asc(), BlockORM.ordinal.asc())
    return list(db.execute(stmt).scalars().all())


def get_page_rows(db: Session, revision_id: str, ids: Optional[Sequence[str]] = None) -> List[PageORM]:
    stmt = select(PageORM).where(PageORM.revision_id == revision_id)
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(PageORM.id.in_(list(ids)))
    stmt = stmt.order_by(PageORM.pdf_page_index.asc())
    return list(db.execute(stmt).scalars().all())


def get_anchor_row(db: Session, revision_id: str, anchor_id: str) -> Optional[AnchorORM]:
    return db.execute(
        select(AnchorORM).where(
            AnchorORM.revision_id == revision_id, AnchorORM.id == anchor_id
        )
    ).scalars().first()


def get_anchor_rows(db: Session, revision_id: str, ids: Sequence[str]) -> List[AnchorORM]:
    if not ids:
        return []
    return list(
        db.execute(
            select(AnchorORM).where(
                AnchorORM.revision_id == revision_id, AnchorORM.id.in_(list(ids))
            )
        ).scalars().all()
    )


def list_anchor_rows(db: Session, revision_id: str) -> List[AnchorORM]:
    return list(
        db.execute(select(AnchorORM).where(AnchorORM.revision_id == revision_id))
        .scalars().all()
    )


def get_media_rows(db: Session, revision_id: str, ids: Optional[Sequence[str]] = None) -> List[MediaORM]:
    stmt = select(MediaORM).where(MediaORM.revision_id == revision_id)
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(MediaORM.id.in_(list(ids)))
    return list(db.execute(stmt).scalars().all())


# --------------------------------------------------------------- 读取：证据


def get_evidence_rows(db: Session, revision_id: str, ids: Sequence[str]) -> List[EvidenceRowORM]:
    if not ids:
        return []
    return list(
        db.execute(
            select(EvidenceRowORM).where(
                EvidenceRowORM.revision_id == revision_id, EvidenceRowORM.id.in_(list(ids))
            )
        ).scalars().all()
    )


def list_evidence_for_claim(db: Session, revision_id: str, claim_id: str) -> List[EvidenceRowORM]:
    return list(
        db.execute(
            select(EvidenceRowORM)
            .where(
                EvidenceRowORM.revision_id == revision_id,
                EvidenceRowORM.claim_id == claim_id,
            )
            .order_by(EvidenceRowORM.created_at.asc())
        ).scalars().all()
    )


def list_evidence_rows(db: Session, revision_id: str) -> List[EvidenceRowORM]:
    return list(
        db.execute(
            select(EvidenceRowORM).where(EvidenceRowORM.revision_id == revision_id)
        ).scalars().all()
    )


def get_validation_row(db: Session, revision_id: str, validation_id: str) -> Optional[ValidationORM]:
    return db.execute(
        select(ValidationORM).where(
            ValidationORM.revision_id == revision_id, ValidationORM.id == validation_id
        )
    ).scalars().first()


def get_validations_for_statement(
    db: Session, revision_id: str, statement_id: str
) -> List[ValidationORM]:
    return list(
        db.execute(
            select(ValidationORM)
            .where(
                ValidationORM.revision_id == revision_id,
                ValidationORM.statement_id == statement_id,
            )
            .order_by(ValidationORM.created_at.asc())
        ).scalars().all()
    )


def list_validation_rows(
    db: Session, revision_id: str, ids: Sequence[str]
) -> List[ValidationORM]:
    if not ids:
        return []
    return list(
        db.execute(
            select(ValidationORM).where(
                ValidationORM.revision_id == revision_id, ValidationORM.id.in_(list(ids))
            )
        ).scalars().all()
    )


# --------------------------------------------------------------- 写入：校验


def insert_validation(
    db: Session, report: ValidationReport, evidence_rows: Sequence[EvidenceRowORM]
) -> ValidationORM:
    row = ValidationORM(
        id=report.id,
        paper_id=report.scope.paper_id,
        revision_id=report.scope.revision_id,
        statement_id=report.statement_id,
        locator_valid=report.locator_valid,
        quote_valid=report.quote_valid,
        scope_valid=report.scope_valid,
        semantic_status=report.semantic_status,
        numeric_status=report.numeric_status,
        qualifier_status=report.qualifier_status,
        decision=report.decision,
        evidence=[e.id for e in evidence_rows],
        reasons=[r.model_dump() for r in report.reasons],
        assessor=report.assessor,
        assessor_version=report.assessor_version,
        confidence=report.confidence,
    )
    db.add(row)
    return row


def insert_evidence(db: Session, record: EvidenceRecord) -> EvidenceRowORM:
    row = EvidenceRowORM(
        id=record.id,
        paper_id=record.scope.paper_id,
        revision_id=record.scope.revision_id,
        legacy_id=record.legacy_id,
        claim_id=record.claim_id,
        source_document_id=record.source_document_id,
        anchor_id=record.anchor_id,
        source_page=record.source_page,
        source_region=[s.model_dump() for s in record.source_region],
        source_text=record.source_text,
        quote_spans=[q.model_dump() for q in record.quote_spans],
        media_ids=list(record.media_ids),
        confidence=record.confidence,
        confidence_method=record.confidence_method,
        locator_status=record.locator_status,
        support_status=record.support_status,
        validation_id=record.validation_id,
    )
    db.add(row)
    return row


def update_evidence_support(
    db: Session, revision_id: str, evidence_ids: Sequence[str],
    support_status: str, validation_id: str,
) -> None:
    for row in get_evidence_rows(db, revision_id, list(evidence_ids)):
        row.support_status = support_status
        row.validation_id = validation_id


# --------------------------------------------------------------- 写入：绑定


def insert_binding(db: Session, binding: Binding) -> BindingORM:
    row = BindingORM(
        id=binding.id,
        paper_id=binding.scope.paper_id,
        revision_id=binding.scope.revision_id,
        from_kind=binding.from_.kind,
        from_id=binding.from_.id,
        to_kind=binding.to.kind,          # ArtifactRef/SourceRef 都有 kind
        to_id=binding.to.id,
        relation=binding.relation,
        method=binding.method,
        validation_id=binding.validation_id,
        state=binding.state,
        reason=binding.reason,
        score=binding.score,
    )
    db.add(row)
    return row


def get_binding_row(db: Session, revision_id: str, binding_id: str) -> Optional[BindingORM]:
    return db.execute(
        select(BindingORM).where(
            BindingORM.revision_id == revision_id, BindingORM.id == binding_id
        )
    ).scalars().first()


def get_bindings_from(
    db: Session, revision_id: str, kind: str, ref_id: str
) -> List[BindingORM]:
    return list(
        db.execute(
            select(BindingORM).where(
                BindingORM.revision_id == revision_id,
                BindingORM.from_kind == kind,
                BindingORM.from_id == ref_id,
            )
        ).scalars().all()
    )


def list_binding_rows(db: Session, revision_id: str) -> List[BindingORM]:
    return list(
        db.execute(
            select(BindingORM).where(BindingORM.revision_id == revision_id)
        ).scalars().all()
    )


def list_bindings_to(
    db: Session, revision_id: str, kind: str, ids: Sequence[str]
) -> List[BindingORM]:
    if not ids:
        return []
    return list(
        db.execute(
            select(BindingORM).where(
                BindingORM.revision_id == revision_id,
                BindingORM.to_kind == kind,
                BindingORM.to_id.in_(list(ids)),
            )
        ).scalars().all()
    )


# --------------------------------------------------------------- 复核 / 审计


def find_review_by_dedup(
    db: Session, revision_id: str, target_kind: str, target_id: str,
    decision: str, reason_digest: str,
) -> Optional[ReviewORM]:
    return db.execute(
        select(ReviewORM).where(
            ReviewORM.revision_id == revision_id,
            ReviewORM.target_kind == target_kind,
            ReviewORM.target_id == target_id,
            ReviewORM.decision == decision,
            ReviewORM.reason_digest == reason_digest,
        )
    ).scalars().first()


def insert_review(db: Session, record: ReviewRecord) -> ReviewORM:
    req = record.request
    row = ReviewORM(
        id=record.id,
        paper_id=req.scope.paper_id,
        revision_id=req.scope.revision_id,
        request=req.model_dump(mode="json"),
        target_kind=req.target.kind,
        target_id=req.target.id,
        decision=req.decision,
        reason=req.reason,
        reason_digest=reason_digest(req),
        expected_validation_id=req.expected_validation_id,
        reviewer=record.reviewer,
        applied_revision_id=record.applied_revision_id,
        job_id=record.job_id,
    )
    db.add(row)
    return row


def get_review_row(db: Session, review_id: str) -> Optional[ReviewORM]:
    return db.execute(select(ReviewORM).where(ReviewORM.id == review_id)).scalars().first()


def get_review_rows(db: Session, revision_id: str, ids: Sequence[str]) -> List[ReviewORM]:
    if not ids:
        return []
    return list(
        db.execute(
            select(ReviewORM).where(
                ReviewORM.revision_id == revision_id, ReviewORM.id.in_(list(ids))
            )
        ).scalars().all()
    )


def list_review_rows(db: Session, revision_id: str) -> List[ReviewORM]:
    return list(
        db.execute(select(ReviewORM).where(ReviewORM.revision_id == revision_id))
        .scalars().all()
    )


def reason_digest(request: ReviewRequest) -> str:
    payload = "|".join([
        request.scope.revision_id, request.target.kind, request.target.id,
        request.decision, (request.reason or "").strip(),
        str(request.expected_validation_id or ""),
        str(request.corrected_page_index if request.corrected_page_index is not None else ""),
        str(request.page_label or ""),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit(
    db: Session, *, kind: str, scope: Optional[Scope] = None, actor: str = "system",
    job_id: Optional[int] = None, payload: Optional[Dict] = None,
) -> None:
    """审计留痕：只存 ID/hash/摘要，不存原文与 token。"""
    db.add(
        AuditLogORM(
            paper_id=scope.paper_id if scope else None,
            revision_id=scope.revision_id if scope else None,
            job_id=job_id,
            kind=kind,
            actor=actor,
            payload=payload or {},
        )
    )


# --------------------------------------------------------------- DTO 投影


def anchor_dto(scope: Scope, row: AnchorORM) -> Anchor:
    return Anchor(
        scope=scope,
        id=row.id,
        source_document_id=row.source_document_id or "",
        precision=row.precision or "page",
        segments=[AnchorSegment(**seg) for seg in (row.segments or [])],
        transform=CoordinateTransform(**row.transform) if row.transform else None,
        raw_ref=RawRef(**row.raw_ref) if row.raw_ref else None,
        created_at=row.created_at,
    )


def evidence_dto(scope: Scope, row: EvidenceRowORM) -> EvidenceRecord:
    return EvidenceRecord(
        scope=scope,
        id=row.id,
        legacy_id=row.legacy_id,
        claim_id=row.claim_id or "",
        source_document_id=row.source_document_id or "",
        anchor_id=row.anchor_id or "",
        source_page=row.source_page or 1,
        source_region=[AnchorSegment(**seg) for seg in (row.source_region or [])],
        source_text=row.source_text or "",
        quote_spans=[QuoteSpanLike(**q) for q in (row.quote_spans or [])],
        media_ids=list(row.media_ids or []),
        confidence=row.confidence,
        confidence_method=row.confidence_method,
        locator_status=row.locator_status or "exact",
        support_status=row.support_status or "unreviewed",
        validation_id=row.validation_id,
    )


def binding_dto(scope: Scope, row: BindingORM) -> Binding:
    from_payload = {"kind": row.from_kind, "id": row.from_id}
    to_payload = {"kind": row.to_kind, "id": row.to_id}
    if row.to_kind in ("evidence", "media", "anchor", "block"):
        target: object = SourceRef(**to_payload)
    else:
        target = ArtifactRef(**to_payload)
    return Binding(
        scope=scope,
        id=row.id,
        **{"from": ArtifactRef(**from_payload)},
        to=target,
        relation=row.relation,
        method=row.method,
        validation_id=row.validation_id,
        state=row.state,
        reason=row.reason or "",
        score=row.score,
        created_at=row.created_at,
    )


def review_dto(row: ReviewORM) -> ReviewRecord:
    return ReviewRecord(
        id=row.id,
        request=ReviewRequest(**row.request),
        reviewer=row.reviewer,
        created_at=row.created_at,
        applied_revision_id=row.applied_revision_id,
        job_id=row.job_id,
    )


def validation_dto(scope: Scope, row: ValidationORM, evidence: List[EvidenceRecord]) -> ValidationReport:
    return ValidationReport(
        scope=scope,
        id=row.id,
        statement_id=row.statement_id,
        locator_valid=bool(row.locator_valid),
        quote_valid=bool(row.quote_valid),
        scope_valid=bool(row.scope_valid),
        semantic_status=row.semantic_status,
        numeric_status=row.numeric_status,
        qualifier_status=row.qualifier_status,
        decision=row.decision,
        evidence=evidence,
        reasons=[ValidationReason(**r) for r in (row.reasons or [])],
        assessor=row.assessor,
        assessor_version=row.assessor_version or "",
        confidence=row.confidence,
        created_at=row.created_at,
    )


# 避免 contracts.documents.QuoteSpan 与 evidence 的循环引用噪声：直接别名
from app.contracts.documents import QuoteSpan as QuoteSpanLike  # noqa: E402


def new_scope_id() -> str:
    return new_id()


def utc_now() -> datetime:
    return now()


__all__ = [
    "get_block_rows", "get_page_rows", "get_anchor_row", "get_anchor_rows",
    "list_anchor_rows", "get_media_rows",
    "get_evidence_rows", "list_evidence_for_claim", "list_evidence_rows",
    "get_validation_row", "get_validations_for_statement", "list_validation_rows",
    "insert_validation", "insert_evidence", "update_evidence_support",
    "insert_binding", "get_binding_row", "get_bindings_from", "list_binding_rows",
    "list_bindings_to",
    "find_review_by_dedup", "insert_review", "get_review_row", "get_review_rows",
    "list_review_rows", "reason_digest", "audit",
    "anchor_dto", "evidence_dto", "binding_dto", "review_dto", "validation_dto",
    "new_scope_id", "utc_now",
]
