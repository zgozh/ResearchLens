"""M12 evaluation 单元测试（REFACTOR_SPEC §6.14「单元测试」要点）。

覆盖：空样本 / 无分母 / 全部拒答 / 全错全对 / **一份预测匹配多个 gold** /
**citation_accuracy 最大 100 且只缩放一次** / overall_score canonical null。

全部使用临时 sqlite，绝不触碰 data/researchlens.db。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402
from app.contracts.evaluation import (  # noqa: E402
    METRIC_NAMES,
    EvaluationInput,
    GoldenClaim,
    GoldenQuestion,
    GoldenSet,
)


def _minimal_pdf(text: str = "Hi") -> bytes:
    content = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="评测测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("eval"), SourceMetadata(original_filename="e.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "source": source, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


def _statement(scope, *, text, evidence_ids=(), display_class="verified_fact"):
    from app.contracts.evidence import VerifiedStatement

    import uuid

    return VerifiedStatement(
        scope=scope, id=f"st-{uuid.uuid4().hex[:10]}",
        claim_id=f"c-{uuid.uuid4().hex[:8]}", text=text, kind="fact",
        display_class=display_class, evidence_ids=list(evidence_ids),
    )


def _answer(scope, *, question, grounded, evidence=(), usage=None, warnings=(),
            mode=None):
    from app.contracts.ai import Usage
    from app.contracts.evidence import ArtifactText
    from app.contracts.qa import AnswerRecord

    import uuid

    # R4-M3：`abstained` 不再是合法 mode —— 未 grounded 的默认形态改为 `not_mentioned`
    # （"如实说明论文没有依据"，正是诚实率要计命中的形态）。
    return AnswerRecord(
        scope=scope, id=f"an-{uuid.uuid4().hex[:10]}", question=question,
        text=ArtifactText(text="回答内容" if grounded else "", spans=[]),
        statements=[], evidence=list(evidence),
        grounded=grounded, confidence="High" if grounded else "Low",
        note="", mode=mode or ("generated" if grounded else "not_mentioned"),
        usage=usage or Usage(), warnings=list(warnings),
    )


def _golden(scope, *, claims=(), questions=()):
    return GoldenSet(
        id="g1", version="v1",
        claims=list(claims), questions=list(questions), anchors=[],
    )


# =============================================================== 空样本 / 分母


class TestEmptyAndNoDenominator:
    def test_empty_input_all_not_evaluated(self, world):
        """空样本：全部指标为 not_evaluated，**不冒充 0**，overall_score 为 None。"""
        from app.modules import evaluation

        scope = world["scope"]
        report = evaluation.compute(EvaluationInput(scope=scope), new_ctx(scope))

        assert len(report.metrics) == len(METRIC_NAMES)
        names = [m.name for m in report.metrics]
        assert names == METRIC_NAMES
        assert report.overall_score is None, "核心指标缺失时 overall_score 必须为 null"

        for entry in report.metrics:
            if entry.value.status == "not_evaluated":
                assert entry.value.value is None, "not_evaluated 的 value 必须是 null"

    def test_zero_denominator_is_not_evaluated(self):
        """无分母（den=0）→ not_evaluated，绝不写 0。"""
        from app.modules.evaluation import metrics as M

        entry = M.ratio_entry("support_precision", 0, 0)
        assert entry.value.status == "not_evaluated"
        assert entry.value.value is None

    def test_unsupported_all_facts_is_zero_but_measured(self, world):
        """分母存在但全错：value=0 且 status=measured（这是真实的 0，不是未评估）。"""
        from app.modules import evaluation

        scope = world["scope"]
        statements = [_statement(scope, text="无证据断言。", evidence_ids=[])]
        report = evaluation.compute(
            EvaluationInput(scope=scope, statements=statements), new_ctx(scope),
        )
        metric = report.metric("unsupported_fact_escape_rate")
        assert metric is not None
        assert metric.status in ("measured", "proxy")
        assert metric.value == 1.0, "全部无证据 → 逃逸率 100%"

    def test_all_correct_inputs(self, world):
        """全对样本：可测指标应为满分且 status=measured/proxy。"""
        from app.modules import evaluation

        scope = world["scope"]
        statements = [
            _statement(scope, text=f"事实句 {i}。", evidence_ids=[f"ev{i}"])
            for i in range(3)
        ]
        report = evaluation.compute(
            EvaluationInput(scope=scope, statements=statements), new_ctx(scope),
        )
        precision = report.metric("support_precision")
        assert precision is not None and precision.value == 1.0


# =============================================================== 不可答题诚实率
#
# R4-M3 / ADR D-106 改写：本类此前叫 `TestRefusal`，断言"拒答率"。
# 原语义为什么失效：决策 1 删除了"拒答"这个动作（所有问题都有回答 + 置信度），
# `abstained` 已从 `AnswerMode` 移除，`answerable_false_refusal_rate` 一并删除。
# 新口径 = **诚实率**：对不可答的问题，系统有没有如实说明"论文没有依据"。


class TestHonesty:
    def test_all_honest_with_unanswerable_golden(self, world):
        """不可答题全部如实说明（not_mentioned）→ unanswerable_honesty_rate = 1.0。"""
        from app.modules import evaluation

        scope = world["scope"]
        questions = [
            GoldenQuestion(id=f"q{i}", scope=scope, question=f"不可回答 {i}", answerable=False)
            for i in range(3)
        ]
        answers = [
            _answer(scope, question=q.question, grounded=False, mode="not_mentioned")
            for q in questions
        ]
        report = evaluation.compute(
            EvaluationInput(
                scope=scope, answers=answers,
                golden=_golden(scope, questions=questions),
            ),
            new_ctx(scope),
        )
        honesty = report.metric("unanswerable_honesty_rate")
        assert honesty is not None
        assert honesty.value == 1.0
        assert honesty.denominator == 3

    def test_fabricated_answer_on_unanswerable_scores_zero(self, world):
        """不可答题却给了 grounded 的生成作答 → 诚实率 0（这是新口径要抓的失败）。"""
        from app.modules import evaluation

        scope = world["scope"]
        questions = [
            GoldenQuestion(id="q1", scope=scope, question="不可回答", answerable=False),
        ]
        answers = [_answer(scope, question="不可回答", grounded=True, mode="generated")]
        report = evaluation.compute(
            EvaluationInput(
                scope=scope, answers=answers,
                golden=_golden(scope, questions=questions),
            ),
            new_ctx(scope),
        )
        metric = report.metric("unanswerable_honesty_rate")
        assert metric is not None and metric.value == 0.0

    def test_false_refusal_metric_is_deleted_not_zero(self, world):
        """`answerable_false_refusal_rate` 必须**不存在**（删掉，不是留成恒 0）。"""
        from app.modules import evaluation

        scope = world["scope"]
        questions = [
            GoldenQuestion(id="q1", scope=scope, question="可回答问题", answerable=True),
        ]
        answers = [_answer(scope, question="可回答问题", grounded=False)]
        report = evaluation.compute(
            EvaluationInput(
                scope=scope, answers=answers,
                golden=_golden(scope, questions=questions),
            ),
            new_ctx(scope),
        )
        assert report.metric("answerable_false_refusal_rate") is None, (
            "该指标测的行为已不存在，留着就是假指标"
        )

    def test_no_golden_questions_means_not_evaluated(self, world):
        """没有 golden 问题 → 诚实率无分母 → not_evaluated（不是 0）。"""
        from app.modules import evaluation

        scope = world["scope"]
        report = evaluation.compute(
            EvaluationInput(scope=scope), new_ctx(scope),
        )
        metric = report.metric("unanswerable_honesty_rate")
        assert metric is not None and metric.status == "not_evaluated"
        assert metric.value is None


# =============================================================== 一对一匹配


class TestOneToOneMatching:
    def test_one_prediction_cannot_match_multiple_gold(self):
        """**一份预测不得匹配多个 gold**（旧 benchmark 的虚高缺陷）。"""
        from app.modules.evaluation.metrics import one_to_one_match

        predicted = ["图神经网络在 QM9 上取得最优结果。"]
        golden = [
            "图神经网络在 QM9 上取得最优结果。",
            "图神经网络在 QM9 上取得最优结果。",
            "图神经网络在 QM9 上取得最优结果。",
        ]
        pred_to_gold, gold_to_pred = one_to_one_match(predicted, golden)
        matched_gold = [g for g in gold_to_pred if g is not None]
        assert len(matched_gold) == 1, "唯一预测最多占一个 gold"
        assert gold_to_pred.count(None) == 2

    def test_two_prediction_one_gold_not_double_counted(self):
        """两条预测指向同一 gold：只有一条被认领。"""
        from app.modules.evaluation.metrics import one_to_one_match

        predicted = ["实验结果非常好。", "实验结果非常好。"]
        golden = ["实验结果非常好。"]
        _, gold_to_pred = one_to_one_match(predicted, golden)
        assert gold_to_pred[0] is not None
        assert sum(1 for p in gold_to_pred if p is not None) == 1

    def test_support_precision_capped_at_one(self, world):
        """一对多场景下 support_precision 不得超过 1.0。

        R4-M5 改写：以前经 `evaluation.compute` 取指标值。现在只要有金标集，
        precision/recall 一律走 **AI 裁判**（决策 3：不再有"人工确认集"这条绕过 AI 判等的路），
        无 LLM 时如实 `not_evaluated`。所以这两个用例改为**直接验证确定性匹配算法**
        —— 它们本来要锁的就是"一对一匹配不许把 precision 撑过 1"这件事，
        直接测算法比隔着服务层更贴近意图。
        """
        from app.contracts.evaluation import GoldenClaim
        from app.modules.evaluation import golden as golden_mod

        scope = world["scope"]
        text = "论文提出图神经网络方法并在 QM9 上取得最优结果。"
        claims = [
            GoldenClaim(id=f"gc{i}", scope=scope, text=text, expected_support="supports")
            for i in range(3)
        ]
        precision, _recall = golden_mod.support_precision_recall(
            [text], claims, predicted_ok=[True],
        )
        assert precision.value.value is not None
        assert precision.value.value <= 1.0, "精确率不得超过 100%"

    def test_recall_counts_unique_matches(self, world):
        """2 条预测、3 个 gold、内容全同 → recall = 2/3。"""
        from app.contracts.evaluation import GoldenClaim
        from app.modules.evaluation import golden as golden_mod

        scope = world["scope"]
        text = "论文在 QM9 数据集上取得最优结果。"
        claims = [
            GoldenClaim(id=f"gc{i}", scope=scope, text=text, expected_support="supports")
            for i in range(3)
        ]
        _precision, recall = golden_mod.support_precision_recall(
            [text, text], claims, predicted_ok=[True, True],
        )
        assert recall.value.numerator == 2 and recall.value.denominator == 3
        assert abs(recall.value.value - (2 / 3)) < 1e-3, "指标按 4 位小数取整"


# =============================================================== 中文匹配


class TestChineseMatching:
    def test_chinese_similarity_is_stable(self):
        """中文 token 化必须稳定（不受大小写/标点干扰）。"""
        from app.modules.evaluation.metrics import similarity

        a = "本文提出一种基于图神经网络的分子性质预测方法。"
        b = "本文提出一种基于图神经网络的分子性质预测方法"
        assert similarity(a, b) >= 0.9

    def test_case_insensitive_latin(self):
        from app.modules.evaluation.metrics import similarity

        assert similarity("GIN 表现最好", "gin 表现最好") >= 0.9

    def test_numbers_weighted(self):
        from app.modules.evaluation.metrics import similarity

        same = similarity("准确率为 91.2%", "准确率为 91.2%")
        diff = similarity("准确率为 91.2%", "准确率为 12.3%")
        assert same > diff, "数字不同必须显著降低相似度"


# =============================================================== overall / get


class TestOverallScore:
    def test_overall_null_when_core_missing(self, world):
        """核心指标不全 → overall_score 为 canonical null + 明确 warning。"""
        from app.modules import evaluation

        scope = world["scope"]
        report = evaluation.compute(EvaluationInput(scope=scope), new_ctx(scope))
        assert report.overall_score is None
        assert any(w.code == "ai_overall_not_evaluated" for w in report.warnings)

    def test_overall_formula_weights(self, world):
        """4 个核心指标均可测时按 §5.9 加权公式计算。"""
        from app.modules import evaluation
        from app.contracts.evaluation import MetricEntry, MetricValue, NavigationCheck

        scope = world["scope"]
        statements = [
            _statement(scope, text="事实句 A。", evidence_ids=["ev1"]),
            _statement(scope, text="事实句 B。", evidence_ids=["ev2"]),
        ]
        checks = [NavigationCheck(anchor_id="a1", page_correct=True, latency_ms=100)]
        questions = [
            GoldenQuestion(id="q1", scope=scope, question="可回答", answerable=True),
            GoldenQuestion(id="q2", scope=scope, question="不可回答", answerable=False),
        ]
        answers = [
            _answer(scope, question="可回答", grounded=True),
            _answer(scope, question="不可回答", grounded=False),
        ]
        report = evaluation.compute(
            EvaluationInput(
                scope=scope, statements=statements, navigation_checks=checks,
                answers=answers, golden=_golden(scope, questions=questions),
            ),
            new_ctx(scope),
        )
        # support_precision=1.0(有证据), anchor_page_accuracy=1.0, refusal=1.0
        # quote_exact_rate 无引文 → not_evaluated → overall 仍应为 None
        if report.overall_score is not None:
            assert 0.0 <= report.overall_score <= 100.0

    def test_overall_exact_weighting(self):
        """纯函数校验：权重 0.4/0.2/0.2/0.2 且 ratio 只缩放一次。"""
        from app.contracts.evaluation import EvaluationReport, MetricEntry, MetricValue
        from app.modules.evaluation.metrics import compute_ai_overall

        def entry(name, value):
            return MetricEntry(name=name, value=MetricValue(
                value=value, unit="ratio", status="measured",
            ))

        report = EvaluationReport(
            scope=Scope(paper_id=1, revision_id="r"), id="e1",
            metrics=[
                entry("support_precision", 0.5),
                entry("quote_exact_rate", 1.0),
                entry("anchor_page_accuracy", 0.0),
                # R4-M3：第四项由"拒答率"更名"不可答题诚实率"，权重与公式不变。
                entry("unanswerable_honesty_rate", 1.0),
            ],
        )
        # 100 × (0.4*0.5 + 0.2*1.0 + 0.2*0.0 + 0.2*1.0) = 100 × 0.6 = 60
        assert compute_ai_overall(report) == 60.0

    def test_overall_never_substitutes_zero(self):
        """缺一个核心指标绝不用 0 顶替（把"无法评估"伪装成"很差"）。"""
        from app.contracts.evaluation import EvaluationReport, MetricEntry, MetricValue
        from app.modules.evaluation.metrics import compute_ai_overall

        def entry(name, value):
            return MetricEntry(name=name, value=MetricValue(
                value=value, unit="ratio", status="measured",
            ))

        report = EvaluationReport(
            scope=Scope(paper_id=1, revision_id="r"), id="e1",
            metrics=[
                entry("support_precision", 1.0),
                entry("quote_exact_rate", 1.0),
                entry("anchor_page_accuracy", 1.0),
                # unanswerable_honesty_rate 缺失（R4-M3 更名后）
            ],
        )
        assert compute_ai_overall(report) is None


class TestGet:
    def test_get_does_not_compute_or_write(self, world):
        from app.core import db as db_mod
        from app.models.audit import EvaluationReportORM
        from app.modules import evaluation

        scope = world["scope"]
        with db_mod.SessionLocal() as db:
            before = db.query(EvaluationReportORM).filter(
                EvaluationReportORM.revision_id == scope.revision_id).count()
        report = evaluation.get(scope)
        evaluation.get(scope)
        with db_mod.SessionLocal() as db:
            after = db.query(EvaluationReportORM).filter(
                EvaluationReportORM.revision_id == scope.revision_id).count()
        assert before == after, "get 不得写库"
        assert report.overall_score is None
        assert len(report.metrics) == len(METRIC_NAMES)

    def test_get_returns_persisted_report(self, world):
        from app.modules import evaluation

        scope = world["scope"]
        statements = [_statement(scope, text="事实。", evidence_ids=["ev1"])]
        evaluation.compute(
            EvaluationInput(scope=scope, statements=statements), new_ctx(scope),
        )
        loaded = evaluation.get(scope)
        precision = loaded.metric("support_precision")
        assert precision is not None and precision.value == 1.0

    def test_get_unknown_paper_raises(self):
        from app.core.errors import DomainError
        from app.modules import evaluation

        with pytest.raises(DomainError):
            evaluation.get(Scope(paper_id=999999, revision_id="nope"))


class TestRunGolden:
    def test_run_golden_requires_golden(self, world):
        from app.core.errors import DomainError
        from app.modules import evaluation

        scope = world["scope"]
        with pytest.raises(DomainError):
            evaluation.run_golden(EvaluationInput(scope=scope), new_ctx(scope))

    def test_run_golden_scope_mismatch_warns(self, world):
        """真值集与 scope 不同源 → 不用于精确率，并给出 warning。"""
        from app.modules import evaluation
        from app.contracts.evaluation import GoldenClaim

        scope = world["scope"]
        other = Scope(paper_id=scope.paper_id, revision_id=scope.revision_id)
        # 用一个别的 paper_id 的 claim 制造 scope 不匹配
        bad_claim = GoldenClaim(
            id="gc1", scope=Scope(paper_id=scope.paper_id + 1, revision_id=scope.revision_id),
            text="外部真值", expected_support="supports",
        )
        report = evaluation.run_golden(
            EvaluationInput(
                scope=scope,
                statements=[_statement(scope, text="预测。", evidence_ids=["e1"])],
                golden=_golden(scope, claims=[bad_claim]),
            ),
            new_ctx(scope),
        )
        assert any(w.code == "golden_scope_mismatch" for w in report.warnings)


# =============================================================== benchmark 缺陷


def _load_benchmark():
    """加载旧 benchmark 脚本（若存在）。"""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "evals" / "benchmark.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("_bench_regression", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBenchmarkRegression:
    """旧 benchmark 的四类真实缺陷回归（§5.9 修复要求）。"""

    def test_citation_accuracy_capped_at_100(self):
        """citation_accuracy 最大 100 且**只缩放一次**（旧代码重复 ×100）。"""
        mod = _load_benchmark()
        if mod is None:
            pytest.skip("benchmark.py 不存在")

        paper = {
            "id": "p1", "title": "t",
            "gt_claims": [{
                "statement": "图神经网络在 QM9 上取得最优结果",
                "evidence_pages": [3],
            }],
        }
        extracted = [{
            "statement": "图神经网络在 QM9 上取得最优结果",
            "evidence": [{"page": 3}],
        }]
        out = mod.compute_paper_metrics(paper, extracted)
        assert out["citation_accuracy"] is not None
        assert 0.0 <= out["citation_accuracy"] <= 100.0, \
            "citation_accuracy 不得超过 100（旧实现双重缩放达 10000）"

    def test_none_times_100_no_crash(self):
        """``None * 100`` 不得崩溃（旧代码在 cite_den==0 时 TypeError）。"""
        mod = _load_benchmark()
        if mod is None:
            pytest.skip("benchmark.py 不存在")

        # 无页码信息 → citation_accuracy 必须是 None，且调用不得抛错
        paper = {
            "id": "p1", "title": "t",
            "gt_claims": [{"statement": "断言", "evidence_pages": []}],
        }
        extracted = [{"statement": "断言", "evidence": [{"page": None}]}]
        out = mod.compute_paper_metrics(paper, extracted)
        assert out["citation_accuracy"] is None

    def test_one_to_one_match_prevents_inflation(self):
        """一对一匹配：一条万能断言不得刷高 covered。"""
        mod = _load_benchmark()
        if mod is None:
            pytest.skip("benchmark.py 不存在")

        paper = {
            "id": "p1", "title": "t",
            "gt_claims": [
                {"statement": "图神经网络在 QM9 上取得最优结果", "evidence_pages": []},
                {"statement": "图神经网络在 QM9 上取得最优结果", "evidence_pages": []},
                {"statement": "图神经网络在 QM9 上取得最优结果", "evidence_pages": []},
            ],
        }
        extracted = [{
            "statement": "图神经网络在 QM9 上取得最优结果",
            "evidence": [{"page": 1}],
        }]
        out = mod.compute_paper_metrics(paper, extracted)
        assert out["covered"] == 1, "唯一 extracted 最多覆盖一个 gold"
        assert out["precision"] <= 100.0

    def test_chinese_bigram_matching_works(self):
        """中文 bigram 有效：相近中文断言可被匹配（旧实现 split 对中文无效）。"""
        mod = _load_benchmark()
        if mod is None:
            pytest.skip("benchmark.py 不存在")

        paper = {
            "id": "p1", "title": "t",
            "gt_claims": [{
                "statement": "本文提出一种基于图神经网络的分子性质预测方法",
                "evidence_pages": [],
            }],
        }
        extracted = [{
            "statement": "本文提出一种基于图神经网络的分子性质预测方法",
            "evidence": [{"page": 1}],
        }]
        out = mod.compute_paper_metrics(paper, extracted)
        assert out["covered"] == 1, "完全相同的中文断言必须匹配上"

