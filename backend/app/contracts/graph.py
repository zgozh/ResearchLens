"""M00 — 研究图谱契约（REFACTOR_SPEC §5.5 前半）。"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import Field

from .common import AnchorId, ContractModel, Id, Scope
from .evidence import ArtifactText

NodeKind = Literal[
    "problem", "method", "experiment", "claim", "evidence", "limitation", "media"
]
NodeStatus = Literal["verified", "inference", "contested", "unverified"]
EdgeRelation = Literal["supports", "contradicts", "illustrates", "depends_on", "mentions"]
EdgeStatus = Literal["verified", "candidate"]


class GraphNodeRecord(ContractModel):
    id: Id
    kind: NodeKind
    label: ArtifactText
    claim_id: Optional[str] = Field(default=None, max_length=32)
    evidence_id: Optional[Id] = None
    media_id: Optional[Id] = None
    anchor_ids: List[AnchorId] = Field(default_factory=list)
    status: NodeStatus = "unverified"


class GraphEdgeRecord(ContractModel):
    """端点必须在该图内、同 scope（§5.4 SourceRef 规则）。"""

    id: Id
    source: Id
    target: Id
    relation: EdgeRelation = "supports"
    label: ArtifactText
    binding_ids: List[Id] = Field(default_factory=list)
    status: EdgeStatus = "candidate"


class GraphArtifact(ContractModel):
    scope: Scope
    id: Id
    nodes: List[GraphNodeRecord] = Field(default_factory=list)
    edges: List[GraphEdgeRecord] = Field(default_factory=list)


__all__ = [
    "NodeKind",
    "NodeStatus",
    "EdgeRelation",
    "EdgeStatus",
    "GraphNodeRecord",
    "GraphEdgeRecord",
    "GraphArtifact",
]
