"""M13 — 旧兼容薄壳（REFACTOR_SPEC §5.11）。

保留旧函数签名 ``get_graph(db: Session, paper_id: int) -> dict``，
内部转发到 canonical ``app.modules.graph``。**不要再往这里加业务逻辑。**

历史 API 仍可能被外部脚本/旧客户端调用；签名与返回形状保持不变。
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session


def get_graph(db: Session, paper_id: int) -> dict:
    """旧签名：React-Flow 友好的 ``{nodes, edges}``；转发到模块适配器。"""
    from app.modules import graph as _graph

    return _graph.get_graph(db, paper_id)


__all__: List[str] = ["get_graph"]
