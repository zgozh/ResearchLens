"""M00 — 检索索引 ORM（§5.6、§5.14）。

向量以 JSON 数组存储，保证 SQLite 与 Postgres 行为一致（第一版不引入 pgvector
Python 包作为前提；Postgres 可用时由检索模块以参数化 SQL 使用 pgvector）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
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


class ChunkORM(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunk_scope", "paper_id", "revision_id"),
        UniqueConstraint("revision_id", "content_hash", name="uq_chunk_revision_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    block_ids: Mapped[list] = mapped_column(JSON, default=list)
    anchor_ids: Mapped[list] = mapped_column(JSON, default=list)
    media_ids: Mapped[list] = mapped_column(JSON, default=list)
    section_path: Mapped[list] = mapped_column(JSON, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding_space: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ChunkVectorORM(Base):
    """单一向量空间的行；空间 = model+dimension+normalization_version。"""

    __tablename__ = "chunk_vectors"
    __table_args__ = (
        UniqueConstraint("chunk_id", "space", name="uq_vector_chunk_space"),
        Index("ix_vector_space", "space"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chunk_id: Mapped[str] = mapped_column(String(36), ForeignKey("chunks.id"), index=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    space: Mapped[str] = mapped_column(String(128))
    dimension: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


__all__ = ["ChunkORM", "ChunkVectorORM"]
