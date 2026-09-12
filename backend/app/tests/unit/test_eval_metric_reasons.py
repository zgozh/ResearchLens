"""M10：`not_evaluated` 必须给出**机器可读的原因码**（REFACTOR_PLAN §5.3 MetricValue.reason）。

现状：`MetricValue` 有 `status ∈ {measured, proxy, not_evaluated}` 与 `method`（一句中文，
比如"无 usage 记录"），但**没有稳定的原因码**。于是前端/评测报告只能说"未评测"，
说不清"为什么测不了" —— 用户此前的疑问正是"为什么这里全是未评测"。

本文件锁住：
1. 任何 `not_evaluated` 条目都带**非空** `reason`（稳定的小写蛇形码）；
2. 典型场景拿到**指定**的码（原文无坐标矩形 / usage 缺失）；
3. `not_evaluated ⇒ value is None`（纪律 1：未评估不许填 0）不变；
4. 显式传入的 `reason` 优先于自动映射。
"""
from __future__ import annotations

import os

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""


class TestNotEvaluatedCarriesReason:
    def test_known_method_maps_to_a_stable_code(self):
        from app.contracts.evaluation import not_evaluated

        entry = not_evaluated("input_tokens", method="无 usage 记录", unit="tokens")
        assert entry.value.status == "not_evaluated"
        assert entry.value.value is None
        assert entry.value.reason == "usage_missing_in_answer_rows", entry.value.reason

    def test_unknown_method_still_gets_a_non_empty_code(self):
        from app.contracts.evaluation import not_evaluated

        entry = not_evaluated("whatever", method="某个还没归类的原因")
        assert entry.value.reason, "未评测必须有原因码，哪怕是 unspecified"
        assert entry.value.reason == "unspecified"

    def test_explicit_reason_wins(self):
        from app.contracts.evaluation import not_evaluated

        entry = not_evaluated("x", reason="custom_code", method="无 usage 记录")
        assert entry.value.reason == "custom_code"

    def test_every_reason_is_lower_snake_case(self):
        from app.contracts.evaluation import not_evaluated

        for method in ("无 usage 记录", "无区域 IoU 样本", "无 GoldenClaim 真值", "随便是啥"):
            reason = not_evaluated("m", method=method).value.reason or ""
            assert reason == reason.lower() and " " not in reason, reason


class TestSpecificMetricsGetTheirCode:
    def test_anchor_region_hit_rate_says_why_it_cannot_be_measured(self):
        from app.modules.evaluation import metrics as M

        entry = M.anchor_region_hit_rate([])  # 原文没有坐标矩形
        assert entry.value.status == "not_evaluated"
        assert entry.value.value is None
        assert entry.value.reason == "source_pdf_has_no_coordinate_rects", entry.value.reason

    def test_token_metrics_without_usage_says_usage_missing(self):
        from app.modules.evaluation import metrics as M

        entries = M.token_metrics([])
        assert entries, "token 指标必须出现在报告里（哪怕是未评测）"
        for entry in entries:
            assert entry.value.status == "not_evaluated"
            assert entry.value.reason == "usage_missing_in_answer_rows", (
                entry.name, entry.value.reason,
            )

    def test_timing_metrics_without_answers_is_not_evaluated_with_reason(self):
        from app.modules.evaluation import metrics as M

        entries = M.timing_metrics([])
        for entry in entries:
            assert entry.value.status == "not_evaluated"
            assert entry.value.reason, entry.name


class TestNotEvaluatedNeverFillsZero:
    """纪律 1 的回归锁：未评测 ≠ 0。"""

    def test_status_and_value_are_consistent_for_every_metric_name(self):
        from app.contracts.evaluation import METRIC_NAMES, not_evaluated

        for name in METRIC_NAMES:
            entry = not_evaluated(name, method="本次输入未提供该指标数据")
            assert entry.value.status == "not_evaluated"
            assert entry.value.value is None, name
            assert entry.value.reason, name
