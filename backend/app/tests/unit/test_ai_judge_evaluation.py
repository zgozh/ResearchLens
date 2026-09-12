"""AI 评测（LLM 语义裁判）：让自动评测**出得了分**，同时不冒充人工真值。

## 为什么需要

规格要求 `support_precision/recall` **必须有标注集才叫 measured**，所以金标集是
机器草案时它们只能是 `not_evaluated`，`overall_score` 因此恒为 null（"未评测"）。

但"未评测"的真正卡点只有 **support_precision** —— 另外三个核心指标
（`quote_exact_rate` / `anchor_page_accuracy` / `unanswerable_refusal_rate`）
本来就是程序可测的。而 support_precision 卡住的**技术原因**是文本相似度：
实测预测断言与参考断言是"同一事实、不同措辞"，最高相似度只有 0.21（<阈值 0.42），
所以就算有人工真值也匹配不上。

## 决策（ADR-0056）

用 **LLM 裁判按语义判等**（不是放宽阈值）给出精确率/召回率，并且：

1. 这两项标 `status="proxy"`（**不是 measured**）—— 没有人工真值的纪律不变；
2. `support_precision` 数值因此**可见**（此前是 null，用户看到的是"未评测"）；
3. 新增 `ai_overall_score`：四项核心指标"可用（measured 或 AI 裁判 proxy）"时按
   同一公式算分；canonical `overall_score` **仍然只在四项均 measured 时才有值**，
   所以 `test_golden_provenance` 的纪律没有被破坏；
4. AI 裁判结果按输入摘要缓存，避免每次打开评测页都调用一次 LLM。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.evaluation import (  # noqa: E402
    EvaluationInput,
    EvaluationReport,
    GoldenClaim,
    GoldenSet,
    MetricEntry,
    MetricValue,
)
from app.modules.evaluation import ai_grader  # noqa: E402
from app.modules.evaluation import metrics as M  # noqa: E402

_SCOPE = Scope(paper_id=1, revision_id="rev-ai-judge")


def _canned(matches, monkeypatch):
    """把 M05 的 complete 换成受控裁判输出（不发起真实云调用）。

    ``has_llm`` 是只读 property（读 ``llm_api_key``），单测里没有密钥，
    因此按既有惯例打在**类**上（见 ``test_qa_citation_recovery.py``）。
    """
    from app.core.config import settings
    from app.modules import ai as ai_module

    monkeypatch.setattr(
        type(settings), "has_llm", property(lambda self: True), raising=False,
    )

    def fake_complete(request, ctx=None):  # noqa: ANN001
        return SimpleNamespace(
            value=SimpleNamespace(
                matches=[SimpleNamespace(**m) for m in matches],
            ),
            model="fake-judge",
        )

    monkeypatch.setattr(ai_module, "complete", fake_complete)


def _entry(name: str, value, status: str = "measured") -> MetricEntry:
    return MetricEntry(name=name, value=MetricValue(value=value, status=status))


# =============================================================== 裁判单元


class TestSupportJudge:
    def test_semantic_match_counts_as_true_positive(self, monkeypatch):
        """措辞不同的同一事实（相似度只有 0.2）也应被判为命中。"""
        _canned([{"predicted": 0, "golden": 1}], monkeypatch)
        res = ai_grader.judge_support(
            ["本方法在 QM9 上把误差降低了 12%", "训练用 AdamW"],
            ["QM9 数据集的平均绝对误差比基线低 12 个百分点", "优化器选择 AdamW", "其余"],
            new_ctx(_SCOPE),
        )
        assert res is not None
        assert res.matches == [(0, 1)]
        assert res.total_predicted == 2 and res.total_golden == 3

    def test_each_golden_can_only_be_used_once(self, monkeypatch):
        _canned([{"predicted": 0, "golden": 0}, {"predicted": 1, "golden": 0}], monkeypatch)
        res = ai_grader.judge_support(["a", "b"], ["g"], new_ctx(_SCOPE))
        assert res is not None
        assert len(res.matches) == 1, "同一条参考断言不能被两条预测占用"

    def test_each_predicted_can_only_match_once(self, monkeypatch):
        _canned([{"predicted": 0, "golden": 0}, {"predicted": 0, "golden": 1}], monkeypatch)
        res = ai_grader.judge_support(["a"], ["g0", "g1"], new_ctx(_SCOPE))
        assert res is not None
        assert len(res.matches) == 1

    def test_out_of_range_indices_are_ignored(self, monkeypatch):
        _canned([{"predicted": 9, "golden": 0}, {"predicted": 0, "golden": -1}], monkeypatch)
        res = ai_grader.judge_support(["a"], ["g"], new_ctx(_SCOPE))
        assert res is not None
        assert res.matches == []

    def test_empty_inputs_return_none(self):
        assert ai_grader.judge_support([], ["g"], new_ctx(_SCOPE)) is None
        assert ai_grader.judge_support(["p"], [], new_ctx(_SCOPE)) is None

    def test_llm_failure_returns_none_not_zero(self, monkeypatch):
        """调用失败 → None（未判定），**绝不返回 0 分**冒充评测。"""
        from app.modules import ai as ai_module

        def boom(request, ctx=None):  # noqa: ANN001
            raise RuntimeError("judge down")

        monkeypatch.setattr(ai_module, "complete", boom)
        assert ai_grader.judge_support(["p"], ["g"], new_ctx(_SCOPE)) is None

    def test_digest_is_stable_and_sensitive(self):
        a = ai_grader.judge_digest(["p1", "p2"], ["g1"])
        assert a == ai_grader.judge_digest(["p1", "p2"], ["g1"])
        assert a != ai_grader.judge_digest(["p1", "p2改"], ["g1"])
        assert a != ai_grader.judge_digest(["p1", "p2"], ["g1", "g2"])


# ======================================================= AI 综合评分


class TestAiOverallScore:
    def _report(self, **status):
        entries = [
            _entry("support_precision", status.get("precision_value", 0.5),
                   status.get("precision", "proxy")),
            _entry("quote_exact_rate", 1.0, status.get("quote", "measured")),
            _entry("anchor_page_accuracy", 1.0, status.get("anchor", "measured")),
            _entry("unanswerable_refusal_rate", 1.0, status.get("refusal", "measured")),
        ]
        return EvaluationReport(scope=_SCOPE, id="r1", metrics=entries)

    def test_canonical_overall_stays_null_with_proxy_precision(self):
        """**纪律不变**：support_precision 是 proxy → canonical overall_score 必须是 null。"""
        assert M.compute_overall(self._report()) is None

    def test_ai_overall_score_is_computed_from_available_core_metrics(self):
        report = self._report()
        ai = M.compute_ai_overall(report)
        assert ai is not None
        # 0.4*50 + 0.2*100 + 0.2*100 + 0.2*100 = 80
        assert ai == 80.0

    def test_ai_overall_requires_all_four_core_metrics(self):
        report = self._report(refusal="not_evaluated")
        assert M.compute_ai_overall(report) is None, "缺一项核心指标就不给分（不用 0 顶替）"

    def test_both_scores_when_everything_measured(self):
        report = self._report(precision="measured")
        assert M.compute_overall(report) == 80.0
        assert M.compute_ai_overall(report) == 80.0


# ======================================================= 服务层接线


@pytest.fixture
def real_scope():
    """服务层测试要真实 revision（``compute`` 会校验 scope 属于该 paper）。"""
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="AI 裁判测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="j.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return Scope(paper_id=paper.id, revision_id=revision.id)


def _inputs(scope: Scope, *, golden_is_tuning: bool, ai_judge=None) -> EvaluationInput:
    from app.contracts.evidence import VerifiedStatement

    stmt = VerifiedStatement(
        scope=scope, id="s1", claim_id="c1",
        text="本方法在 QM9 上把误差降低了 12%。",
        evidence_ids=["e1"], display_class="verified_fact",
    )
    golden = GoldenSet(
        id="g1", version="gv1", source_hashes=[],
        claims=[GoldenClaim(id="c1", scope=scope,
                            text="QM9 数据集上平均绝对误差比基线低 12%",
                            expected_support="supports")],
        questions=[], anchors=[],
    )
    return EvaluationInput(
        scope=scope, statements=[stmt], golden=golden,
        golden_is_tuning=golden_is_tuning, ai_judge=ai_judge,
        navigation_checks=[],
    )


class TestServiceWiring:
    def test_tuning_golden_without_judge_stays_not_evaluated(self, real_scope):
        """没有 AI 裁判结果（无 ctx / 未配置模型）时仍如实 not_evaluated。"""
        from app.modules import evaluation

        report = evaluation.compute(
            _inputs(real_scope, golden_is_tuning=True), None
        )
        assert report.metric("support_precision").status == "not_evaluated"
        assert report.ai_overall_score is None
        assert report.overall_score is None

    def test_cached_roundtrip_keeps_the_same_value(self, real_scope, monkeypatch):
        """**往返一致**：新判 → 持久化 → 复用，数值必须完全一样。

        这是真实踩过的坑（ADR-0056）：持久化时为了省事只存"总数"、不存配对，
        复用时却用 ``matches`` 重算真阳性 → 算出 0 → **把好数据写成 0 分**，
        而且之后每次都命中这个坏缓存，永远 0。
        """
        from app.contracts.evaluation import AiJudgeResult
        from app.modules import evaluation

        monkeypatch.setattr(
            ai_grader, "judge_support",
            lambda p, g, c: ai_grader.JudgeResult(
                matches=[(0, 0)], total_predicted=len(p), total_golden=len(g),
                model="fresh",
            ),
        )
        fresh = evaluation.compute(_inputs(real_scope, golden_is_tuning=True), new_ctx(real_scope))
        assert fresh.metric("support_precision").value == 1.0

        # 模拟 legacy 层持久化出来的缓存契约：**配对为空、只有计数**
        digest = ai_grader.judge_digest(
            ["本方法在 QM9 上把误差降低了 12%。"],
            ["QM9 数据集上平均绝对误差比基线低 12%"],
        )
        persisted = AiJudgeResult(
            matches=[], true_positive=1, total_predicted=1, total_golden=1, digest=digest,
        )
        reused = evaluation.compute(
            _inputs(real_scope, golden_is_tuning=True, ai_judge=persisted), None
        )
        assert reused.metric("support_precision").value == 1.0, \
            "复用缓存必须与原判一致，不能因为不回写配对而变成 0"
        assert "cached" in reused.metric("support_precision").method

    def test_ai_judge_produces_proxy_precision_and_ai_score(self, real_scope, monkeypatch):
        """LLM 裁判给出命中 → precision 标 proxy（不冒充 measured）+ AI 评分出数。"""
        from app.modules import evaluation

        def fake(predicted, golden, ctx):  # noqa: ANN001
            return ai_grader.JudgeResult(
                matches=[(0, 0)], total_predicted=len(predicted), total_golden=len(golden),
                model="fake-judge",
            )

        monkeypatch.setattr(ai_grader, "judge_support", fake)
        report = evaluation.compute(
            _inputs(real_scope, golden_is_tuning=True), new_ctx(real_scope)
        )
        precision = report.metric("support_precision")
        assert precision.status == "proxy", "AI 裁判给的是 proxy，不能冒充 measured"
        assert precision.value == 1.0
        assert "ai_judge" in precision.method
        assert report.overall_score is None, "canonical 评分仍不出（未人工确认）"
        # 本样本没有证据/锚点/题库，另外三项核心指标不可测 → AI 评分同样**不出**，
        # 而不是拿 0 顶替（live 三篇里这三项都测得到，所以那时会出分）。
        assert report.ai_overall_score is None
        assert any(w.code == "support_metrics_ai_judged" for w in report.warnings)

    def test_ai_score_requires_all_four_core_metrics_even_with_judge(
        self, real_scope, monkeypatch
    ):
        """**即使 AI 裁判给了结论**，缺任何一项核心指标也不出分（不拿 0 顶替）。

        本样本只有 support_precision（AI 裁判）与 anchor_page_accuracy，
        ``quote_exact_rate``（无引文跨度）与 ``unanswerable_refusal_rate``（无答案）不可测，
        所以 AI 评分同样为 None。live 三篇论文这四项都测得到（见 ADR-0056 实测），
        那里才会出分——这正是"缺项即不出分"的诚实行为。
        """
        from app.modules import evaluation
        from app.contracts.evaluation import GoldenAnchor, NavigationCheck

        monkeypatch.setattr(
            ai_grader, "judge_support",
            lambda p, g, c: ai_grader.JudgeResult(
                matches=[(0, 0)], total_predicted=len(p), total_golden=len(g),
                model="fake-judge",
            ),
        )
        inp = _inputs(real_scope, golden_is_tuning=True)
        inp.golden.anchors = [
            GoldenAnchor(id="a1", scope=real_scope, expected_page_index=0),
        ]
        inp.navigation_checks = [
            NavigationCheck(anchor_id="a1", page_correct=True, latency_ms=120),
        ]
        report = evaluation.compute(inp, new_ctx(real_scope))
        assert report.metric("support_precision").status == "proxy"
        assert report.metric("anchor_page_accuracy").value == 1.0
        assert report.metric("quote_exact_rate").status == "not_evaluated"
        assert report.ai_overall_score is None, "缺两项核心指标就不给分"
        assert report.overall_score is None

    def test_cached_judge_result_is_reused_without_llm(self, real_scope, monkeypatch):
        """带**摘要命中**的缓存结果时不得再调用 LLM。"""
        from app.modules import evaluation

        def boom(predicted, golden, ctx):  # noqa: ANN001
            raise AssertionError("缓存命中时不该调用模型")

        monkeypatch.setattr(ai_grader, "judge_support", boom)
        predicted = ["本方法在 QM9 上把误差降低了 12%。"]
        golden = ["QM9 数据集上平均绝对误差比基线低 12%"]
        digest = ai_grader.judge_digest(predicted, golden)
        cached = ai_grader.JudgeResult(
            matches=[(0, 0)], true_positive=1, total_predicted=1, total_golden=1,
            model="cached", digest=digest,
        )
        report = evaluation.compute(
            _inputs(real_scope, golden_is_tuning=True, ai_judge=cached.as_contract()),
            new_ctx(real_scope),
        )
        assert report.metric("support_precision").value == 1.0
        assert "cached" in report.metric("support_precision").method

    def test_stale_cache_is_ignored_and_rejudged(self, real_scope, monkeypatch):
        """摘要不匹配（断言变了）→ 必须重新判，不能用旧结论。"""
        from app.modules import evaluation

        called = {"n": 0}

        def fake(predicted, golden, ctx):  # noqa: ANN001
            called["n"] += 1
            return ai_grader.JudgeResult(
                matches=[], total_predicted=len(predicted), total_golden=len(golden),
                model="fresh",
            )

        monkeypatch.setattr(ai_grader, "judge_support", fake)
        stale = ai_grader.JudgeResult(
            matches=[(0, 0)], total_predicted=1, total_golden=1,
            model="stale", digest="digest-of-something-else",
        )
        report = evaluation.compute(
            _inputs(real_scope, golden_is_tuning=True, ai_judge=stale.as_contract()),
            new_ctx(real_scope),
        )
        assert called["n"] == 1, "摘要不匹配必须重判"
        assert report.metric("support_precision").value == 0.0, "用的是新结论"
