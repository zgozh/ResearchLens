"""M00 — 源文件 / 修订版 / 资产 / 模型快照 ORM（§5.2、§5.3、§5.6、§5.14）。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
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


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class SourceDocumentORM(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("paper_id", "sha256", name="uq_source_paper_hash"),
        Index("ix_source_paper", "paper_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    asset_id: Mapped[str] = mapped_column(String(36), default="")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str] = mapped_column(String(64), default="application/pdf")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    source_url: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[str] = mapped_column(String(256), default="")
    acquisition: Mapped[str] = mapped_column(String(16), default="upload")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RevisionORM(Base):
    __tablename__ = "revisions"
    __table_args__ = (Index("ix_revision_paper_state", "paper_id", "state"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    source_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="source")
    state: Mapped[str] = mapped_column(String(16), default="staging")
    parser_name: Mapped[str] = mapped_column(String(64), default="")
    parser_version: Mapped[str] = mapped_column(String(64), default="")
    normalizer_version: Mapped[str] = mapped_column(String(64), default="")
    prompt_version: Mapped[str] = mapped_column(String(64), default="")
    model_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    artifact_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quality: Mapped[str] = mapped_column(String(16), default="source_only")
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class AssetORM(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("paper_id", "sha256", "kind", name="uq_asset_paper_hash_kind"),
        Index("ix_asset_revision", "revision_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(24), default="parser_raw")
    rel_path: Mapped[str] = mapped_column(String(512), default="")  # 受控相对路径，不外露
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ModelSnapshotORM(Base):
    __tablename__ = "model_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "chat_model", "embedding_model", "capability_version",
            name="uq_snapshot_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(32), default="dashscope")
    base_url: Mapped[str] = mapped_column(String(256), default="")
    chat_model: Mapped[str] = mapped_column(String(128), default="")
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capability_version: Mapped[str] = mapped_column(String(64), default="rl.capabilities/1")
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


__all__ = ["SourceDocumentORM", "RevisionORM", "AssetORM", "ModelSnapshotORM", "new_id", "now"]
