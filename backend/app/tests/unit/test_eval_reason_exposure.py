"""M10：把"为什么未评测"暴露到**兼容投影**里，并锁住两处投影的一致性。

背景：`MetricValue.reason`（机器可读原因码）已经加好，但前端读的是 legacy 投影
（`metrics` 是个 `name → number|null` 的 dict），其中**只有 `not_evaluated` 名单**，
拿不到原因 —— 界面上仍然只能说"未评测"，说不清"为什么测不了"。

同时本文件是一条**双读一致性**契约测试（M9 的第一片）：
`schemas/adapters.to_legacy_evaluation` 与 `modules/evaluation/legacy.to_legacy_evaluation`
是两份几乎一样的实现，任何一方漏改都会造成"前端有时看得到、有时看不到"。
"""
from __future__ import annotations

from app.contracts.common import Scope, Warning
from app.contracts.evaluation import (
    EvaluationReport,
    MetricEntry,
    MetricValue,
    not_evaluated,
)

SCOPE = Scope(paper_id=7, revision_id="rev-eval")


def _measured(name: str, value: float) -> MetricEntry:
    return MetricEntry(name=name, value=MetricValue(value=value, status="measured"))


def _report() -> EvaluationReport:
    return EvaluationReport(
        scope=SCOPE,
        id="eval-1",
        metrics=[
            _measured("quote_exact_rate", 1.0),
            not_evaluated("anchor_region_hit_rate", method="无区域 IoU 样本"),
            not_evaluated("input_tokens", method="无 usage 记录", unit="tokens"),
        ],
        warnings=[Warning(code="x", message="y", stage="evaluation")],
    )


class TestReasonsAreExposed:
    def test_adapter_projection_carries_reason_codes(self):
        from app.schemas.adapters import to_legacy_evaluation

        out = to_legacy_evaluation(_report())
        reasons = out.metrics["not_evaluated_reasons"]
        assert reasons["anchor_region_hit_rate"] == "source_pdf_has_no_coordinate_rects"
        assert reasons["input_tokens"] == "usage_missing_in_answer_rows"
        assert "quote_exact_rate" not in reasons, "已测指标不该出现在原因表里"

    def test_legacy_projection_carries_reason_codes(self):
        from app.modules.evaluation.legacy import to_legacy_evaluation as legacy_proj

        out = legacy_proj(_report())
        reasons = out["metrics"]["not_evaluated_reasons"]
        assert reasons["anchor_region_hit_rate"] == "source_pdf_has_no_coordinate_rects"
        assert reasons["input_tokens"] == "usage_missing_in_answer_rows"

    def test_two_projections_agree(self):
        """双读一致性：两处投影的名单与原因表必须逐项相等（防"只修一处"）。"""
        from app.modules.evaluation.legacy import to_legacy_evaluation as legacy_proj
        from app.schemas.adapters import to_legacy_evaluation as adapter_proj

        a = adapter_proj(_report()).metrics
        b = legacy_proj(_report())["metrics"]
        assert a["not_evaluated"] == b["not_evaluated"]
        assert a["not_evaluated_reasons"] == b["not_evaluated_reasons"]
        assert a["proxy"] == b["proxy"]

    def test_reason_map_never_claims_a_value(self):
        """纪律 1：原因表只解释"为什么没有值"，不得夹带任何数值。"""
        from app.schemas.adapters import to_legacy_evaluation

        reasons = to_legacy_evaluation(_report()).metrics["not_evaluated_reasons"]
        for name, code in reasons.items():
            assert isinstance(code, str) and code, (name, code)
