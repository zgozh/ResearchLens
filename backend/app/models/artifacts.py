"""M00 — 页 / 块 / 锚点 / 页码映射 / 媒体 / 结构化产物 ORM（§5.2、§5.3、§5.5）。"""
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


class PageORM(Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("revision_id", "pdf_page_index", name="uq_page_revision_index"),
        Index("ix_page_scope", "paper_id", "revision_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    pdf_page_index: Mapped[int] = mapped_column(Integer)
    page_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label_status: Mapped[str] = mapped_column(String(16), default="unknown")
    width_pt: Mapped[float] = mapped_column(Float, default=0.0)
    height_pt: Mapped[float] = mapped_column(Float, default=0.0)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    cropbox_pdf: Mapped[list] = mapped_column(JSON, default=list)
    text: Mapped[str] = mapped_column(Text, default="")
    text_origin: Mapped[str] = mapped_column(String(24), default="source_extraction")
    preview_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    extraction_quality: Mapped[str] = mapped_column(String(16), default="text")


class BlockORM(Base):
    __tablename__ = "blocks"
    __table_args__ = (
        Index("ix_block_revision_page_ordinal", "revision_id", "page_id", "ordinal"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    page_id: Mapped[str] = mapped_column(String(36), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(24), default="paragraph")
    text: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(24), default="source_extraction")
    anchor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    media_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    section_path: Mapped[list] = mapped_column(JSON, default=list)
    raw_ref: Mapped[dict] = mapped_column(JSON, default=dict)
    language: Mapped[str] = mapped_column(String(16), default="")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AnchorORM(Base):
    __tablename__ = "anchors"
    __table_args__ = (Index("ix_anchor_scope", "paper_id", "revision_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    source_document_id: Mapped[str] = mapped_column(String(36), default="")
    precision: Mapped[str] = mapped_column(String(16), default="page")
    segments: Mapped[list] = mapped_column(JSON, default=list)
    transform: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PageLabelMappingORM(Base):
    __tablename__ = "page_label_mappings"
    __table_args__ = (
        Index("ix_label_scope_label", "paper_id", "revision_id", "page_label"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    page_label: Mapped[str] = mapped_column(String(64))
    pdf_page_index: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(24), default="printed_ocr")
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    source_block_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class MediaORM(Base):
    __tablename__ = "media"
    __table_args__ = (
        Index("ix_media_scope_kind", "paper_id", "revision_id", "kind"),
        # legacy_no 是**按 kind** 的兼容编号：图1/图2、表1/表2、公式1 各自独立。
        # 契约依据：§5.4 兼容整数编号；adapters 按 kind 分别收集 figure_refs/table_refs；
        # legacy 旧表本就是 figures.fig_no 与 tables.table_no 两套编号；前端 RichText
        # 分别用 fig_no/table_no 查找。若约束不含 kind，则同 revision 的第一张图和
        # 第一个公式都取 legacy_no=1 → 撞唯一约束 → 整个 media 阶段失败。
        UniqueConstraint(
            "revision_id", "kind", "legacy_no",
            name="uq_media_revision_kind_legacy_no",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="figure")
    original_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    legacy_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    #: 另一语言 caption（迁移 0006）：中英双语 caption 拆开后主语言进 caption、
    #: 另一种进这里，做到"展示不乱"且"信息不丢"。
    caption_alt: Mapped[str] = mapped_column(Text, default="")
    anchor_ids: Mapped[list] = mapped_column(JSON, default=list)
    original_asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    thumbnail_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ArtifactBlobORM(Base):
    """结构 / 图谱 / 讲解 / 地图等聚合产物（按 revision+kind 唯一，整体赋值防 JSON 脏检测问题）。"""

    __tablename__ = "artifact_blobs"
    __table_args__ = (
        UniqueConstraint("revision_id", "kind", name="uq_artifact_revision_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"), index=True)
    revision_id: Mapped[str] = mapped_column(String(36), index=True)
    #: 判别符。既有取值：``graph`` / ``presentation`` / ``page_preview:<sha256>``。
    #: 页预览用 ``kind`` 承载 64 位缓存键，故必须 ≥ 13+1+64=78；原为 32 ——
    #: SQLite 不校验长度所以单测没发现，Postgres 上直接 ``StringDataRightTruncation``
    #: 让 /pages/{n}/preview 全部 500（ADR-0023）。
    kind: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


__all__ = [
    "PageORM", "BlockORM", "AnchorORM", "PageLabelMappingORM", "MediaORM", "ArtifactBlobORM",
]
