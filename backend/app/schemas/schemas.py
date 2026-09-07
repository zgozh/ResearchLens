"""Pydantic v2 schemas (Spec §19 Claim Schema, §20 Q&A rule)."""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    demo_mode: bool
    version: str


# --- Paper ---
class PaperOut(BaseModel):
    id: int
    slug: str
    title: str
    subtitle: str = ""
    authors: List[str] = Field(default_factory=list)
    year: int
    domain: str
    abstract: str = ""
    tags: List[str] = Field(default_factory=list)
    source_mode: str = "demo"
    status: str = "ready"
    map_summary: dict = Field(default_factory=dict)


class SectionOut(BaseModel):
    heading: str
    kind: str
    page: int
    summary: str = ""
    body: str = ""
    key_points: List[str] = Field(default_factory=list)


class FigureOut(BaseModel):
    fig_no: int
    caption: str
    page: int
    glyph_svg: str = ""
    importance: str = "medium"
    description: str = ""


class TableOut(BaseModel):
    table_no: int
    caption: str
    page: int
    content: List[List[Any]] = Field(default_factory=list)
    key_finding: str = ""


# --- Claims / Evidence ---
class EvidenceOut(BaseModel):
    id: Optional[int] = None
    page: int
    region: str = ""
    region_type: str = "text"
    text: str = ""
    quote: str = ""
    confidence: float = 0.95


class ClaimOut(BaseModel):
    id: Optional[int] = None
    claim_id: str
    statement: str
    type: str = "RESULT"
    confidence: float = 0.9
    status: str = "SUPPORTED"
    rationale: str = ""
    evidence: List[EvidenceOut] = Field(default_factory=list)


class ClaimSummary(BaseModel):
    claim_id: str
    statement: str
    type: str
    confidence: float
    status: str
    evidence_count: int


# --- Graph ---
class GraphOut(BaseModel):
    nodes: List[dict] = Field(default_factory=list)
    edges: List[dict] = Field(default_factory=list)


# --- Presentation ---
class SceneOut(BaseModel):
    order: int
    title: str
    kind: str
    summary: str = ""
    steps: List[Any] = Field(default_factory=list)
    evidence_refs: List[Any] = Field(default_factory=list)
    figure_refs: List[Any] = Field(default_factory=list)
    narration: dict = Field(default_factory=dict)


class PresentationOut(BaseModel):
    scenes: List[SceneOut] = Field(default_factory=list)


# --- Q&A (Spec §20: Answer + Evidence + Confidence) ---
class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = 5


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    confidence: str
    evidence: List[EvidenceOut] = Field(default_factory=list)
    note: str = ""


# --- Evaluation (Spec §21) ---
class EvaluationOut(BaseModel):
    overall_score: float
    metrics: dict


# --- Demo list ---
class DemoPaperListItem(BaseModel):
    slug: str
    title: str
    subtitle: str = ""
    domain: str
    year: int
    tags: List[str] = Field(default_factory=list)
    abstract: str = ""
    accent: str = ""
