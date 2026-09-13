"""旧前端 DTO 投影 —— **兼容再导出层**（R4-M8 物理迁移后的门面）。

## 这个文件现在是什么

投影实现**全部**搬到了 pp/projection/（R4-M8，ADR D-111）。本模块只做 re-export，
让既有调用方（pi/routes.py、各模块、测试）**一行不用改**继续工作。

## 为什么保留它

schemas/adapters.py 是长期存在的导入路径，很多地方 rom app.schemas.adapters import ...。
物理搬迁不应该强迫几十个调用点同时改名 —— 那是把"机械迁移"变成"大规模改名"，
风险高得多。所以：**实现搬家，导入路径保留**。

## 私有辅助也在再导出之列（这是真踩过的坑）

modules/papers/legacy.py 从**这里**导入 _legacy_step（函数体内 import，只在运行时炸）。
R4-M8 第一版门面只导出了公开函数，于是 GET /api/papers/{id} 全线 500 ——
**单元测试没抓到，是端到端验收 erify_route_a.py 抓到的**。
教训：搬迁后必须 grep **每个**待搬符号（含私有）的引用点，并让门面全量再导出。

## 纪律

本文件**不得出现 def to_legacy_**（	est_projection_dual_read.py 会拦下）——
它必须是纯粹的再导出；真要改投影逻辑，去 pp/projection/。
"""
from __future__ import annotations

from app.projection.dto import (  # noqa: F401
    # 公开投影（含 graph/presentation 的 **Pydantic 包装版**：它们返回
    # GraphOut / PresentationOut，内部委托 projection/graph.py、projection/scene.py。
    # 直接从 projection.graph 再导出会**悄悄改变返回类型** —— 双读一致性测试当场抓到过。
    to_legacy_answer,
    to_legacy_claim,
    to_legacy_claim_summary,
    to_legacy_detail,
    to_legacy_evaluation,
    to_legacy_evidence,
    to_legacy_graph,
    to_legacy_paper,
    to_legacy_presentation,
    # 私有辅助：**必须一并再导出**，否则"函数体内 import"的调用点会在运行时炸
    _as_dict,
    _dedup_ints,
    _figure_out,
    _generation_status,
    _json_scalar,
    _legacy_region_label,
    _legacy_step,
    _section_out,
    _status_to_legacy,
    _table_out,
)

__all__ = [
    "to_legacy_answer",
    "to_legacy_claim",
    "to_legacy_claim_summary",
    "to_legacy_detail",
    "to_legacy_evaluation",
    "to_legacy_evidence",
    "to_legacy_graph",
    "to_legacy_paper",
    "to_legacy_presentation",
]
