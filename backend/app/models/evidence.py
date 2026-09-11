"""M00 — 陈述 / 证据 / 校验 / 绑定 / 断言 / 结构产物 / 回答 ORM（§5.4、§5.5、§5.7）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.source import new_id, now


class StatementORM(Base):
    __tablename__ = "statements"
    __table_args__ = (
        UniqueConstraint("revision_id", "claim_id", name="uq_statement_revision_claim"),
        Index("ix_statement_scope", "paper_id", "revision_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    claim_id: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="fact")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    qualifiers: Mapped[list] = mapped_column(JSON, default=list)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    origin: Mapped[str] = mapped_column(String(24), default="generated")
    display_class: Mapped[str] = mapped_column(String(24), default="unverified")
    ordinal: Mapped[int] = mapped_column(Integer, default=0)


class ClaimRecordORM(Base):
    __tablename__ = "claim_records"
    __table_args__ = (
        UniqueConstraint("revision_id", "claim_id", name="uq_claim_revision_claim"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_id: Mapped[str] = mapped_column(String(32))
    statement_id: Mapped[str] = mapped_column(String(36))
    type: Mapped[str] = mapped_column(String(16), default="RESULT")
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), default="exhibit")


class EvidenceRowORM(Base):
    __tablename__ = "evidence_records"
    __table_args__ = (
        Index("ix_evidence_revision_claim", "revision_id", "claim_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_id: Mapped[str] = mapped_column(String(32), default="")
    source_document_id: Mapped[str] = mapped_column(String(36), default="")
    anchor_id: Mapped[str] = mapped_column(String(36), default="")
    source_page: Mapped[int] = mapped_column(Integer, default=1)
    source_region: Mapped[list] = mapped_column(JSON, default=list)
    source_text: Mapped[str] = mapped_column(Text, default="")
    quote_spans: Mapped[list] = mapped_column(JSON, default=list)
    media_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locator_status: Mapped[str] = mapped_column(String(16), default="exact")
    support_status: Mapped[str] = mapped_column(String(16), default="unreviewed")
    validation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ValidationORM(Base):
    __tablename__ = "validations"
    __table_args__ = (Index("ix_validation_revision_statement", "revision_id", "statement_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    statement_id: Mapped[str] = mapped_column(String(36), index=True)
    locator_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    quote_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    scope_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    semantic_status: Mapped[str] = mapped_column(String(16), default="unreviewed")
    numeric_status: Mapped[str] = mapped_column(String(16), default="unreviewed")
    qualifier_status: Mapped[str] = mapped_column(String(16), default="unreviewed")
    decision: Mapped[str] = mapped_column(String(16), default="unverified")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    assessor: Mapped[str] = mapped_column(String(16), default="rule")
    assessor_version: Mapped[str] = mapped_column(String(64), default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class BindingORM(Base):
    __tablename__ = "bindings"
    __table_args__ = (
        Index("ix_binding_revision_from", "revision_id", "from_kind", "from_id"),
        Index("ix_binding_revision_to", "revision_id", "to_kind", "to_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    from_kind: Mapped[str] = mapped_column(String(24))
    from_id: Mapped[str] = mapped_column(String(64))
    to_kind: Mapped[str] = mapped_column(String(24))
    to_id: Mapped[str] = mapped_column(String(64))
    relation: Mapped[str] = mapped_column(String(16), default="supports")
    method: Mapped[str] = mapped_column(String(32), default="explicit_block_ref")
    validation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="candidate")
    reason: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SectionRecordORM(Base):
    __tablename__ = "section_records"
    __table_args__ = (Index("ix_section_revision", "revision_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    heading: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="body")
    source_block_ids: Mapped[list] = mapped_column(JSON, default=list)
    anchor_ids: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    key_points: Mapped[list] = mapped_column(JSON, default=list)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)


class MethodStepORM(Base):
    __tablename__ = "method_steps"
    __table_args__ = (Index("ix_method_revision_ordinal", "revision_id", "ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[dict] = mapped_column(JSON, default=dict)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    media_ids: Mapped[list] = mapped_column(JSON, default=list)
    binding_ids: Mapped[list] = mapped_column(JSON, default=list)


class MapItemORM(Base):
    __tablename__ = "map_items"
    __table_args__ = (Index("ix_map_revision_ordinal", "revision_id", "ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="problem")
    text: Mapped[dict] = mapped_column(JSON, default=dict)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    anchor_ids: Mapped[list] = mapped_column(JSON, default=list)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)


class AnswerORM(Base):
    __tablename__ = "answers"
    __table_args__ = (
        Index("ix_answer_revision_cache", "revision_id", "cache_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    question: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[dict] = mapped_column(JSON, default=dict)
    statements: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[str] = mapped_column(String(8), default="Low")
    note: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(16), default="generated")
    model_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    cache_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


__all__ = [
    "StatementORM", "ClaimRecordORM", "EvidenceRowORM", "ValidationORM", "BindingORM",
    "SectionRecordORM", "MethodStepORM", "MapItemORM", "AnswerORM",
]
