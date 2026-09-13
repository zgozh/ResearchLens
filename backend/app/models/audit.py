"""M00 — 人工复核 / 审计 / 评测报告 ORM（§5.9）。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

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


class ReviewORM(Base):
    """复核记录不可变（只追加 applied_revision_id/job_id）。"""

    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_review_scope", "paper_id", "revision_id"),
        UniqueConstraint(
            "revision_id", "target_kind", "target_id", "decision", "reason_digest",
            name="uq_review_dedup",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    target_kind: Mapped[str] = mapped_column(String(24), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    decision: Mapped[str] = mapped_column(String(24), default="confirm")
    reason: Mapped[str] = mapped_column(Text, default="")
    reason_digest: Mapped[str] = mapped_column(String(64), default="")
    expected_validation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(64), default="anonymous")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    applied_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuditLogORM(Base):
    """审计留痕：只存 ID/hash/摘要，不存原文与 token。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_scope", "paper_id", "revision_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(48), default="")
    actor: Mapped[str] = mapped_column(String(64), default="system")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class EvaluationReportORM(Base):
    __tablename__ = "evaluation_reports"
    __table_args__ = (Index("ix_eval_scope", "paper_id", "revision_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[str] = mapped_column(String(32), default="rl.eval/1")
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[list] = mapped_column(JSON, default=list)
    golden_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class GoldenSetORM(Base):
    __tablename__ = "golden_sets"
    __table_args__ = (
        UniqueConstraint("golden_id", "version", name="uq_golden_id_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    golden_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    is_tuning: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


__all__ = ["ReviewORM", "AuditLogORM", "EvaluationReportORM", "GoldenSetORM"]


class QaStreamAuditORM(Base):
    """M7：每次流式问答落一行审计（**不存正文**，只存事件类型序列）。

    `terminal='none'` 表示"服务端没发出任何终结事件" —— 这是"前端显示被中断"
    的对账数据源；此前线上完全查不到。全部字段从宽（可空），迁移只增不改。
    """

    __tablename__ = "qa_stream_audits"
    __table_args__ = (
        Index("ix_qa_audit_paper_created", "paper_id", "created_at"),
        Index("ix_qa_audit_answer", "answer_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    answer_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: 事件类型名序列，如 ["meta","status","citation","sentence","final"]
    events: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    #: final | error | none（none = 没发出终结事件）
    terminal: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    exception_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    elapsed_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )
