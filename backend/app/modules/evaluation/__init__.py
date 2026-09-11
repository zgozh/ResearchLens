"""M12 — 自动评测模块（REFACTOR_SPEC §3.2、§5.9、§5.10、§6.14）。

固定 15 个指标名；``value=null`` 的 ``not_evaluated`` 不可冒充 0/100；
``overall_score`` 仅在核心人工真值指标均可测时计算，否则 canonical null。
**M12 不调用 pipeline**，只接收 ``EvaluationInput``；``get`` 不计算、不写库。

API:
- ``compute(input, ctx) -> EvaluationReport``（canonical）
- ``get(scope) -> EvaluationReport``（canonical，只读）
- ``run_golden(input, ctx) -> EvaluationReport``
- ``compute_evaluation(db, paper_id) -> models.Evaluation``（旧 HTTP 兼容）
"""
from .golden import load_golden_set, save_golden_set  # noqa: F401
from .legacy import compute_evaluation, to_legacy_evaluation  # noqa: F401
from .metrics import (  # noqa: F401
    compute_overall,
    core_metric_missing,
    one_to_one_match,
    similarity,
)
from .service import ALGORITHM_VERSION, compute, get, run_golden  # noqa: F401

__all__ = [
    "compute",
    "get",
    "run_golden",
    "compute_evaluation",
    "to_legacy_evaluation",
    "load_golden_set",
    "save_golden_set",
    "compute_overall",
    "core_metric_missing",
    "one_to_one_match",
    "similarity",
    "ALGORITHM_VERSION",
]
