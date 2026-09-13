"""M08 — 旧 HTTP 兼容适配（REFACTOR_SPEC §5.11、§5.10 M13）。

``api/routes.py`` 仍以 ``get_graph(db, paper_id)`` 调用本包；本模块把旧
``Session`` 用法翻译成 canonical 入口（内部自开 ``session_scope``），
再投影为 ``GraphOut`` 兼容的 dict。

不做定位校验的伪造：找不到 revision 时返回空图，不猜物理页/不编 ID。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Scope

from . import service as svc


def get_graph(db: Session, paper_id: int) -> Dict[str, List[dict]]:
    """旧签名：返回 React-Flow 友好的 ``{nodes, edges}``。

    只读快照；若该论文无持久化图谱则返回空图（不触发生成）。
    """
    revision_id = _readable_revision(db, paper_id)
    if not revision_id:
        return {"nodes": [], "edges": []}

    artifact = svc.get(Scope(paper_id=paper_id, revision_id=revision_id))
    return to_legacy_graph(artifact)


def to_legacy_graph(artifact) -> Dict[str, List[dict]]:
    """``GraphArtifact → GraphOut``：**R4-M8 后委托唯一实现**（薄委托，不再有逻辑）。

    实现已搬到 `app/projection/graph.py` —— 投影只有一个家（`projection/`），
    本处只做转发。**别把逻辑写回这里**：`test_projection_thin_delegation.py`
    会以"≤45 行且必须有转发调用"把它拦下（D-102 的守卫）。
    """
    from app.projection.graph import to_legacy_graph as _projection

    return _projection(artifact)


def _readable_revision(db: Session, paper_id: int) -> Optional[str]:
    from app.models.models import Paper

    row = db.get(Paper, paper_id)
    if row is None:
        return None
    if row.readable_revision_id:
        return row.readable_revision_id
    # 回退：取该论文任意一条 revision（保持只读，不写库）
    from app.models.source import RevisionORM

    stmt = (
        select(RevisionORM.id)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.desc())
        .limit(1)
    )
    found = db.execute(stmt).first()
    return found[0] if found else None


__all__ = ["get_graph", "to_legacy_graph"]
