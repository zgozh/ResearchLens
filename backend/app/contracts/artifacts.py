"""M00 — 资产与图表公式契约（REFACTOR_SPEC §5.3）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import Field, field_validator

from .common import (
    AnchorId,
    AssetId,
    ContractModel,
    Hash,
    Id,
    MediaId,
    Origin,
    PaperId,
    RevisionId,
    Scope,
    Score,
    Warning,
)

AssetKind = Literal[
    "source_pdf", "parser_raw", "crop", "thumbnail",
    "page_preview", "extracted_html", "synthetic_svg",
]
MediaKind = Literal["figure", "table", "equation", "page_preview"]


class Asset(ContractModel):
    id: AssetId
    paper_id: PaperId
    revision_id: Optional[RevisionId] = None
    sha256: Hash
    mime: str
    byte_size: int = Field(ge=0)
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    kind: AssetKind
    url: str = ""          # 后端受控资源地址，不暴露磁盘路径
    created_at: Optional[datetime] = None

    @field_validator("sha256")
    @classmethod
    def _hash(cls, v: str) -> str:
        return v.lower()


class AssetWrite(ContractModel):
    paper_id: PaperId
    revision_id: Optional[RevisionId] = None
    kind: AssetKind
    mime: str
    width_px: Optional[int] = None
    height_px: Optional[int] = None


class ByteRange(ContractModel):
    start: int = Field(ge=0)
    end_inclusive: Optional[int] = None


class AssetRead(ContractModel):
    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}

    asset: Asset
    stream: Any = None       # ByteStream（异步 bytes 迭代器）
    total_size: int = Field(ge=0)
    range: Optional[ByteRange] = None


class TableCell(ContractModel):
    """保留完整数据，不截断内容（§5.3）。"""

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    rowspan: int = Field(default=1, ge=1)
    colspan: int = Field(default=1, ge=1)
    text: str = ""
    is_header: bool = False
    anchor_id: Optional[AnchorId] = None


class ExtractedMedia(ContractModel):
    """提取表示；``table_html`` 是不可信提取 HTML，不预设已经安全。"""

    table_html: Optional[str] = None
    table_cells: List[TableCell] = Field(default_factory=list)
    latex: Optional[str] = None
    equation_label: Optional[str] = None
    origin: Origin = "source_extraction"
    warnings: List[Warning] = Field(default_factory=list)


class MediaProvenance(ContractModel):
    representation: Literal["pdf_crop", "mineru_crop", "extracted", "synthetic"]
    source_document_id: Optional[Id] = None
    source_sha256: Optional[Hash] = None
    raw_asset_id: Optional[AssetId] = None
    transform: Literal["crop", "resize", "none"] = "none"
    renderer_version: Optional[str] = None
    verification: Literal["source_bound", "unverified", "synthetic"] = "unverified"


class Media(ContractModel):
    scope: Scope
    id: MediaId
    kind: MediaKind
    original_label: Optional[str] = None      # 原始编号（图 2(a) / 表 S1 / (3)）
    legacy_no: Optional[int] = None           # 兼容整数编号，该 revision 内唯一
    caption: str = ""
    #: 同一对象另一语言的 caption（无损保留，避免"同表双语重复"直接丢掉一种语言）
    caption_alt: str = ""
    anchor_ids: List[AnchorId] = Field(default_factory=list)
    original_asset_ids: List[AssetId] = Field(default_factory=list)
    thumbnail_asset_id: Optional[AssetId] = None
    extracted: Optional[ExtractedMedia] = None
    provenance: MediaProvenance = Field(
        default_factory=lambda: MediaProvenance(representation="extracted")
    )
    excluded: bool = False
    exclusion_reason: Optional[str] = None


class MediaViewPolicy(ContractModel):
    """真实 source 缺原图不允许返回 synthetic（§5.3）。"""

    default_mode: Literal["original", "extracted", "synthetic", "unavailable"]
    original_asset_ids: List[AssetId] = Field(default_factory=list)
    fallback_page_ids: List[Id] = Field(default_factory=list)
    label: str = ""
    warnings: List[Warning] = Field(default_factory=list)


class MediaLinkCandidate(ContractModel):
    media_id: MediaId
    via_anchor_ids: List[AnchorId] = Field(default_factory=list)
    method: Literal["explicit_block_ref", "caption_ref", "same_page", "legacy_regex"]
    score: Optional[Score] = None
    reason: str = ""


class MediaBuildResult(ContractModel):
    scope: Scope
    media: List[Media] = Field(default_factory=list)
    warnings: List[Warning] = Field(default_factory=list)


__all__ = [
    "AssetKind", "MediaKind", "Asset", "AssetWrite", "ByteRange", "AssetRead",
    "TableCell", "ExtractedMedia", "MediaProvenance", "Media",
    "MediaViewPolicy", "MediaLinkCandidate", "MediaBuildResult",
]
