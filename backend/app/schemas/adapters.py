"""旧前端 DTO 投影 —— **兼容再导出层**（R4-M8 物理迁移后的门面）。

## 这个文件现在是什么

投影实现**全部**搬到了 pp/projection/（R4-M8）。本模块只做 re-export，
让既有调用方（pi/routes.py、各模块、测试）**一行不用改**继续工作。

## 为什么保留它

schemas/adapters.py 是长期存在的导入路径，很多地方 rom app.schemas.adapters import
to_legacy_paper。物理搬迁不应该强迫几十个调用点同时改名 —— 那是把"机械迁移"变成
"大规模改名"，风险高得多。所以：**实现搬家，导入路径保留**。

## 纪律

本文件**不得出现 def to_legacy_**（	est_projection_dual_read.py 会拦下）——
它必须是纯粹的再导出；真要改投影逻辑，去 pp/projection/。
"""
from __future__ import annotations

from app.projection.dto import (  # noqa: F401
    to_legacy_answer,
    to_legacy_claim,
    to_legacy_claim_summary,
    to_legacy_detail,
    to_legacy_evaluation,
    to_legacy_evidence,
    # 注意：graph / presentation 必须走 dto 里那两个**包装版**
    # （它们返回 GraphOut / PresentationOut Pydantic 对象，并在内部委托
    #  projection/graph.py、projection/scene.py 的 dict 实现）。
    # 直接从 projection.graph 再导出会**悄悄改变本模块的返回类型** —— 调用方会炸。
    to_legacy_graph,
    to_legacy_paper,
    to_legacy_presentation,
)

__all__ = [
    "to_legacy_paper",
    "to_legacy_detail",
    "to_legacy_claim",
    "to_legacy_claim_summary",
    "to_legacy_evidence",
    "to_legacy_graph",
    "to_legacy_presentation",
    "to_legacy_answer",
    "to_legacy_evaluation",
]
