"""R4-M3 — **拒答退出产品语义**：所有问题都有回答 + 置信度（ADR D-104）。

用户拍板（原话）："拒答直接彻底消失，反正有置信度说明。" + "可以附"（最接近的原文片段）。

本模块锁住的口径：

1. `mode="abstained"` **不再出现在任何 API 响应里**（从 `AnswerMode` 删除）；
2. 四条原本以"无证据"为由拒答的路径，各自给出**有信息的回答**：
   - 模型不可用 → `unavailable`（如实说明 + 已知信息，不硬编）；
   - 检索为空但能点名对象 → `not_mentioned`；抽不出对象 → `general`；
   - **对象确实不在原文** → `not_mentioned`（判据保留为确定性证据）**并附最接近的原文片段**；
   - 模型草稿全被 gate 拒 → **抽取式兜底** `extractive`（逐字原文）；连片段都没有 → `general`/`unavailable`。
3. `grounded` 语义**不变**（仍=逐句过 Evidence Gate）——不许因为"不再拒答"而放宽，
   否则 `unsupported_fact_escape_rate` 失守；
4. 置信度三档有**确定判据**，不再"非 grounded 一律 Low"；
5. 低置信回答附的原文片段必须**逐字来自检索到的原文**（纪律：不许编造）。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402

#: 一段足够长、会被 `_closest_snippet` 采用的原文（逐字断言用）。
SNIPPET = (
    "We employ a residual connection around each of the two sub-layers, "
    "followed by layer normalization."
)


@pytest.fixture
def real_scope():
    """服务层测试要真实 revision（``answer`` 会校验 scope 属于该 paper）。"""
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="拒答退出测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="g.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return Scope(paper_id=paper.id, revision_id=revision.id)


def _hit(text: str, *, vector: float | None = None):
    return SimpleNamespace(
        chunk_id="c1", block_ids=["b1"], anchor_ids=[], media_ids=[],
        text=text, vector_score=vector, lexical_score=None, rrf_score=0.03,
        rerank_score=None, rank=1, page=3,
    )


# --------------------------------------------------------------------- 1


class TestAbstainedModeIsGone:
    """`abstained` 从契约里删除，且四条原拒答路径都不再产出它。"""

    def test_answer_mode_literal_has_no_abstained(self):
        from typing import get_args

        from app.contracts.qa import AnswerMode

        assert "abstained" not in get_args(AnswerMode), (
            "abstained 必须从 AnswerMode 删除（决策 1：前端永远见不到）"
        )
        for expected in ("generated", "extractive", "general", "not_mentioned",
                         "cached", "unavailable"):
            assert expected in get_args(AnswerMode), f"新 mode 表缺 {expected}"

    def test_model_unavailable_gives_unavailable_mode(self, real_scope, monkeypatch):
        """无模型 + 闲聊 → `unavailable`（如实说明），不是 `abstained`。"""
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        rec = qs.answer(real_scope, QARequest(question="你好"), new_ctx(real_scope))
        assert rec.mode == "unavailable", f"实际 {rec.mode}"
        assert rec.text.text.strip(), "任何回答都必须有可读正文"
        assert rec.confidence == "Low"
        assert rec.grounded is False

    def test_empty_retrieval_with_object_is_not_mentioned(self, real_scope, monkeypatch):
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        rec = qs.answer(
            real_scope, QARequest(question="论文用了 Kubernetes 吗？"), new_ctx(real_scope)
        )
        assert rec.mode == "not_mentioned", f"实际 {rec.mode}"
        assert "Kubernetes" in rec.text.text, "必须点名问题里的对象"

    def test_gate_rejects_all_drafts_falls_back_to_extractive(
        self, real_scope, monkeypatch
    ):
        """模型草稿全被 gate 拒 → 抽取式兜底（逐字原文），不是拒答。"""
        from app.contracts.ai import Usage
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(
            type(qs.settings), "has_llm", property(lambda self: True), raising=False,
        )
        monkeypatch.setattr(qs, "_snapshot_id", lambda ctx: "snap-1")
        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([_hit(SNIPPET, vector=0.8)], []))
        # 模型给了草稿但一句都没过 gate
        monkeypatch.setattr(qs, "_llm_draft", lambda *a, **k: ("", [], Usage()))
        monkeypatch.setattr(qs, "_gate_claims", lambda *a, **k: [])
        monkeypatch.setattr(
            qs.gate, "assess",
            lambda *a, **k: SimpleNamespace(
                grounded=False, reason="没有任何通过 gate 的句子",
                confidence="Low", fact_count=0, supported_facts=0,
                inference_count=0, unverified_count=0,
            ),
        )

        from app.contracts.evidence import VerifiedStatement

        stmt = VerifiedStatement(
            scope=real_scope, id="s1", claim_id="c1", text=SNIPPET,
            evidence_ids=["e1"], display_class="verified_fact",
        )
        monkeypatch.setattr(qs, "_extractive_draft", lambda *a, **k: (SNIPPET, [stmt]))

        # 注意问句：**不能**含"像具体对象"的中文内容词——那会先命中阶段 2.6 的
        # "对象不在原文"确定性判据（本测试要覆盖的是阶段 3 的抽取式兜底）。
        rec = qs.answer(
            real_scope, QARequest(question="这篇论文用了什么方法？"), new_ctx(real_scope)
        )
        assert rec.mode != "abstained"
        assert rec.mode == "extractive", f"实际 {rec.mode}"
        assert rec.text.text.strip(), "抽取式兜底必须有正文"
        assert rec.grounded is False, "未经完整 gate 不得声称 grounded"


# --------------------------------------------------------------------- 2


class TestSnippetIsVerbatim:
    """决策 2：允许附"最接近的原文片段"，但它必须**逐字**来自原文。"""

    def test_object_absent_attaches_verbatim_snippet(self, real_scope, monkeypatch):
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        # 检索有命中，但问题问的对象（Kubernetes）在命中里不出现
        hits = [_hit(SNIPPET, vector=0.7)]
        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: (hits, []))

        rec = qs.answer(
            real_scope, QARequest(question="论文用了 Kubernetes 吗？"), new_ctx(real_scope)
        )
        assert rec.mode == "not_mentioned", f"实际 {rec.mode}"
        body = rec.text.text
        assert "Kubernetes" in body, "要点名没提到的对象"
        # 片段逐字来自原文：片段主体必须是 SNIPPET 的子串（允许截断加省略号）
        core = SNIPPET[:40]
        assert core in body, f"附的片段必须逐字来自原文，实际正文：{body!r}"
        assert "未通过证据校验" in body or "仅供参考" in body, (
            "片段必须显式标注未通过证据校验（不许与 evidence 混淆）"
        )
        assert rec.grounded is False
        assert rec.evidence == [], "片段不是 evidence，不得进引用列表"


# --------------------------------------------------------------------- 3


class TestConfidenceBands:
    """置信度三档判据确定化（不再是"非 grounded 一律 Low"）。"""

    def _decision(self, **kw):
        from app.modules.qa.answer_gate import GateDecision

        base = dict(grounded=False, reason="", confidence="Low")
        base.update(kw)
        return GateDecision(**base)

    def test_high_requires_grounded_two_facts_no_inference(self):
        from app.modules.qa.answer_gate import _confidence

        d = self._decision(grounded=True, fact_count=2, supported_facts=2, inference_count=0)
        assert _confidence(d, mode="generated") == "High"

    def test_grounded_single_fact_is_medium(self):
        from app.modules.qa.answer_gate import _confidence

        d = self._decision(grounded=True, fact_count=1, supported_facts=1, inference_count=0)
        assert _confidence(d, mode="generated") == "Medium"

    def test_extractive_all_supported_is_medium(self):
        """抽取式且句句有据 → Medium（用户要的是"给置信度"而不是"拒答"）。"""
        from app.modules.qa.answer_gate import _confidence

        d = self._decision(grounded=False, fact_count=2, supported_facts=2)
        assert _confidence(d, mode="extractive") == "Medium"

    def test_general_and_unavailable_are_low(self):
        from app.modules.qa.answer_gate import _confidence

        d = self._decision(grounded=False, fact_count=0, supported_facts=0)
        assert _confidence(d, mode="general") == "Low"
        assert _confidence(d, mode="unavailable") == "Low"

    def test_grounded_semantics_not_relaxed(self):
        """红线：`assess` 仍要求事实句都有证据——不许为"不再拒答"放宽。"""
        from app.modules.qa.answer_gate import assess

        from app.contracts.evidence import VerifiedStatement

        scope = Scope(paper_id=1, revision_id="r")
        no_evidence = VerifiedStatement(
            scope=scope, id="s1", claim_id="c1", text="事实句",
            evidence_ids=[], display_class="verified_fact",
        )
        d = assess("事实句", [no_evidence], mode="extractive")
        assert d.grounded is False, "事实句没有证据时绝不许 grounded"


# --------------------------------------------------------------------- 5


class TestLegacyModeMapping:
    """历史行里 `mode='abstained'` 在**读取投影处**映射（R4 规划 Q1）。

    为什么不迁移 DB：答案缓存键含 question+snapshot+source_digest，历史行的内容是当时的
    真实产出，改历史等于改事实。这里只在读取处映射，新问新写不再产生旧值。
    """

    def test_abstained_with_absent_object_maps_to_not_mentioned(self):
        """防御性映射：旧行若带"对象缺席"note，则落 `not_mentioned`。"""
        from app.modules.qa.service import NOT_MENTIONED_NOTE, _legacy_mode

        assert _legacy_mode("abstained", NOT_MENTIONED_NOTE) == "not_mentioned"

    def test_abstained_with_no_evidence_maps_to_unavailable(self):
        """**真实历史形态**：旧代码里 `mode="abstained"` 只由"没找到证据"产出
        （对象缺席那条路产的是 `not_mentioned`，不是 `abstained`）→ 映射到
        `unavailable`（"当时给不出完整回答"），而不是 `not_mentioned`（那会谎称点过名）。"""
        from app.modules.qa.service import ABSTAIN_NOTE, _legacy_mode

        assert _legacy_mode("abstained", ABSTAIN_NOTE) == "unavailable"

    def test_new_modes_pass_through(self):
        from app.modules.qa.service import _legacy_mode

        for mode in ("generated", "extractive", "general", "not_mentioned", "unavailable"):
            assert _legacy_mode(mode, "") == mode

    def test_empty_mode_is_mapped_not_leaked(self):
        from app.modules.qa.service import _legacy_mode

        assert _legacy_mode(None, "") == "unavailable"
        assert _legacy_mode("", "论文中没有提到 X") == "not_mentioned"

    def test_row_to_answer_never_returns_abstained(self):
        """端到端：把一行旧数据喂给 `_row_to_answer`，出来的 mode 必须是新取值。"""
        from types import SimpleNamespace

        from app.modules.qa.service import _row_to_answer

        row = SimpleNamespace(
            paper_id=1, revision_id="r", id="a1", question="q",
            text={"text": "旧拒答正文", "spans": []}, statements=[], evidence=[],
            grounded=False, confidence="Low",
            note="论文中没有足够的已验证证据支持回答；已按 Evidence Gate 拒绝进入事实层。",
            mode="abstained", model_snapshot_id=None, usage={}, warnings=[],
        )
        rec = _row_to_answer(row)
        assert rec is not None
        assert rec.mode != "abstained"
        assert rec.mode in ("not_mentioned", "unavailable", "general", "extractive")

    """`answerable_false_refusal_rate` 删除；`unanswerable_refusal_rate` → `unanswerable_honesty_rate`。"""

    def test_metric_names_no_longer_has_false_refusal(self):
        from app.contracts.evaluation import METRIC_NAMES

        assert "answerable_false_refusal_rate" not in METRIC_NAMES, (
            "该指标测的行为已不存在（决策 1），必须删除而不是留成恒 0 的死指标"
        )
        assert "unanswerable_refusal_rate" not in METRIC_NAMES, "已更名"
        assert "unanswerable_honesty_rate" in METRIC_NAMES

    def test_unanswerable_question_answered_honestly_scores_one(self):
        """不可答题得到 `not_mentioned`（如实说明没有证据）→ honesty 记 1。"""
        from app.contracts.evaluation import GoldenQuestion
        from app.modules.evaluation import metrics as M

        q = "论文用了 Kubernetes 吗？"
        answer = SimpleNamespace(
            question=q, mode="not_mentioned", statements=[],
            text=SimpleNamespace(text="论文中没有提到 Kubernetes。"),
            grounded=False, warnings=[], usage=SimpleNamespace(elapsed_ms=1),
        )
        entry = M.honesty_metrics(
            [answer], [GoldenQuestion(id="g1", scope=Scope(paper_id=1, revision_id="r"),
                                      question=q, answerable=False)]
        )
        assert entry.name == "unanswerable_honesty_rate"
        assert entry.value.value == 1.0, entry.value

    def test_unanswerable_question_fabricated_scores_zero(self):
        """不可答题却 grounded 生成作答（胡说）→ honesty 记 0。"""
        from app.contracts.evaluation import GoldenQuestion
        from app.modules.evaluation import metrics as M

        q = "论文用了 Kubernetes 吗？"
        answer = SimpleNamespace(
            question=q, mode="generated", statements=[],
            text=SimpleNamespace(text="论文使用 Kubernetes 部署了实验。"),
            grounded=True, warnings=[], usage=SimpleNamespace(elapsed_ms=1),
        )
        entry = M.honesty_metrics(
            [answer], [GoldenQuestion(id="g1", scope=Scope(paper_id=1, revision_id="r"),
                                      question=q, answerable=False)]
        )
        assert entry.value.value == 0.0, entry.value
