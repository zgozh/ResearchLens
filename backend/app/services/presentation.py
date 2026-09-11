"""M13 — 旧兼容薄壳（REFACTOR_SPEC §5.11）。

保留旧签名 ``get_presentation(db: Session, paper_id: int) -> dict``，
内部转发到 ``app.modules.scene`` 的兼容适配器。

修复的真实缺陷：旧实现用正则从正文猜「图N/表N」并据此造 linked 证据，
会把同页任意证据塞进场景。canonical 路径**只由 verified binding 产生 media**，
无关联时返回空 ``linked`` / ``figure_refs`` / ``table_refs``。
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session


def get_presentation(db: Session, paper_id: int) -> dict:
    """旧签名：``{scenes: [...]}``；转发到模块适配器（含 verified 媒体通道）。"""
    from app.modules import scene as _scene

    return _scene.get_presentation(db, paper_id)


__all__: List[str] = ["get_presentation"]
