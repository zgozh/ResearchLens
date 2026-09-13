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


# ------------------------- 0. 「不可答题是否如实」的判据（R4-M3 改写）


class TestHonestyPredicate:
    """R4-M3 / ADR D-106：**"拒答"这个动作已被产品删除**（决策 1）。

    原语义为什么失效：本类此前断言 ``mode == "abstained"`` 才算"正确拒答"、
    ``answerable_false_refusal_rate`` 衡量"可答题被误拒"。决策 1 之后所有问题都有
    回答 + 置信度，`abstained` 从 `AnswerMode` 删除，**两个指标测的行为都不存在了**：
    ``answerable_false_refusal_rate`` 直接删除（留着就是恒 0 的假指标），
    ``unanswerable_refusal_rate`` 更名 ``unanswerable_honesty_rate``，
    口径改为"对不可答的问题，系统有没有如实说明论文没有依据"。

    保留的原判据内核：**不能拿"grounded=False"当"没回答"** —— 交付了内容就是交付了。
    """

    def test_extractive_is_honest_when_not_grounded(self):
        """抽取式且未整体 grounded → 交付的是逐字原文并标注未过校验 = **如实**。"""
        q = "不可回答问题"
        answers = [_qa(q, mode="extractive", statements=["s"], text="原文", grounded=False)]
        entry = M.honesty_metrics(answers, [_golden(q, False)])
        assert entry.value.status == "measured"
        assert entry.value.value == 1.0
        assert entry.value.denominator == 1

    def test_extractive_but_grounded_is_not_honest(self):
        """抽取式**却 grounded**：等于对不可答题生成了内容 → 不算如实。"""
        q = "不可回答问题"
        answers = [_qa(q, mode="extractive", statements=["s"], text="原文", grounded=True)]
        entry = M.honesty_metrics(answers, [_golden(q, False)])
        assert entry.value.value == 0.0

    def test_not_mentioned_counts_as_honest(self):
        q = "不可回答问题"
        answers = [_qa(q, mode="not_mentioned", statements=[], text="论文中没有提到 X。",
                       grounded=False)]
        entry = M.honesty_metrics(answers, [_golden(q, False)])
        assert entry.value.value == 1.0

    def test_general_counts_as_honest(self):
        """通用回答明确标注"未使用论文证据" → 如实。"""
        q = "不可回答问题"
        answers = [_qa(q, mode="general", statements=[], text="通用解释", grounded=False)]
        entry = M.honesty_metrics(answers, [_golden(q, False)])
        assert entry.value.value == 1.0

    def test_generated_on_unanswerable_is_not_honest(self):
        """对不可答题给出了 grounded 的生成作答（胡说）→ 0 分。"""
        q = "不可回答问题"
        answers = [_qa(q, mode="generated", statements=["s"], text="论文用了 Kubernetes。",
                       grounded=True)]
        entry = M.honesty_metrics(answers, [_golden(q, False)])
        assert entry.value.value == 0.0

    def test_answerable_only_means_not_evaluated(self):
        """只有可答题时没有分母 → not_evaluated（**不是 0**，决策底线 1）。"""
        q = "可回答问题"
        answers = [_qa(q, mode="generated", statements=["s"], text="内容", grounded=True)]
        entry = M.honesty_metrics(answers, [_golden(q, True)])
        assert entry.value.status == "not_evaluated"
        assert entry.value.value is None

    def test_mode_missing_falls_back_to_delivery_check(self):
        """没有 ``mode`` 字段（旧记录）时按"是否交付内容"判。"""
        q = "不可回答问题"
        noisy = SimpleNamespace(question=q, statements=["s"], grounded=False)
        empty = SimpleNamespace(question=q, statements=[], grounded=False)
        assert M.honesty_metrics([noisy], [_golden(q, False)]).value.value == 0.0
        assert M.honesty_metrics([empty], [_golden(q, False)]).value.value == 1.0

    def test_false_refusal_metric_is_gone(self):
        """`answerable_false_refusal_rate` 必须**删除**而不是留成恒 0 的绿条。"""
        q = "可回答问题"
        answers = [_qa(q, mode="generated", statements=["s"], text="有内容", grounded=False)]
        first, second = M.refusal_metrics(answers, [_golden(q, True)])
        assert first.name == "unanswerable_honesty_rate", "旧名已更名"
        assert second is None, "第二项（误拒率）已删除"


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
