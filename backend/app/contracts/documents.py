"""M00 — 文档、页码、块与定位契约（REFACTOR_SPEC §5.2）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import Field, model_validator

from .artifacts import Asset, ExtractedMedia
from .common import (
    AnchorId,
    AssetId,
    BlockId,
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
    validate_rect,
)

BlockKind = Literal[
    "heading", "paragraph", "caption", "table", "equation",
    "image", "header", "footer", "page_number", "other",
]

RevisionKind = Literal["source", "legacy", "synthetic"]
RevisionState = Literal["staging", "readable", "published", "superseded", "failed"]


# --------------------------------------------------------------- 论文 / 源文件


class PaperRecord(ContractModel):
    id: PaperId
    slug: str = Field(max_length=64)
    title: str
    source_mode: Literal["demo", "real", "upload"]
    provenance_class: Literal["synthetic", "source_document"]
    status: Literal["pending", "processing", "ready", "failed"]
    published_revision_id: Optional[RevisionId] = None
    readable_revision_id: Optional[RevisionId] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SourceDocument(ContractModel):
    id: Id
    paper_id: PaperId
    sha256: Hash
    asset_id: AssetId
    byte_size: int = Field(ge=0)
    mime: str = "application/pdf"
    page_count: int = Field(default=0, ge=0)
    source_url: Optional[str] = None      # 已去除访问凭据
    original_filename: Optional[str] = None
    acquisition: Literal["upload", "url", "seed"] = "upload"
    created_at: Optional[datetime] = None


class Revision(ContractModel):
    id: RevisionId
    paper_id: PaperId
    source_document_id: Optional[Id] = None
    kind: RevisionKind = "source"
    state: RevisionState = "staging"
    parser_name: str = ""
    parser_version: str = ""
    normalizer_version: str = ""
    prompt_version: str = ""
    model_snapshot_id: Optional[Id] = None
    artifact_digest: Optional[Hash] = None
    quality: Literal["complete", "partial", "source_only"] = "source_only"
    warnings: List[Warning] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class PaperCreate(ContractModel):
    title: str
    source_mode: Literal["demo", "real", "upload"] = "upload"
    provenance_class: Literal["synthetic", "source_document"] = "source_document"
    idempotency_key: Optional[str] = None


class SourceMetadata(ContractModel):
    original_filename: Optional[str] = None
    source_url: Optional[str] = None
    acquisition: Literal["upload", "url", "seed"] = "upload"


class SourceInput(ContractModel):
    """三种来源之一；URL 获取归后台阶段。"""

    kind: Literal["stored", "pending_upload", "url"]
    source_document_id: Optional[Id] = None
    asset_id: Optional[AssetId] = None
    url: Optional[str] = None
    title: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "SourceInput":
        if self.kind == "stored" and not self.source_document_id:
            raise ValueError("stored 需要 source_document_id")
        if self.kind == "pending_upload" and not self.asset_id:
            raise ValueError("pending_upload 需要 asset_id")
        if self.kind == "url" and not self.url:
            raise ValueError("url 需要 url")
        return self


# --------------------------------------------------------------- 页 / 块 / 坐标


class Page(ContractModel):
    scope: Scope
    id: Id
    pdf_page_index: int = Field(ge=0)     # 0-based 唯一位置主键
    pdf_page_no: int = Field(ge=1)        # 兼容投影 = index + 1
    page_label: Optional[str] = None      # 印刷页
    label_status: Literal["verified", "candidate", "ambiguous", "unknown"] = "unknown"
    width_pt: float = Field(gt=0)
    height_pt: float = Field(gt=0)
    rotation: Literal[0, 90, 180, 270] = 0
    cropbox_pdf: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    text: str = ""
    text_origin: Origin = "source_extraction"
    preview_asset_id: Optional[AssetId] = None
    extraction_quality: Literal["text", "ocr", "image_only", "empty"] = "text"


class PageSummary(ContractModel):
    """Page 去掉 text，但保留 extraction_quality/preview_asset_id。"""

    scope: Scope
    id: Id
    pdf_page_index: int = Field(ge=0)
    pdf_page_no: int = Field(ge=1)
    page_label: Optional[str] = None
    label_status: Literal["verified", "candidate", "ambiguous", "unknown"] = "unknown"
    width_pt: float = Field(gt=0)
    height_pt: float = Field(gt=0)
    rotation: Literal[0, 90, 180, 270] = 0
    extraction_quality: Literal["text", "ocr", "image_only", "empty"] = "text"
    preview_asset_id: Optional[AssetId] = None

    @classmethod
    def from_page(cls, page: Page) -> "PageSummary":
        return cls(
            scope=page.scope, id=page.id, pdf_page_index=page.pdf_page_index,
            pdf_page_no=page.pdf_page_no, page_label=page.page_label,
            label_status=page.label_status, width_pt=page.width_pt, height_pt=page.height_pt,
            rotation=page.rotation, extraction_quality=page.extraction_quality,
            preview_asset_id=page.preview_asset_id,
        )


class RawRef(ContractModel):
    """受控解析索引，不是可执行表达式。"""

    asset_id: AssetId
    record_path: str
    native_id: Optional[str] = None
    bbox_values: Optional[List[float]] = None
    bbox_units: Literal["pixel", "point", "normalized", "unknown"] = "unknown"
    coordinate_frame: Optional[str] = None


class CoordinateTransform(ContractModel):
    """3×3 仿射/齐次矩阵；必须写入经实际 PDF 旋转/CropBox 测试的值。"""

    raw_to_canonical: List[float]
    canonical_to_pdf_unrotated: List[float]
    adapter_version: str = ""

    @model_validator(mode="after")
    def _check(self) -> "CoordinateTransform":
        if len(self.raw_to_canonical) != 9 or len(self.canonical_to_pdf_unrotated) != 9:
            raise ValueError("变换矩阵必须为 9 元素")
        return self


class Block(ContractModel):
    scope: Scope
    id: BlockId
    page_id: Id
    ordinal: int = Field(ge=0)
    kind: BlockKind = "paragraph"
    text: str = ""
    origin: Origin = "source_extraction"
    anchor_id: Optional[AnchorId] = None
    media_id: Optional[MediaId] = None
    section_path: List[str] = Field(default_factory=list)
    raw_ref: Optional[RawRef] = None
    language: str = ""
    content_hash: Optional[Hash] = None


class QuoteSpan(ContractModel):
    """边界是 Unicode code point，半开区间；source_text 必须等于原 Block 的该切片。"""

    block_id: BlockId
    start_cp: int = Field(ge=0)
    end_cp: int = Field(gt=0)
    source_text: str
    match_method: Literal["exact", "normalized"] = "exact"
    normalizer_version: Optional[str] = None

    @model_validator(mode="after")
    def _check(self) -> "QuoteSpan":
        if self.end_cp <= self.start_cp:
            raise ValueError("end_cp 必须大于 start_cp")
        return self


class AnchorSegment(ContractModel):
    """page-only 必须 rect=None / quads=[]。"""

    page_id: Id
    pdf_page_index: int = Field(ge=0)
    page_label: Optional[str] = None
    rect: Optional[List[float]] = None
    quads: List[List[List[float]]] = Field(default_factory=list)
    block_ids: List[BlockId] = Field(default_factory=list)
    quote_spans: List[QuoteSpan] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "AnchorSegment":
        if self.rect is not None:
            validate_rect(self.rect)
        elif self.quads:
            raise ValueError("page-only 段不得带 quads")
        return self


class Anchor(ContractModel):
    scope: Scope
    id: AnchorId
    source_document_id: Id
    precision: Literal["region", "page"] = "page"
    segments: List[AnchorSegment] = Field(default_factory=list)
    transform: Optional[CoordinateTransform] = None
    raw_ref: Optional[RawRef] = None
    created_at: Optional[datetime] = None


class PageLabelMapping(ContractModel):
    """允许标签重号，不设标签唯一。"""

    scope: Scope
    id: Id
    page_label: str
    pdf_page_index: int = Field(ge=0)
    method: Literal["pdf_metadata", "printed_ocr", "manual"]
    status: Literal["verified", "candidate", "ambiguous"]
    source_block_ids: List[BlockId] = Field(default_factory=list)
    confidence: Optional[Score] = None
    review_id: Optional[Id] = None


class PageResolution(ContractModel):
    status: Literal["resolved", "ambiguous", "unresolved"]
    candidates: List[PageLabelMapping] = Field(default_factory=list)


class PageLabelOverride(ContractModel):
    review_id: Id
    source_sha256: Hash
    page_label: str
    pdf_page_index: int = Field(ge=0)


class NavigationTarget(ContractModel):
    """前端不可用 section kind / fig_no 代替它。"""

    scope: Scope
    anchor_id: AnchorId
    segment_index: int = Field(ge=0)


class NavigationResult(ContractModel):
    target: NavigationTarget
    status: Literal["region_highlighted", "page_opened", "unavailable"]
    reason: Optional[str] = None


class PageContent(ContractModel):
    page: Page
    blocks: List[Block] = Field(default_factory=list)
    anchors: List[Anchor] = Field(default_factory=list)


# --------------------------------------------------------------- 解析产物


class ParsedMediaCandidate(ContractModel):
    kind: Literal["figure", "table", "equation", "page_preview"]
    original_label: Optional[str] = None
    caption: str = ""
    #: 同一对象另一语言的 caption（MinerU 常把中英双语拼接成一条）。
    #: 主 caption 只保留文档主导语言的那一段，另一段**无损**留在这里。
    caption_alt: str = ""
    anchor_ids: List[AnchorId] = Field(default_factory=list)
    raw_ref: Optional[RawRef] = None
    extracted: Optional[ExtractedMedia] = None
    embedded_asset_id: Optional[AssetId] = None
    excluded: bool = False
    exclusion_reason: Optional[str] = None


class ParseResult(ContractModel):
    """``ctx.scope`` 必填且须对应 source，不能偷偷创建另一 revision。"""

    scope: Scope
    source: SourceDocument
    pages: List[Page] = Field(default_factory=list)
    blocks: List[Block] = Field(default_factory=list)
    anchors: List[Anchor] = Field(default_factory=list)
    label_mappings: List[PageLabelMapping] = Field(default_factory=list)
    media_candidates: List[ParsedMediaCandidate] = Field(default_factory=list)
    raw_asset_ids: List[AssetId] = Field(default_factory=list)
    parser_name: str = ""
    parser_version: str = ""
    warnings: List[Warning] = Field(default_factory=list)


class ParseSummary(ContractModel):
    scope: Scope
    page_count: int = Field(default=0, ge=0)
    block_ids: List[BlockId] = Field(default_factory=list)
    anchor_ids: List[AnchorId] = Field(default_factory=list)
    media_candidates: List[ParsedMediaCandidate] = Field(default_factory=list)
    raw_asset_ids: List[AssetId] = Field(default_factory=list)
    quality: Literal["complete", "partial", "source_only"] = "source_only"
    warnings: List[Warning] = Field(default_factory=list)


# --------------------------------------------------------------- 旧详情元数据


class LegacyMethodStep(ContractModel):
    id: str
    label: str
    phase: Optional[str] = None
    detail: Optional[str] = None
    text: Optional[str] = None
    figure_ref: Optional[int] = None
    color: Optional[str] = None


class LegacyPaperMetadata(ContractModel):
    subtitle: str = ""
    authors: List[str] = Field(default_factory=list)
    year: int = 2026
    domain: str = "general"
    abstract: str = ""
    tags: List[str] = Field(default_factory=list)
    map_summary: dict = Field(default_factory=dict)
    pdf_url: str = ""
    method_steps: List[LegacyMethodStep] = Field(default_factory=list)


__all__ = [
    "BlockKind", "RevisionKind", "RevisionState",
    "PaperRecord", "SourceDocument", "Revision", "PaperCreate", "SourceMetadata",
    "SourceInput", "Page", "PageSummary", "RawRef", "CoordinateTransform", "Block",
    "QuoteSpan", "AnchorSegment", "Anchor", "PageLabelMapping", "PageResolution",
    "PageLabelOverride", "NavigationTarget", "NavigationResult", "PageContent",
    "ParsedMediaCandidate", "ParseResult", "ParseSummary",
    "LegacyMethodStep", "LegacyPaperMetadata",
]
