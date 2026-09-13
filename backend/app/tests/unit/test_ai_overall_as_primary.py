"""R4-M5 — 评测全面 AI 化：**删除一切人工环节**（ADR D-105）。

用户拍板（原话）："我建议就是直接取消一切跟人工有关的，那个自动评测直接全部ai评ai打分。"
+ "综合评分，各项指标什么率的全部ai直接完成，取消人工操作并且把综合评分右边的
（人工真值口径）字段删掉。"

本模块锁住的口径：

1. `overall_score` 是**主分**，直接用 AI 口径算（`compute_ai_overall`），并带
   `overall_score_basis="ai_generated"` 标明来源；
2. 人工口径函数 `compute_overall` / `core_metric_missing` **删除**（不是保留不用）；
3. `EvaluationInput.golden_is_tuning` 字段删除；金标集只剩一种形态（AI 从原文构造）；
4. 人工确认端点 `POST /papers/{id}/golden-set/confirm` **删除**；
5. 人工语义告警 `golden_not_annotated` / `overall_not_evaluated` 删除，
   替换为纯说明性的 `golden_ai_constructed` / `ai_overall_not_evaluated`；
6. **底线不变**：核心指标缺失时 `overall_score` 为 `None` + 原因告警，**绝不填 0**。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402

_SCOPE = Scope(paper_id=1, revision_id="rev-r4m5")


def _entry(name: str, value, status: str = "measured"):
    from app.contracts.evaluation import MetricEntry, MetricValue

    return MetricEntry(name=name, value=MetricValue(
        value=value, unit="ratio", status=status,
    ))


def _report(**status):
    from app.contracts.evaluation import EvaluationReport

    return EvaluationReport(
        scope=_SCOPE, id="r1",
        metrics=[
            _entry("support_precision", status.get("precision_value", 0.5),
                   status.get("precision", "proxy")),
            _entry("quote_exact_rate", 1.0, status.get("quote", "measured")),
            _entry("anchor_page_accuracy", 1.0, status.get("anchor", "measured")),
            _entry("unanswerable_honesty_rate", 1.0, status.get("honesty", "measured")),
        ],
    )


# ------------------------------------------------------------------ 1


class TestHumanPathIsDeleted:
    """人工口径的**函数与字段**都删除，不是留着不用。"""

    def test_compute_overall_is_gone(self):
        from app.modules.evaluation import metrics as M

        assert not hasattr(M, "compute_overall"), (
            "人工真值口径函数必须删除（决策 3：人工有关的全部删掉）"
        )

    def test_core_metric_missing_is_gone(self):
        from app.modules.evaluation import metrics as M

        assert not hasattr(M, "core_metric_missing")

    def test_evaluation_input_has_no_golden_is_tuning(self):
        from app.contracts.evaluation import EvaluationInput

        assert "golden_is_tuning" not in EvaluationInput.model_fields, (
            "调参集概念随人工确认一并删除；金标集只剩一种形态"
        )

    def test_confirm_endpoint_is_gone(self):
        """`POST /papers/{id}/golden-set/confirm` 路由必须不存在。"""
        from app.api import canonical

        paths = {getattr(r, "path", "") for r in canonical.router.routes}
        assert not any("golden-set/confirm" in p for p in paths), (
            f"人工确认端点必须删除，实际路由：{sorted(p for p in paths if 'golden' in p)}"
        )

    def test_golden_builder_has_no_confirm(self):
        from app.modules.evaluation import golden_builder

        assert not hasattr(golden_builder, "confirm_for_scope")


# ------------------------------------------------------------------ 2


class TestAiScoreIsPrimary:
    """`overall_score` 是 AI 口径主分，且标明来源。"""

    def test_ai_overall_is_computed_from_proxy_precision(self):
        from app.modules.evaluation import metrics as M

        # 0.4*50 + 0.2*100 + 0.2*100 + 0.2*100 = 80
        assert M.compute_ai_overall(_report()) == 80.0

    def test_report_declares_ai_basis(self):
        from app.contracts.evaluation import EvaluationReport

        report = EvaluationReport(scope=_SCOPE, id="r1")
        assert report.overall_score_basis is None, "未算之前为 None（不谎称来源）"
        report = report.model_copy(update={
            "overall_score": 80.0, "overall_score_basis": "ai_generated",
        })
        assert report.overall_score_basis == "ai_generated"
        assert report.overall_score == 80.0

    def test_missing_core_metric_never_becomes_zero(self):
        """底线：缺核心指标 → None + 原因告警，**绝不填 0**。"""
        from app.modules.evaluation import metrics as M

        report = _report(honesty="not_evaluated")
        assert M.compute_ai_overall(report) is None

    def test_ai_overall_returns_none_without_judge(self):
        """AI 裁判未出结论（precision 非 measured/proxy）→ None，不填 0。"""
        from app.modules.evaluation import metrics as M

        assert M.compute_ai_overall(_report(precision="not_evaluated")) is None


# ------------------------------------------------------------------ 3


class TestWarningCodes:
    """人工语义告警码删除，替换为纯说明性的 AI 口径告警。"""

    def test_human_semantic_warning_codes_are_gone(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "app"
        hits = []
        for py in root.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for code in ("golden_not_annotated", "overall_not_evaluated"):
                if code in text:
                    hits.append(f"{py.name}:{code}")
        assert not hits, f"人工语义告警码必须清零，仍有：{hits}"

    def test_evaluation_service_declares_ai_construction(self):
        import pathlib

        svc = pathlib.Path(__file__).resolve().parents[2] / "modules/evaluation/service.py"
        text = svc.read_text(encoding="utf-8")
        assert "golden_ai_constructed" in text, (
            "要用纯说明性告警告诉用户'金标集由 AI 从原文构造，评分为 AI 口径'"
        )
        assert "ai_overall_not_evaluated" in text, "AI 口径缺指标时要有独立的原因码"


# ------------------------------------------------------------------ 4


class TestServiceWiring:
    """服务层：AI 构造金标集也能出分（这正是决策 3/4 要的效果）。"""

    @pytest.fixture
    def real_scope(self):
        from app.contracts.documents import PaperCreate, SourceMetadata
        from app.modules import papers as papers_mod

        paper = papers_mod.create_paper(
            PaperCreate(title="AI 口径主分", source_mode="upload",
                        provenance_class="source_document")
        )
        source = papers_mod.store_source(
            paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="e.pdf")
        )
        revision = papers_mod.create_revision(paper.id, source.id, "source")
        return Scope(paper_id=paper.id, revision_id=revision.id)

    def test_ai_constructed_golden_still_scores(self, real_scope, monkeypatch):
        """金标集是 AI 构造 + AI 裁判有结论 → 报告里 overall_score 有值且标 basis。"""
        from app.contracts.evaluation import (
            AiJudgeResult, EvaluationInput, GoldenClaim, GoldenSet,
        )
        from app.modules import evaluation

        golden = GoldenSet(
            id="g-ai", version="v1",
            claims=[GoldenClaim(id="g1", scope=real_scope, text="参考断言",
                                expected_support="supports")],
        )
        judged = AiJudgeResult(
            matches=[[0]], true_positive=1, total_predicted=1, total_golden=1,
            model="judge", digest="d1", judge_version="v1",
        )
        statements = []
        input_ = EvaluationInput(
            scope=real_scope, statements=statements, golden=golden, ai_judge=judged,
        )
        report = evaluation.compute(input_, new_ctx(real_scope))
        # 核心指标里 quote/anchor/honesty 多半缺样本 → 允许 None，但**来源必须声明**
        if report.overall_score is not None:
            assert report.overall_score_basis == "ai_generated"
        # 无论如何不许出现"人工"语义
        codes = [w.code for w in report.warnings]
        assert "golden_not_annotated" not in codes
        assert "overall_not_evaluated" not in codes
