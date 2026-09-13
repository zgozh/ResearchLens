"""M4 问答策略放开 + M5 绝不空答不变量（REFACTOR_PLAN_R3）。

用户原话："是不是应该直接完全放开，不要限制了更好。"
现状问题（实测 2026-09-12，paper 7）：
- `这篇论文哪里最值得质疑？` → `mode=abstained`、**answer 空串**（前端只能说"无证据支持"）；
- `论文用了什么数据？` → 同上；
- `主要贡献是什么？` → 修过（`_is_paper_related` 加宽）后已能答。

本文件锁住的口径：
1. **闲聊/问候不触发检索**（规则前置；mock 检索调用计数必须为 0）；
2. **论文问题 + 检索为空**时不再空白拒答：能抽出问题对象 → `not_mentioned`（点名对象）；
   抽不出对象 → `general`（标注"未使用论文原文"）；
3. **绝不空答**做成代码级不变量：落库前若正文与句子皆空，替换为兜底模板并记告警日志。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402


@pytest.fixture
def real_scope():
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="问答放开测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="p.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return Scope(paper_id=paper.id, revision_id=revision.id)


def _hit(text: str):
    return SimpleNamespace(
        chunk_id="c1", block_ids=["b1"], anchor_ids=[], media_ids=[],
        text=text, vector_score=0.5, lexical_score=None, rrf_score=0.03,
        rerank_score=None, rank=1,
    )


def _enable_llm(monkeypatch, answer: str = "这是通用回答正文。"):
    from app.contracts.ai import CompletionResult
    from app.core.config import settings
    from app.modules import ai as ai_module
    from app.modules.qa import service as qs

    monkeypatch.setattr(
        type(settings), "has_llm", property(lambda self: True), raising=False,
    )
    monkeypatch.setattr(
        ai_module, "complete",
        lambda request, ctx=None: CompletionResult(value=answer, model="fake", mode="text"),
    )
    # `_general_answer` 还要求 revision 已登记模型快照，否则直接返回 None（→ 拒答）
    monkeypatch.setattr(qs, "_snapshot_id", lambda ctx: "snap-1")


class TestChitchatSkipsRetrieval:
    """规则前置：问候/闲聊不该去检索论文（省一次云调用，也避免无关命中）。"""

    @pytest.mark.parametrize(
        "question",
        ["你好，介绍一下你自己", "谢谢！", "你是谁？", "今天天气怎么样？"],
    )
    def test_chitchat_does_not_call_retrieval(self, real_scope, monkeypatch, question):
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        calls = {"n": 0}

        def _retrieve(*a, **k):
            calls["n"] += 1
            return [], []

        monkeypatch.setattr(qs, "_retrieve", _retrieve)
        _enable_llm(monkeypatch)

        rec = qs.answer(real_scope, QARequest(question=question), new_ctx(real_scope))
        assert calls["n"] == 0, f"闲聊不该触发检索：{question}"
        assert rec.mode == "general", rec.mode
        assert rec.text.text.strip(), "闲聊也必须有正文"


class TestEmptyRetrievalOpensUp:
    """检索为空时不再空白拒答 —— 这就是"放开"。"""

    def test_paper_question_with_object_is_not_mentioned(self, real_scope, monkeypatch):
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        rec = qs.answer(
            real_scope, QARequest(question="这篇论文提到量子计算了吗？"), new_ctx(real_scope)
        )
        assert rec.mode == "not_mentioned", rec.mode
        assert "量子计算" in rec.text.text, rec.text.text
        assert rec.grounded is False and not rec.evidence

    def test_paper_question_without_object_falls_back_to_general(self, real_scope, monkeypatch):
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        _enable_llm(monkeypatch, "通用解释正文。")
        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        rec = qs.answer(
            real_scope, QARequest(question="这篇论文讲的核心思想是什么？"), new_ctx(real_scope)
        )
        assert rec.mode in ("general", "not_mentioned"), rec.mode
        assert rec.text.text.strip(), "不得空答"

    def test_general_answer_is_labelled(self, real_scope, monkeypatch):
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        _enable_llm(monkeypatch, "通用回答。")
        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        rec = qs.answer(real_scope, QARequest(question="什么是量子纠缠？"), new_ctx(real_scope))
        assert rec.mode == "general", rec.mode
        assert "未使用论文" in (rec.note or ""), rec.note
        assert not rec.evidence and rec.grounded is False


class TestNeverEmptyInvariant:
    """M5：不变量而不是"各分支自觉"。"""

    def test_invariant_fills_text_when_everything_is_empty(self, real_scope, monkeypatch):
        from app.contracts.evidence import ArtifactText
        from app.contracts.qa import AnswerRecord, QARequest
        from app.modules.qa import service as qs

        rec = qs.answer(real_scope, QARequest(question="这篇论文提到量子计算了吗？"),
                        new_ctx(real_scope))
        empty = AnswerRecord(
            scope=rec.scope, id="x", question=rec.question,
            text=ArtifactText(text="", spans=[]), statements=[], evidence=[],
            grounded=False, confidence="Low", note="", mode="unavailable",
        )
        filled = qs._ensure_readable(empty, "这篇论文提到量子计算了吗？", [])
        assert filled.text.text.strip(), "不变量必须补出正文"
        # R4-M3：兜底也不再产 `abstained`（已从 AnswerMode 删除）。
        assert filled.mode in ("not_mentioned", "extractive", "general", "unavailable"), \
            filled.mode

    def test_invariant_is_not_triggered_when_text_exists(self, real_scope):
        from app.contracts.evidence import ArtifactText
        from app.contracts.qa import AnswerRecord
        from app.modules.qa import service as qs

        rec = AnswerRecord(
            scope=real_scope, id="x", question="q",
            text=ArtifactText(text="有正文。", spans=[]), statements=[], evidence=[],
            grounded=False, confidence="Low", note="", mode="generated",
        )
        assert qs._ensure_readable(rec, "q", []).text.text == "有正文。"

    def test_fallback_text_never_says_no_content(self, real_scope):
        from app.contracts.evidence import ArtifactText
        from app.contracts.qa import AnswerRecord
        from app.modules.qa import service as qs

        rec = AnswerRecord(
            scope=real_scope, id="x", question="这篇论文提到量子计算了吗？",
            text=ArtifactText(text="", spans=[]), statements=[], evidence=[],
            grounded=False, confidence="Low", note="", mode="unavailable",
        )
        out = qs._ensure_readable(rec, "这篇论文提到量子计算了吗？", []).text.text
        assert "没有生成内容" not in out
        assert out.strip()
