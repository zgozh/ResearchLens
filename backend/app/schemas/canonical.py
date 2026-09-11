"""M13 — canonical HTTP 聚合响应 DTO（REFACTOR_SPEC §5.12）。

这些是 §5.12 新增资源接口的响应结构，跨 contracts（canonical）与
schemas.schemas（旧 PaperOut）两层——因此放在 schemas 层而非 contracts 冻结区。
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts import Asset, Media
from app.contracts.common import Id, Scope, Warning
from app.contracts.documents import Revision, SourceDocument
from app.contracts.evaluation import EvaluationReport
from app.contracts.evidence import (
    ClaimRecord,
    StructureArtifact,
    VerifiedStatement,
)
from app.contracts.graph import GraphArtifact
from app.contracts.jobs import JobRecord
from app.contracts.scene import PresentationArtifact

from .schemas import PaperOut


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Capability(CanonicalModel):
    name: Literal[
        "pdf", "text", "media", "claims", "graph", "presentation", "qa", "evaluation"
    ]
    state: Literal["ready", "partial", "pending", "unavailable"]
    reason: Optional[str] = None


class SectionIndexItem(CanonicalModel):
    id: Id
    heading: str
    anchor_ids: List[str] = Field(default_factory=list)


class MediaIndexItem(CanonicalModel):
    id: Id
    kind: str
    label: Optional[str] = None
    thumbnail_asset_id: Optional[str] = None


class PaperManifest(CanonicalModel):
    """不含全文 / base64 / 原 HTML；服务端只读。"""

    paper: PaperOut
    revision: Optional[Revision] = None
    provenance_class: str = "synthetic"
    source: Optional[SourceDocument] = None
    page_count: int = 0
    section_index: List[SectionIndexItem] = Field(default_factory=list)
    media_index: List[MediaIndexItem] = Field(default_factory=list)
    assets: List[Asset] = Field(default_factory=list)
    capabilities: List[Capability] = Field(default_factory=list)
    active_job: Optional[JobRecord] = None
    warnings: List[Warning] = Field(default_factory=list)


class ExhibitBundle(CanonicalModel):
    scope: Scope
    structure: Optional[StructureArtifact] = None
    claims: List[ClaimRecord] = Field(default_factory=list)
    statements: List[VerifiedStatement] = Field(default_factory=list)
    graph: Optional[GraphArtifact] = None
    presentation: Optional[PresentationArtifact] = None
    evaluation: Optional[EvaluationReport] = None
    capabilities: List[Capability] = Field(default_factory=list)


__all__ = [
    "Capability",
    "SectionIndexItem",
    "MediaIndexItem",
    "PaperManifest",
    "ExhibitBundle",
]
