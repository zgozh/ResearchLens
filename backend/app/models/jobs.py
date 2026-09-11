"""M00 — 持久任务状态机 ORM（§5.8）。"""
from __future__ import annotations

import uuid
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
from app.models.source import now


class JobORM(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_job_state_lease", "state", "lease_until"),
        UniqueConstraint("idempotency_key", name="uq_job_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="ingest")
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(24), default="acquire")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fence: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    stage_results: Mapped[list] = mapped_column(JSON, default=list)
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    model_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    budget: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class JobEventORM(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "event_id", name="uq_job_event_seq"),
        Index("ix_job_event_job", "job_id", "event_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=lambda: str(uuid.uuid4()))
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), index=True)
    event_id: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    type: Mapped[str] = mapped_column(String(32), default="stage_started")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class JobStageKeyORM(Base):
    """阶段幂等键：唯一键 (revision_id, stage, input_digest, algorithm_version)。"""

    __tablename__ = "job_stage_keys"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "stage", "input_digest", "algorithm_version",
            name="uq_stage_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True,
                                    default=lambda: str(uuid.uuid4()))
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    stage: Mapped[str] = mapped_column(String(24))
    input_digest: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="succeeded")
    artifact_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


__all__ = ["JobORM", "JobEventORM", "JobStageKeyORM"]
