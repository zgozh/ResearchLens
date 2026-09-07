"""Research Graph assembly (Spec §11/§30) — reads from store and returns
React-Flow-friendly nodes + edges. Section maps graph node kinds to visual facets.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app import models


def get_graph(db: Session, paper_id: int) -> dict:
    nodes = (
        db.query(models.ResearchGraphNode)
        .filter(models.ResearchGraphNode.paper_id == paper_id)
        .all()
    )
    edges = (
        db.query(models.ResearchGraphEdge)
        .filter(models.ResearchGraphEdge.paper_id == paper_id)
        .all()
    )

    node_list = [
        {"id": n.node_id, "label": n.label, "kind": n.kind, "props": n.props or {}}
        for n in nodes
    ]
    edge_list = [
        {"id": f"{e.source}-{e.target}", "source": e.source, "target": e.target, "label": e.label}
        for e in edges
    ]
    return {"nodes": node_list, "edges": edge_list}
