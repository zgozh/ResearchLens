"""M13 — 旧兼容薄壳（REFACTOR_SPEC §5.11）。

保留旧签名 ``answer_question(db, paper_id, question, top_k=5) -> AskResponse``，
内部转发到 ``app.modules.qa`` 的兼容适配器（**与流式共用同一服务与同一 gate**）。

修复的真实缺陷：旧实现 ``grounded = not is_generic``——只要回答里没出现
「未提供直接依据」等措辞就标 grounded=True，等于**按措辞猜**。canonical 的
grounded 只由「事实句全部有验证通过的证据 + 无未支持推断」决定，纯拒答恒为 False。
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.schemas.schemas import AskResponse


def answer_question(
    db: Session,
    paper_id: int,
    question: str,
    top_k: int = 5,
) -> AskResponse:
    """旧签名：转发到模块适配器；无证据时为带标记的拒答（仍 200）。"""
    from app.modules import qa as _qa

    return _qa.answer_question(db, paper_id, question, top_k)


__all__: List[str] = ["answer_question"]
