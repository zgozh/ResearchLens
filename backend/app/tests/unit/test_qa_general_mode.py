"""证据问答**不受限**：非论文问题走通用回答，不再"无证据即拒答"（ADR-0057）。

用户要求（原话）："证据问答功能应该不受限制问答，不应该无证据 → 拒绝编造，
应该只是聊到论文相关的东西才查到该论文相关的东西。"

现状问题：`_draft` 里 ``if not hits: return "", [], Usage(), ...`` → 任何**检索不到
论文内容**的问题（闲聊、领域常识、跨论文提问）都被判 `abstained`，界面显示拒答，
用户以为"问答坏了"。

本模块锁住的口径：

1. **判据是"问题是否指向这篇论文"**，不是"检索有没有命中"：问了论文（"论文/本文/
   这一节/图 3…"）或检索语义分数很高 → 走论文证据链，**没有证据就如实拒答**（不编造）；
2. 与论文无关的问题 → **通用回答**：`mode="general"`、`grounded=False`、
   note 明确写"未使用论文原文证据"，**不当成拒答**（评测的拒答率也按 mode 判，不含它）；
3. 没有可用模型时**不硬编答案**：如实拒答（通用回答也必须来自模型）。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402

SCOPE = Scope(paper_id=1, revision_id="rev-general")


@pytest.fixture
def real_scope():
    """服务层测试要真实 revision（``answer`` 会校验 scope 属于该 paper）。"""
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="通用问答测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="g.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return Scope(paper_id=paper.id, revision_id=revision.id)


def _hit(text: str, *, vector: float | None = None, lexical: float | None = None):
    return SimpleNamespace(
        chunk_id="c1", block_ids=["b1"], anchor_ids=[], media_ids=[],
        text=text, vector_score=vector, lexical_score=lexical, rrf_score=0.03,
        rerank_score=None, rank=1,
    )


class TestPaperRelatedClassifier:
    def test_chat_question_is_not_paper_related(self):
        from app.modules.qa import service as qs

        assert qs._is_paper_related("今天天气怎么样？", []) is False

    def test_explicit_paper_mention_is_paper_related(self):
        from app.modules.qa import service as qs

        for q in ("本文提出的方法是什么？", "这篇论文的实验设置如何？",
                  "论文中「2 相关背景」讲了什么？", "图 3 说明了什么？",
                  "the paper proposes what?"):
            assert qs._is_paper_related(q, []) is True, q

    def test_strong_semantic_hit_marks_paper_related(self):
        """没提"论文"，但检索语义高度相关（问的正是文中内容）→ 仍按论文问题处理。"""
        from app.modules.qa import service as qs

        assert qs._is_paper_related("Haar 小波如何用于载体选择？", [_hit("...", vector=0.72)]) is True

    def test_weak_hit_alone_is_not_enough(self):
        from app.modules.qa import service as qs

        assert qs._is_paper_related("推荐几部科幻电影", [_hit("...", vector=0.31)]) is False


class TestGeneralAnswer:
    def test_non_paper_question_is_answered_not_refused(self, real_scope, monkeypatch):
        """与论文无关的问题 → ``mode="general"``，有正文、note 说明未用论文证据。

        **用真实契约类型 ``CompletionResult``**：此前单测伪造了一个带 ``text=`` 的对象，
        而真实类型只有 ``value`` —— 于是"单测通过、线上仍然拒答"（ADR-0060）。
        """
        from app.contracts.ai import CompletionResult
        from app.contracts.qa import QARequest
        from app.modules import ai as ai_module
        from app.modules.qa import service as qs

        monkeypatch.setattr(
            type(qs.settings), "has_llm", property(lambda self: True), raising=False,
        )
        monkeypatch.setattr(
            ai_module, "complete",
            lambda request, ctx=None: CompletionResult(
                value="量子纠缠是指两个粒子状态不可分。", model="m", mode="text",
            ),
        )
        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        monkeypatch.setattr(qs, "_snapshot_id", lambda ctx: "snap-1")

        rec = qs.answer(real_scope, QARequest(question="什么是量子纠缠？"), new_ctx(real_scope))
        assert rec.mode == "general", f"应走通用回答，实际 {rec.mode}"
        assert rec.text.text.strip(), "通用回答必须有正文"
        assert rec.grounded is False, "通用回答不得标 grounded"
        assert "通用" in (rec.note or "") or "未使用论文" in (rec.note or ""), rec.note
        assert not rec.statements, "通用回答不带论文断言"

    def test_completion_text_reads_value_not_text(self):
        """回归锁：``CompletionResult`` 的纯文本正文在 ``value`` 里，不在 ``text``。"""
        from app.contracts.ai import CompletionResult
        from app.modules.qa import service as qs

        assert qs._completion_text(CompletionResult(value="正文", mode="text")) == "正文"
        # 空的/非法形状不得被当成正文
        assert qs._completion_text(CompletionResult(value=None, mode="text")) == ""
        assert qs._completion_text(CompletionResult(value={"a": 1}, mode="json_object")) == ""

    def test_paper_question_without_evidence_still_abstains(self, real_scope, monkeypatch):
        """**不编造**这条纪律不变：问了论文但检索不到证据 → 如实说明，绝不编内容。

        R4-M3 改写：以前断言 `mode == "abstained"`（拒答）。决策 1 删除了"拒答"这一档，
        改为断言落到新的如实说明形态 —— 但**内核断言全部保留**：
        grounded=False、无 statements、无 evidence（不许拿别的内容顶替）。
        """
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        rec = qs.answer(
            real_scope, QARequest(question="本文的核心创新点是什么？"), new_ctx(real_scope)
        )
        assert rec.mode != "abstained", "该取值已从产品语义删除（决策 1）"
        assert rec.mode in ("not_mentioned", "extractive", "general", "unavailable"), rec.mode
        assert rec.grounded is False, "无证据不得 grounded"
        assert not rec.statements and not rec.evidence, "不得编造证据"
        assert rec.text.text.strip(), "必须给出可读正文"

    def test_no_llm_means_unavailable_not_fabrication(self, real_scope, monkeypatch):
        """没有模型时不能硬编答案 → 如实说明 `unavailable`。"""
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        rec = qs.answer(
            real_scope, QARequest(question="你好"), new_ctx(real_scope))
        assert rec.mode == "unavailable", f"模型不可用应如实说明，实际 {rec.mode}"
        assert rec.grounded is False
        assert rec.text.text.strip()

    def test_general_answer_is_not_counted_in_honesty_denominator(self):
        """评测口径：可答题不进诚实率分母（`general` 也不是"误拒"）。"""
        from app.contracts.evaluation import GoldenQuestion
        from app.modules.evaluation import metrics as M

        q = "什么是量子纠缠？"
        answer = SimpleNamespace(question=q, mode="general", statements=[],
                                 text=SimpleNamespace(text="解释"), grounded=False,
                                 warnings=[], usage=SimpleNamespace(elapsed_ms=1))
        entry = M.honesty_metrics(
            [answer], [GoldenQuestion(id="g1", scope=SCOPE, question=q, answerable=True)]
        )
        assert entry.value.status == "not_evaluated", (
            "可答题不进分母 → 无样本即 not_evaluated（不是 0）"
        )


class TestEmptyDraftNoteIsClear:
    """模型只给 claims、``answer`` 留空时，note 必须解释清楚（ADR-0060）。

    实测现象：界面同时显示"有正文"和 note="答案文本为空"，会被读成自相矛盾。
    """

    def test_note_explains_sentence_assembled_answer(self, real_scope, monkeypatch):
        from app.contracts.ai import Usage
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(
            type(qs.settings), "has_llm", property(lambda self: True), raising=False,
        )
        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([_hit("片段", vector=0.8)], []))
        # 必须有 snapshot id，否则 `_draft` 直接走 llm_unavailable 抽取降级，到不了 _llm_draft
        monkeypatch.setattr(qs, "_snapshot_id", lambda ctx: "snap-1")
        # 草稿：answer 空、claims 非空；句子经 gate 通过（这里直接伪造 gate 与句子）
        monkeypatch.setattr(
            qs, "_llm_draft",
            lambda *a, **k: ("", [{"text": "事实句", "block_ids": ["b1"], "quote": "片段"}],
                             Usage()),
        )
        monkeypatch.setattr(qs, "_gate_claims", lambda *a, **k: [_stmt(real_scope)])
        monkeypatch.setattr(
            qs.gate, "assess",
            lambda *a, **k: SimpleNamespace(grounded=False, reason="答案文本为空",
                                            confidence="Low"),
        )
        rec = qs.answer(real_scope, QARequest(question="本文的方法是什么？"), new_ctx(real_scope))
        assert rec.text.text.strip(), "仍应给出由句子组成的正文"
        assert "通过证据校验的事实句" in (rec.note or ""), rec.note


def _stmt(scope):
    from app.contracts.evidence import VerifiedStatement

    return VerifiedStatement(scope=scope, id="s1", claim_id="c1", text="事实句",
                             evidence_ids=["e1"], display_class="verified_fact")

