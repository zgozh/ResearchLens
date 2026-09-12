"""Pydantic v2 schemas — 旧 HTTP 契约（REFACTOR_SPEC §5.11）。

**兼容纪律**：旧字段名/类型逐项保留（见 §5.11 代码块），新增字段一律可选，
不改变旧字段语义。旧的宽松字段（``content`` / ``steps`` / ``linked`` 等）
在响应模型上允许旧有效值，避免旧数据导致整个详情 500。

新增 canonical 扩展字段（可选）：
- ``provenance_class`` / ``revision_id`` / ``readable_revision_id`` /
  ``published_revision_id`` / ``generation_status``
- ``evidence_id``（新 ID）与旧数字 ``id`` 并存
- ``confidence_assessed`` / ``verification_status`` / ``anchor_id``
- ``image_mime``（不悄悄把 ``image_b64`` 改成 URL）
- ``migration_warnings``（逐项迁移警告，不静默丢字段）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

#: 旧响应模型基类：忽略未知字段（旧库/旧前端可能有额外键）
class LegacyModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class HealthOut(LegacyModel):
    status: str
    demo_mode: bool
    version: str
    # --- 可选扩展（§5.11：可新增 dependencies/warnings）---
    dependencies: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)


# --- Paper ---
class LegacyMethodStepOut(LegacyModel):
    """旧 ``LegacyMethodStep``：id/label 必填，其余可选。"""

    id: str
    label: str
    phase: Optional[str] = None
    detail: Optional[str] = None
    text: Optional[str] = None
    figure_ref: Optional[int] = None
    #: **该步骤自己的**关联图/表编号（可能多个）。由该断言的 ``statement→media``
    #: 绑定得出；此前 DTO 是固定字段表，新字段会被静默丢弃（实测 figure_refs 恒 None）。
    figure_refs: List[int] = Field(default_factory=list)
    table_refs: List[int] = Field(default_factory=list)
    #: 图表编号 → **来源方法**（``explicit_block_ref``/``caption_ref``/``page_proximity``）。
    #: 前端据此把"位置推断"与"题注匹配"分开标注，不让人以为位置推断也是文字证据（ADR-0059）。
    figure_ref_methods: Dict[int, str] = Field(default_factory=dict)
    color: Optional[str] = None


class PaperOut(LegacyModel):
    id: int
    slug: str
    title: str
    subtitle: str = ""
    authors: List[str] = Field(default_factory=list)
    year: int = 2026
    domain: str = "general"
    abstract: str = ""
    tags: List[str] = Field(default_factory=list)
    source_mode: str = "demo"
    status: str = "ready"
    map_summary: Dict[str, Any] = Field(default_factory=dict)
    pdf_url: str = ""
    method_steps: List[Any] = Field(default_factory=list)
    # --- canonical 扩展（全部可选）---
    provenance_class: Optional[str] = None
    revision_id: Optional[str] = None
    readable_revision_id: Optional[str] = None
    published_revision_id: Optional[str] = None
    generation_status: Optional[str] = None


class SectionOut(LegacyModel):
    heading: str
    kind: str
    page: int
    summary: str = ""
    body: str = ""
    key_points: List[str] = Field(default_factory=list)
    #: 本节覆盖的**物理页范围**（1-based）。``page`` 是兼容字段 = ``page_start``；
    #: 前端"阅读该章节正文"据此跳到对应页（此前 ``page`` 恒为 1，永远跳第 1 页）。
    page_start: int = 0
    page_end: int = 0


class FigureOut(LegacyModel):
    fig_no: int
    caption: str
    page: int
    glyph_svg: str = ""
    image_b64: str = ""
    importance: str = "medium"
    description: str = ""
    # --- canonical 扩展 ---
    image_mime: str = "image/png"
    media_id: Optional[str] = None
    #: 真实图资产的可访问 URL（``/api/assets/{id}``）。旧字段 ``image_b64``/
    #: ``glyph_svg`` 是内联渲染时代的产物，canonical 侧不再内联字节；
    #: 前端 ``FigureImage`` 优先用本字段（ADR-0027）。
    image_url: str = ""


class TableOut(LegacyModel):
    table_no: int
    caption: str
    page: int
    content: List[List[Any]] = Field(default_factory=list)
    table_html: str = ""
    key_finding: str = ""
    # --- canonical 扩展 ---
    media_id: Optional[str] = None


class PaperDetail(PaperOut):
    sections: List[SectionOut] = Field(default_factory=list)
    figures: List[FigureOut] = Field(default_factory=list)
    tables: List[TableOut] = Field(default_factory=list)
    method_steps: List[Any] = Field(default_factory=list)
    pages: List[Dict[str, Any]] = Field(default_factory=list)
    accent: str = "#6366F1"
    #: 逐项迁移警告（旧宽松字段不可解析时的降级说明）
    migration_warnings: List[str] = Field(default_factory=list)


# --- Claims / Evidence ---
class EvidenceOut(LegacyModel):
    """旧 ``id`` 继续数字；新 ID 放 ``evidence_id``。"""

    id: Optional[int] = None
    page: int = 1
    region: str = ""
    region_type: str = "text"
    text: str = ""
    quote: str = ""
    confidence: float = 0.95
    # --- canonical 扩展 ---
    evidence_id: Optional[str] = None
    anchor_id: Optional[str] = None
    locator_status: Optional[str] = None
    verification_status: Optional[str] = None
    media_ids: List[str] = Field(default_factory=list)
    confidence_assessed: bool = True
    confidence_method: Optional[str] = None


class ClaimOut(LegacyModel):
    id: Optional[int] = None
    claim_id: str
    statement: str
    type: str = "RESULT"
    confidence: float = 0.9
    status: str = "SUPPORTED"
    rationale: str = ""
    evidence: List[EvidenceOut] = Field(default_factory=list)
    # --- canonical 扩展 ---
    statement_id: Optional[str] = None
    verification_status: Optional[str] = None
    visibility: Optional[str] = None
    revision_id: Optional[str] = None
    confidence_assessed: bool = True
    evidence_ids: List[str] = Field(default_factory=list)


class ClaimSummary(LegacyModel):
    claim_id: str
    statement: str = ""
    type: str
    confidence: float
    status: str
    evidence_count: int
    # --- canonical 扩展 ---
    verification_status: Optional[str] = None
    confidence_assessed: bool = True


# --- Graph ---
class GraphOut(LegacyModel):
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    revision_id: Optional[str] = None


# --- Presentation ---
class SceneOut(LegacyModel):
    order: int
    title: str
    kind: str
    summary: str = ""
    steps: List[Any] = Field(default_factory=list)
    evidence_refs: List[Any] = Field(default_factory=list)
    figure_refs: List[Any] = Field(default_factory=list)
    table_refs: List[Any] = Field(default_factory=list)
    narration: Dict[str, Any] = Field(default_factory=dict)
    linked: List[Any] = Field(default_factory=list)
    # --- canonical 扩展 ---
    media_ids: List[str] = Field(default_factory=list)
    statement_ids: List[str] = Field(default_factory=list)


class PresentationOut(LegacyModel):
    scenes: List[SceneOut] = Field(default_factory=list)
    revision_id: Optional[str] = None


# --- Q&A (Spec §20: Answer + Evidence + Confidence) ---
class AskRequest(BaseModel):
    """旧请求：question 1..2000；top_k 越界由服务层 clamp，不直接 422。"""

    model_config = ConfigDict(extra="ignore")

    question: str = Field(min_length=1, max_length=2000)
    top_k: int = 5


class AskResponse(LegacyModel):
    answer: str
    grounded: bool
    confidence: str
    evidence: List[EvidenceOut] = Field(default_factory=list)
    note: str = ""
    #: ``generated``/``extractive``/``cached``/``abstained``/``general``（ADR-0057）。
    #: ``general`` = 与论文无关的通用回答：前端要把它与"拒答"区分开显示。
    mode: str = ""


# --- Evaluation (Spec §21) ---
class EvaluationOut(LegacyModel):
    #: 未评估时是 **null**，不是 0（ADR-0055 / 迁移 0008）；可用性另见
    #: ``metrics["overall_score_available"]``。
    overall_score: Optional[float] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


# --- Demo list ---
class DemoPaperListItem(LegacyModel):
    slug: str
    title: str
    subtitle: str = ""
    domain: str
    year: int
    tags: List[str] = Field(default_factory=list)
    abstract: str = ""
    accent: str = ""
    source_mode: str = "demo"
    # --- canonical 扩展 ---
    provenance_class: Optional[str] = None


__all__ = [
    "LegacyModel",
    "HealthOut",
    "LegacyMethodStepOut",
    "PaperOut",
    "SectionOut",
    "FigureOut",
    "TableOut",
    "PaperDetail",
    "EvidenceOut",
    "ClaimOut",
    "ClaimSummary",
    "GraphOut",
    "SceneOut",
    "PresentationOut",
    "AskRequest",
    "AskResponse",
    "EvaluationOut",
    "DemoPaperListItem",
]
