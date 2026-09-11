"""M13 — 旧兼容薄壳（REFACTOR_SPEC §5.11）。

保留旧签名 ``compute_evaluation(db, paper_id) -> models.Evaluation``，
内部转发到 ``app.modules.evaluation`` 的兼容适配器。

修复的真实缺陷：
- 旧 GET 路径**直接写库并 commit**；canonical 的 ``get`` 不计算、不写库；
- 旧 ``overall_score`` 在无数据时是 0.0，与「无法评估」不可区分；兼容层现在
  额外给出 ``overall_score_available`` / ``overall_score_canonical`` / ``not_evaluated``。
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session


def compute_evaluation(db: Session, paper_id: int):
    """旧签名：返回 ``models.Evaluation``（保持既有前端读取形状）。"""
    from app.modules import evaluation as _eval

    return _eval.compute_evaluation(db, paper_id)


__all__: List[str] = ["compute_evaluation"]
