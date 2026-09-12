"""问答「永不空答」+ 论文相关判据加宽（REFACTOR_PLAN M7）。

**实测证据**（2026-09-12，paper 7 = Attention Is All You Need，revision e0c91aa2）：

| 问题 | 实测结果 |
|---|---|
| 这篇论文哪里最值得质疑？ | `mode=abstained`、`answer` 为**空串**、SSE 只有 meta/status/final（0 条 sentence） |
| 主要贡献是什么？ | `mode=general` —— 被当成与论文无关的闲聊，用"通用助手"口吻回答 |
| 论文用了什么数据？ | `mode=abstained`、空文本 |
| 你好，介绍一下你自己 | `mode=general`（这条是对的） |

根因（两条，都有现场证据）：

1. ``_is_paper_related`` 只认两类信号："论文/本文…"这类指向词，或检索语义分 ≥ 0.6。
   实测同一篇论文上，**所有**问题的 `vector_score` 都落在 0.41–0.60（包括明确指向论文
   的问题），0.6 这条线实际不可达 —— 于是"主要贡献是什么"被判成与论文无关。
2. ``_abstained`` 产出 ``ArtifactText(text="")``，前端只渲染 statements/answer 文本，
   于是拒答在界面上就是"什么都没有"（用户原话："没有生成内容"）。

本文件锁住的口径：

- 论文相关 = 指向词 ∪ **学术话题词**（贡献/数据集/局限/实验…）∪ rerank 高分命中；
- 闲聊与领域常识仍走通用回答（不受限问答这条不能丢）；
- **任何**拒答路径都必须给出**非空、可读、不冒充证据**的正文；
- 问的若是具体对象（"论文提到 Kubernetes 了吗"）→ `mode="not_mentioned"` 且正文点名该对象。
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
        PaperCreate(title="问答完整性测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="q.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return Scope(paper_id=paper.id, revision_id=revision.id)


def _hit(text: str, *, vector: float | None = None, rerank: float | None = None):
    return SimpleNamespace(
        chunk_id="c1", block_ids=["b1"], anchor_ids=[], media_ids=[],
        text=text, vector_score=vector, lexical_score=None, rrf_score=0.03,
        rerank_score=rerank, rank=1,
    )


class TestPaperRelevanceIsWidened:
    """「主要贡献是什么？」这类**明显在问论文**的问题不能被判成闲聊。"""

    @pytest.mark.parametrize(
        "question",
        [
            "主要贡献是什么？",
            "创新点在哪？",
            "论文用了什么数据集？",
            "这个方法有什么局限？",
            "实验结果怎么样？",
            "作者是怎么评估的？",
            "训练用了多少算力？",
        ],
    )
    def test_academic_topic_without_paper_word_is_paper_related(self, question):
        from app.modules.qa import service as qs

        hits = [_hit("some chunk text", vector=0.48)]  # 实测的真实量级
        assert qs._is_paper_related(question, hits) is True, question

    def test_high_rerank_hit_marks_paper_related(self):
        """rerank 是实测中**唯一**能拉开差距的信号（问论文内问题 0.55–1.0）。"""
        from app.modules.qa import service as qs

        assert qs._is_paper_related(
            "How many attention heads?", [_hit("...", vector=0.45, rerank=0.78)]
        ) is True

    def test_weak_rerank_alone_is_not_enough(self):
        from app.modules.qa import service as qs

        assert qs._is_paper_related(
            "推荐几部科幻电影", [_hit("...", vector=0.45, rerank=0.2)]
        ) is False

    @pytest.mark.parametrize(
        "question",
        ["你好，介绍一下你自己", "今天天气怎么样？", "什么是量子纠缠？",
         "帮我写一首诗", "Python 的列表和元组有什么区别？"],
    )
    def test_chat_and_offtopic_stay_general(self, question):
        """不受限问答这条不能丢：与论文无关的问题仍走通用回答。"""
        from app.modules.qa import service as qs

        assert qs._is_paper_related(question, [_hit("论文片段", vector=0.5)]) is False, question


class TestAbstainIsNeverEmpty:
    """拒答也必须有内容：空白 = 用户眼里的"问答坏了"。"""

    def test_no_hits_abstain_has_readable_text(self, real_scope, monkeypatch):
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([], []))
        rec = qs.answer(
            real_scope, QARequest(question="本文的核心创新点是什么？"), new_ctx(real_scope)
        )
        assert rec.mode == "abstained", rec.mode
        assert rec.text.text.strip(), "拒答正文不得为空"
        assert len(rec.text.text.strip()) >= 15, f"拒答正文太短：{rec.text.text!r}"
        assert not rec.statements and not rec.evidence, "拒答不得伪造证据"
        assert rec.grounded is False
        assert (rec.note or "").strip(), "拒答必须给出可读的 note 说明"

    def test_absent_object_is_not_mentioned_and_names_the_object(self, real_scope, monkeypatch):
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(
            qs, "_retrieve",
            lambda *a, **k: ([_hit("The model was trained on 8 NVIDIA P100 GPUs.")], []),
        )
        rec = qs.answer(
            real_scope,
            QARequest(question="论文提到 Kubernetes 了吗？"),
            new_ctx(real_scope),
        )
        assert rec.mode == "not_mentioned", f"应明确回答『论文没提到』，实际 {rec.mode}"
        assert "Kubernetes" in rec.text.text, f"正文应点名对象：{rec.text.text!r}"
        assert rec.grounded is False and not rec.evidence

    def test_blank_draft_abstain_has_text(self, real_scope, monkeypatch):
        """模型给了 claims 但一句都没过 gate、且抽取兜底也空 → 仍必须有正文。"""
        from app.contracts.ai import Usage
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(
            type(qs.settings), "has_llm", property(lambda self: True), raising=False,
        )
        monkeypatch.setattr(qs, "_snapshot_id", lambda ctx: "snap-1")
        monkeypatch.setattr(
            qs, "_retrieve",
            lambda *a, **k: ([_hit("Table 2 summarizes our results.", vector=0.5)], []),
        )
        monkeypatch.setattr(qs, "_llm_draft", lambda *a, **k: ("", [], Usage()))
        rec = qs.answer(
            real_scope, QARequest(question="本文的核心创新点是什么？"), new_ctx(real_scope)
        )
        assert rec.text.text.strip(), "拒答正文不得为空"
        assert rec.mode in ("abstained", "not_mentioned"), rec.mode
        assert not rec.statements

    def test_abstain_does_not_invent_quotes(self, real_scope, monkeypatch):
        """拒答正文里若引用原文，必须**逐字来自检索片段**（纪律 3）。"""
        from app.contracts.ai import Usage
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        snippet = "The Transformer uses multi-head attention."
        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: ([_hit(snippet, vector=0.5)], []))
        monkeypatch.setattr(
            type(qs.settings), "has_llm", property(lambda self: True), raising=False,
        )
        monkeypatch.setattr(qs, "_snapshot_id", lambda ctx: "snap-1")
        monkeypatch.setattr(qs, "_llm_draft", lambda *a, **k: ("", [], Usage()))
        rec = qs.answer(
            real_scope, QARequest(question="本文的核心创新点是什么？"), new_ctx(real_scope)
        )
        text = rec.text.text
        # 若正文里出现引号片段，它必须是原文子串
        for marker in ('"', "「", "『"):
            assert marker not in text or snippet[:20] in text.replace("\n", " ")
        assert rec.evidence == []


class TestModesStayHonest:
    def test_paper_question_with_evidence_still_generated_or_extractive(self, real_scope, monkeypatch):
        from app.contracts.ai import Usage
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        monkeypatch.setattr(
            type(qs.settings), "has_llm", property(lambda self: True), raising=False,
        )
        monkeypatch.setattr(qs, "_snapshot_id", lambda ctx: "snap-1")
        monkeypatch.setattr(
            qs, "_retrieve",
            lambda *a, **k: ([_hit("Table 2 summarizes our results.", vector=0.55, rerank=0.8)], []),
        )
        monkeypatch.setattr(
            qs, "_llm_draft",
            lambda *a, **k: ("结论句。", [{"text": "结论句。", "block_ids": ["b1"],
                                          "quote": "Table 2 summarizes our results."}], Usage()),
        )
        monkeypatch.setattr(qs, "_gate_claims", lambda *a, **k: [_stmt(real_scope)])
        monkeypatch.setattr(
            qs.gate, "assess",
            lambda *a, **k: SimpleNamespace(grounded=True, reason="", confidence="Medium"),
        )
        rec = qs.answer(
            real_scope, QARequest(question="主要贡献是什么？"), new_ctx(real_scope)
        )
        assert rec.mode == "generated", rec.mode
        assert rec.text.text.strip()


def _stmt(scope):
    from app.contracts.evidence import VerifiedStatement

    return VerifiedStatement(scope=scope, id="s1", claim_id="c1", text="结论句。",
                             evidence_ids=["e1"], display_class="verified_fact")
