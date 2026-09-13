"""图谱投影 —— **唯一实现**（R4-M8 物理迁移，原 `modules/graph/legacy.py`）。

迁移性质：**纯机械**。函数体逐字搬入，`modules/graph/legacy.to_legacy_graph`
改为薄委托。双读一致性测试（`test_projection_dual_read.py`）是防"搬丢字段"的网。
"""
from __future__ import annotations

from typing import Dict, List


def to_legacy_graph(artifact) -> Dict[str, List[dict]]:
    """``GraphArtifact → GraphOut``：字段名与旧前端契约保持一致。

    **投影层不许静默丢字段**（ADR-0058）：此前 props 白名单里没有 ``media_id``，
    于是前端"图表节点"分支永远拿不到 id —— 用户看到的就是"图表节点没有给出具体的图表"。
    这与 D-48（``_legacy_step`` 丢掉 ``figure_refs``）是同一类缺陷：**白名单式投影**
    一旦漏字段，API 表面看不出任何异常，但功能整块失效。现在补回 ``media_id``，
    并把节点自带的展示事实（``props``）**整体透传**。

    R4-M9 追加：``props.validation``（`{decision, semantic_status, reasons}`）也由
    整体透传带出 —— 图谱证据节点的四分类徽标靠它。
    """
    nodes = [
        {
            "id": n.id,
            "label": (n.label.text if n.label else ""),
            "kind": n.kind,
            "props": {
                "status": n.status,
                "claim_id": n.claim_id,
                "evidence_id": n.evidence_id,
                # 图表节点必须有 media_id，前端才能取图/定位（用户实测反馈）
                "media_id": n.media_id,
                "anchor_ids": list(n.anchor_ids or []),
                **(dict(getattr(n, "props", None) or {})),
            },
        }
        for n in artifact.nodes
    ]
    edges = [
        {
            "id": e.id,
            "source": e.source,
            "target": e.target,
            "label": (e.label.text if e.label else e.relation),
            "relation": e.relation,
            "status": e.status,
        }
        for e in artifact.edges
    ]
    return {"nodes": nodes, "edges": edges}


__all__ = ["to_legacy_graph"]
