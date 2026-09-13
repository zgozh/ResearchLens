"""M12 — 自动评测模块（REFACTOR_SPEC §3.2、§5.9、§5.10、§6.14）。

固定 15 个指标名；``value=null`` 的 ``not_evaluated`` 不可冒充 0/100。

R4-M5（ADR D-105）：``overall_score`` 现在是**主分「AI 质量评分（自动）」**——
用 AI 口径公式算（四项核心指标"可用"即可，``support_precision`` 允许 AI 裁判 proxy 参与），
并带 ``overall_score_basis="ai_generated"`` 标明来源。人工真值口径已随决策 3 删除。

**M12 不调用 pipeline**，只接收 ``EvaluationInput``；``get`` 不计算、不写库。

API:
- ``compute(input, ctx) -> EvaluationReport``（canonical）
- ``get(scope) -> EvaluationReport``（canonical，只读）
- ``get_current(scope) -> EvaluationReport``（**读报告的推荐入口**：过期就地重算，
  避免 `/exhibits` 与 `/evaluation` 两个入口给出两套数）
- ``run_golden(input, ctx) -> EvaluationReport``
- ``compute_evaluation(db, paper_id) -> models.Evaluation``（旧 HTTP 兼容）
"""
from .golden import load_golden_set, save_golden_set  # noqa: F401
from .legacy import compute_evaluation, to_legacy_evaluation  # noqa: F401
from .metrics import (  # noqa: F401
    ai_core_metric_missing,
    compute_ai_overall,
    one_to_one_match,
    similarity,
)
from .service import ALGORITHM_VERSION, compute, get, get_current, run_golden  # noqa: F401

__all__ = [
    "compute",
    "get",
    "get_current",
    "run_golden",
    "compute_evaluation",
    "to_legacy_evaluation",
    "load_golden_set",
    "save_golden_set",
    "compute_ai_overall",
    "ai_core_metric_missing",
    "one_to_one_match",
    "similarity",
    "ALGORITHM_VERSION",
]
