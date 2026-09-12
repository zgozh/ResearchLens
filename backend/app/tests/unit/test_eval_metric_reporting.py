"""评测**报告口径**的回归测试（ADR-0052）。

三处真实缺陷，都属"值算出来了但被藏起来 / 口径不对"：

1. 投影层把非 ``measured`` 一律丢成 null → ``proxy`` 指标（规格**允许**报告，
   只要求标明）被前端显示成"未评测"；
2. ``recovery_success_rate`` 只吃 warnings、且只认 ``*_failed`` 码 → 我们真实
   发生的降级（``citation_recovered`` / ``extractive_fallback``）一个都不算，
   该指标**永远 not_evaluated**；
3. ``qa_first_verified_ms`` 此前用 **navigation_check 的页面跳转时延**冒充
   "首个经验证答案句耗时"，口径完全不对。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.contracts.evaluation import (
    EvaluationReport,
    GoldenQuestion,
    MetricEntry,
    MetricValue,
)
from app.contracts.common import Scope
from app.modules.evaluation import metrics as M

_SCOPE = Scope(paper_id=1, revision_id="rev-metric-reporting")


def _entry(name: str, value, status: str = "measured") -> MetricEntry:
    return MetricEntry(name=name, value=MetricValue(value=value, status=status))


def _answer(codes=(), statements=(), grounded: bool = False, elapsed_ms: int = 0):
    return SimpleNamespace(
        warnings=[SimpleNamespace(code=c) for c in codes],
        statements=list(statements),
        grounded=grounded,
        usage=SimpleNamespace(elapsed_ms=elapsed_ms),
    )


def _qa(
    question: str,
    *,
    mode: str = "generated",
    statements=(),
    text: str = "",
    grounded: bool = False,
):
    """构造一条评测输入用的 AnswerRecord 形状（只需指标读到的字段）。"""
    return SimpleNamespace(
        question=question,
        mode=mode,
        statements=list(statements),
        text=SimpleNamespace(text=text),
        grounded=grounded,
        warnings=[],
        usage=SimpleNamespace(elapsed_ms=1),
    )


def _golden(question: str, answerable: bool):
    return GoldenQuestion(id=f"g-{question}", scope=_SCOPE, question=question,
                          answerable=answerable)


# ------------------------- 0. 「拒答」的判据（不是 grounded=False）


class TestRefusalPredicate:
    """``grounded=False`` 只表示"未完全核验通过"，**不等于拒答**。

    实测（live，3 篇真实论文）：``refusal_metrics`` 用 ``grounded is False`` 当拒答，
    于是 paper 1 里一条 ``mode=generated``、**交付了 3 条答案句**的回答被算成"误拒"，
    ``answerable_false_refusal_rate`` 被虚报成 0.5（实际 0）。拒答的真判据是
    ``mode == "abstained"``（``qa/service.py`` 也这么定义：无句子才叫拒答）。
    """

    def test_delivered_but_not_fully_grounded_is_not_a_refusal(self):
        """交付了句子、只是没完全核验通过 → **不算误拒**（当前实现会算，故先失败）。"""
        q = "可回答问题"
        answers = [
            _qa(q, mode="generated", statements=["s1", "s2", "s3"], text="有内容",
                grounded=False),
        ]
        _, false_refusal = M.refusal_metrics(answers, [_golden(q, True)])
        assert false_refusal.value.status == "measured"
        assert false_refusal.value.value == 0.0, "交付了答案却记成误拒 = 指标失真"
        assert false_refusal.value.numerator == 0.0

    def test_abstained_counts_as_false_refusal(self):
        q = "可回答问题"
        answers = [_qa(q, mode="abstained", statements=[], text="", grounded=False)]
        _, false_refusal = M.refusal_metrics(answers, [_golden(q, True)])
        assert false_refusal.value.value == 1.0
        assert false_refusal.value.numerator == 1.0

    def test_abstained_counts_as_correct_refusal_on_unanswerable(self):
        q = "不可回答问题"
        answers = [_qa(q, mode="abstained", statements=[], text="", grounded=False)]
        refusal, _ = M.refusal_metrics(answers, [_golden(q, False)])
        assert refusal.value.value == 1.0

    def test_extractive_mode_is_delivery_not_refusal(self):
        q = "可回答问题"
        answers = [_qa(q, mode="extractive", statements=["s"], text="原文", grounded=False)]
        _, false_refusal = M.refusal_metrics(answers, [_golden(q, True)])
        assert false_refusal.value.value == 0.0

    def test_mode_missing_falls_back_to_delivery_check(self):
        """没有 ``mode`` 字段时按"是否交付内容"判：有句子/有文本就不是拒答。"""
        q = "可回答问题"
        noisy = SimpleNamespace(question=q, statements=["s"], grounded=False)
        empty = SimpleNamespace(question=q, statements=[], grounded=False)
        _, only_delivered = M.refusal_metrics([noisy], [_golden(q, True)])
        assert only_delivered.value.value == 0.0
        _, only_empty = M.refusal_metrics([empty], [_golden(q, True)])
        assert only_empty.value.value == 1.0


# ------------------------------------------------- 1. proxy 必须如实呈现


class TestProxyVisible:
    def test_proxy_value_is_reported_and_named(self):
        """proxy 有值 → 写进 metrics 值 + 登记进 proxy 名单（不是 null / not_evaluated）。"""
        from app.modules.evaluation import legacy

        report = EvaluationReport(
            scope=_SCOPE,
            id="e1",
            metrics=[
                _entry("quote_exact_rate", 1.0, "measured"),
                _entry("unsupported_fact_escape_rate", 0.0, "proxy"),
                _entry("support_precision", None, "not_evaluated"),
            ],
        )
        out = legacy.to_legacy_evaluation(report)
        assert out["metrics"]["unsupported_fact_escape_rate"] == 0.0
        assert "unsupported_fact_escape_rate" in out["metrics"]["proxy"]
        assert "unsupported_fact_escape_rate" not in out["metrics"]["not_evaluated"]

    def test_not_evaluated_stays_null_and_is_not_proxy(self):
        """not_evaluated 仍是不写 0 的 null，且不得混进 proxy 名单。"""
        from app.modules.evaluation import legacy

        report = EvaluationReport(
            scope=_SCOPE,
            id="e2",
            metrics=[_entry("support_recall", None, "not_evaluated")],
        )
        out = legacy.to_legacy_evaluation(report)
        assert out["metrics"]["support_recall"] is None
        assert out["metrics"]["proxy"] == []
        assert "support_recall" in out["metrics"]["not_evaluated"]

    def test_measured_not_in_proxy(self):
        from app.modules.evaluation import legacy

        report = EvaluationReport(
            scope=_SCOPE, id="e3", metrics=[_entry("anchor_page_accuracy", 1.0)]
        )
        out = legacy.to_legacy_evaluation(report)
        assert out["metrics"]["proxy"] == []
        assert out["metrics"]["anchor_page_accuracy"] == 1.0

    def test_unevaluated_overall_score_is_none_not_zero(self):
        """**未评估的综合评分必须是 null**：旧实现为迁就 NOT NULL 列填 0.0，
        实测 curl 顶层返回 ``"overall_score": 0.0``，会被读成"评了 0 分"（ADR-0055）。"""
        from app.modules.evaluation import legacy

        report = EvaluationReport(
            scope=_SCOPE, id="e4",
            metrics=[_entry("support_precision", None, "not_evaluated")],
        )
        out = legacy.to_legacy_evaluation(report)
        assert out["overall_score"] is None, "不得用 0 冒充未评估"
        assert out["metrics"]["overall_score_available"] is False
        assert out["metrics"]["overall_score_canonical"] is None

    def test_adapters_projection_also_returns_none(self):
        """两处投影（modules/legacy 与 schemas/adapters）口径必须一致。"""
        from app.schemas import adapters

        report = EvaluationReport(
            scope=_SCOPE, id="e5",
            metrics=[_entry("support_precision", None, "not_evaluated"),
                     _entry("unsupported_fact_escape_rate", 0.0, "proxy")],
        )
        out = adapters.to_legacy_evaluation(report)
        assert out.overall_score is None
        assert out.metrics["overall_score_available"] is False
        assert out.metrics["unsupported_fact_escape_rate"] == 0.0
        assert out.metrics["proxy"] == ["unsupported_fact_escape_rate"]


# --------------------------------- 2. recovery_success_rate 按答案粒度


class TestRecoverySuccessRate:
    def test_no_degradation_is_not_evaluated(self):
        entry = M.recovery_success_rate([_answer(["ok"])])
        assert entry.value.status == "not_evaluated"
        assert entry.value.value is None

    def test_real_degradation_codes_count(self):
        """我们真实发生的降级码必须被认出来（旧实现只认 *_failed）。"""
        answers = [
            _answer(["citation_recovered"], statements=["s1"]),
            _answer(["extractive_fallback"], statements=["s2"]),
            _answer(["quote_trimmed"], statements=["s3"], grounded=True),
        ]
        entry = M.recovery_success_rate(answers)
        assert entry.value.status == "measured"
        assert entry.value.value == 1.0
        assert entry.value.denominator == 3

    def test_degradation_without_delivery_counts_as_failure(self):
        """降级后**没交付**（无答案句也不 grounded）→ 记失败，不再默认"每次都补上了"。"""
        answers = [
            _answer(["retrieval_failed"], statements=[]),
            _answer(["citation_recovered"], statements=["s"]),
        ]
        entry = M.recovery_success_rate(answers)
        assert entry.value.value == 0.5
        assert entry.value.denominator == 2

    def test_rated_per_answer_not_per_warning(self):
        """同一次回答里出现 5 条降级告警，分母只能算 1 —— 旧实现按告警条数会把分母灌水。"""
        entry = M.recovery_success_rate(
            [_answer(["citation_recovered"] * 5, statements=["s"])]
        )
        assert entry.value.denominator == 1
        assert entry.value.value == 1.0


# -------------------------------------- 3. qa_first_verified_ms 口径


class TestFirstVerifiedLatency:
    def test_only_answers_with_sentences_count(self):
        """拒答（无句子）的耗时不算"首个经验证答案句"延迟，只算在总耗时里。"""
        answers = [
            _answer(statements=[], elapsed_ms=9999),      # 拒答：快/慢都与首句无关
            _answer(statements=["s"], elapsed_ms=1000),
            _answer(statements=["s"], elapsed_ms=3000),
        ]
        entries = {e.name: e.value for e in M.timing_metrics(answers)}
        assert entries["qa_first_verified_ms"].value == 2000.0
        assert entries["qa_total_ms"].value == (9999 + 1000 + 3000) / 3
        assert "answer_elapsed_with_sentences" in entries["qa_first_verified_ms"].method

    def test_all_refused_is_not_evaluated_not_zero(self):
        entries = {e.name: e.value for e in M.timing_metrics(
            [_answer(statements=[], elapsed_ms=10)]
        )}
        assert entries["qa_first_verified_ms"].status == "not_evaluated"
        assert entries["qa_first_verified_ms"].value is None
        assert entries["qa_total_ms"].value == 10.0

    def test_ingest_ms_passthrough(self):
        entries = {e.name: e.value for e in M.timing_metrics([], ingest_ms=12345.0)}
        assert entries["ingest_ms"].value == 12345.0
        assert entries["ingest_ms"].status == "measured"
