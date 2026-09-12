"""M00 — 研究图谱契约（REFACTOR_SPEC §5.5 前半）。"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field

from .common import AnchorId, ContractModel, Id, Scope, Warning
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
    #: **展示用的补充事实**（图表节点的编号/图片 URL/页码、证据节点的判定与引文…）。
    #: 用 dict 而不是继续加字段：这些是投影/UI 关心的展示事实，不该污染图谱的语义字段。
    #: 投影层必须原样透传（曾经用白名单投影丢掉 ``media_id``，整块"图表节点"因此失效）。
    props: Dict[str, Any] = Field(default_factory=dict)


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
    #: 图谱构建告警（``isolated_claim`` / ``edge_endpoint_missing`` /
    #: ``evidence_bindings_derived`` …）。此前 ``build()`` 收集了告警却**无处可放**，
    #: 于是"为什么这张图没有边"在 API 里完全不可见——数据缺口必须可见。
    warnings: List[Warning] = Field(default_factory=list)


__all__ = [
    "NodeKind",
    "NodeStatus",
    "EdgeRelation",
    "EdgeStatus",
    "GraphNodeRecord",
    "GraphEdgeRecord",
    "GraphArtifact",
]
