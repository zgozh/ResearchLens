"""结构化输出被 token 上限截断时，**不能拿同样的预算重试**，也要能用模型的 chunk 引用（ADR-0063）。

三个真缺陷（都来自"问答一直在转/答不出来"的线上排查）：

1. **截断重试白烧时间**：实测一次 QA 草稿发了 5 次请求，其中 3 次是
   ``output_tokens == max_tokens == 1200`` 的**截断**（尾部全是空白、JSON 不完整），
   每次 **26.8s** → 单次草稿最坏 ~80s，用户看到的就是"一直在转"。
   模型自己只用了 10.5s（成功那次）。
2. **模型给的 chunk 引用被系统性拒收**：提示词让模型复制片段前缀 ``[chunk_id]``，
   而 ``_gate_claims`` 只接受 ``allowed_blocks``（块 id）→ 模型给的对引用**必然**被丢，
   只能靠确定性恢复兜底；恢复失败就整句丢弃（实测 4/4 句被丢）。
3. **短事实问题检索不到关键段落**：问"论文用了什么数据集"，检索回来的 5 段里
   **一句数据集都没提到**（答案句在 5.1 实验章，没被召回）。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""


# ===================================================== 1. 截断必须放大预算


class TestTruncationEscalatesBudget:
    def _spy(self, monkeypatch, *, truncate_times: int):
        """前 N 次返回"被截断的坏 JSON"，之后返回好 JSON；记录每次的 max_tokens。"""
        from app.modules.ai import service as ai_service

        seen: list = []
        state = {"n": 0}

        def fake_chat_once(provider, body):  # noqa: ANN001
            seen.append(body.get("max_tokens"))
            state["n"] += 1
            if state["n"] <= truncate_times:
                budget = int(body.get("max_tokens") or 0)
                # 真实现象：正好用满上限、文本被截断（尾部空白、JSON 不完整）
                return ai_service.transport.TransportResult(
                    text='{"answer": "cut', model="m",
                    usage={"input_tokens": 100, "output_tokens": budget,
                           "elapsed_ms": 26000},
                    mode="json_schema", attempts=1,
                )
            return ai_service.transport.TransportResult(
                text='{"answer": "ok"}', model="m",
                usage={"input_tokens": 100, "output_tokens": 20, "elapsed_ms": 500},
                mode="json_schema", attempts=1,
            )

        monkeypatch.setattr(ai_service.transport, "chat_once", fake_chat_once)
        monkeypatch.setattr(
            ai_service, "_providers",
            lambda: [ai_service.transport.Provider("k", "https://example.invalid/v1", "m")],
        )
        monkeypatch.setattr(
            type(ai_service.settings), "has_llm", property(lambda self: True), raising=False,
        )
        return seen

    def _request(self):
        from pydantic import BaseModel

        from app.contracts.ai import ChatMessage, CompletionRequest

        class _Out(BaseModel):
            answer: str = ""

        return CompletionRequest(
            messages=[ChatMessage(role="user", content="hi")],
            output_schema=_Out,
            max_output_tokens=1200,
        )

    def test_retry_uses_larger_budget_after_truncation(self, monkeypatch):
        """截断后重试必须**放大** max_tokens（此前三次都是 1200，纯烧时间）。"""
        from app.contracts.common import Scope, new_ctx
        from app.modules.ai import service as ai_service

        seen = self._spy(monkeypatch, truncate_times=1)
        ai_service.complete(self._request(), new_ctx(Scope(paper_id=1, revision_id="r")))
        assert len(seen) >= 2, f"应重试一次：{seen}"
        assert seen[1] > seen[0], f"重试预算必须放大，实际 {seen}"

    def test_budget_is_capped(self, monkeypatch):
        """放大要有上限，不能无限膨胀。"""
        from app.contracts.common import Scope, new_ctx
        from app.modules.ai import service as ai_service

        seen = self._spy(monkeypatch, truncate_times=99)
        with pytest.raises(Exception):
            ai_service.complete(self._request(), new_ctx(Scope(paper_id=1, revision_id="r")))
        assert seen, "至少发过一次"
        assert max(seen) <= ai_service.MAX_OUTPUT_TOKENS_CAP, f"预算未封顶：{seen}"


# ===================================================== 2. 接受模型的 chunk 引用


class TestChunkCitationAccepted:
    def _hits(self):
        return [SimpleNamespace(
            chunk_id="chunk-1", block_ids=["blk-a", "blk-b"], anchor_ids=[],
            media_ids=[], text="片段正文", vector_score=0.5, lexical_score=1.0,
            rrf_score=0.03, rerank_score=None, rank=1,
        )]

    def test_model_chunk_id_maps_to_its_blocks(self):
        """模型按提示词复制的是 ``[chunk_id]``，gate 必须把它映射成该片段的块。"""
        from app.modules.qa import service as qs

        hits = self._hits()
        blocks = qs._claim_block_ids({"block_ids": ["chunk-1"]}, hits)
        assert blocks == ["blk-a", "blk-b"], f"chunk 引用未映射成块：{blocks}"

    def test_raw_block_id_still_accepted(self):
        from app.modules.qa import service as qs

        assert qs._claim_block_ids({"block_ids": ["blk-a"]}, self._hits()) == ["blk-a"]

    def test_unknown_id_is_dropped(self):
        from app.modules.qa import service as qs

        assert qs._claim_block_ids({"block_ids": ["nope"]}, self._hits()) == []

    def test_gate_no_longer_drops_valid_chunk_citations(self, monkeypatch):
        """端到端一层：给了合法 chunk 引用时**不得**再报 claim_without_citation。"""
        from app.contracts.common import Scope, new_ctx
        from app.modules.qa import service as qs

        captured = {}

        def fake_register(scope, draft, warnings, ctx=None):  # noqa: ANN001
            captured["draft"] = draft
            return SimpleNamespace(id="s1", text=draft.text)

        monkeypatch.setattr(qs, "_register_statement", fake_register)
        warnings: list = []
        out = qs._gate_claims(
            Scope(paper_id=1, revision_id="r"),
            [{"text": "事实句", "block_ids": ["chunk-1"], "quote": "片段正文"}],
            self._hits(), warnings,
        )
        assert out, "合法引用不该被丢"
        assert not [w for w in warnings if w.code == "claim_without_citation"]
        assert captured["draft"].citations[0].block_id == "blk-a"


# ===================================================== 3. 关键词补充检索


class TestKeywordRetrievalPass:
    def test_query_terms_extracts_content_words(self):
        from app.modules.qa import service as qs

        terms = qs._query_terms("论文用了什么数据集？")
        assert "数据集" in terms, f"应抽出内容词：{terms}"
        assert not any(t in ("论文", "什么", "用了") for t in terms), f"停用词不该留：{terms}"

    def test_second_pass_uses_terms(self, monkeypatch):
        """有内容词时应当**再检索一次**（短事实问题的答案句常不在第一次的召回里）。"""
        from app.contracts.common import Scope, new_ctx
        from app.modules.qa import service as qs

        queries: list = []

        def fake_retrieve(request, ctx=None):  # noqa: ANN001
            queries.append(request.query)
            return SimpleNamespace(hits=[SimpleNamespace(
                chunk_id=f"c{len(queries)}", block_ids=[f"b{len(queries)}"], anchor_ids=[],
                media_ids=[], text="正文", vector_score=0.5, lexical_score=1.0,
                rrf_score=0.03, rerank_score=None, rank=1,
            )], warnings=[])

        monkeypatch.setattr("app.modules.retrieval.retrieve", fake_retrieve)
        hits, _ = qs._retrieve(Scope(paper_id=1, revision_id="r"), "论文用了什么数据集？",
                               5, new_ctx(Scope(paper_id=1, revision_id="r")))
        assert len(queries) >= 2, f"应做第二次关键词检索：{queries}"
        assert any("数据集" in q for q in queries[1:]), f"第二次查询应含内容词：{queries}"
        assert len({h.chunk_id for h in hits}) == len(hits), "合并后不得有重复 chunk"


# ===================================================== 4. 批量语义判定


class TestBatchVerdictPreset:
    def test_batch_verdict_is_preset_on_ctx(self, monkeypatch):
        """批量判定结果要写进 ctx 预置位，evidence.validate 读到就不再调用模型。"""
        from app.contracts.common import Scope, new_ctx
        from app.modules.evidence import semantic as semantic_mod
        from app.modules.qa import service as qs

        monkeypatch.setattr(
            semantic_mod, "batch_judge",
            lambda items, ctx: {items[0][0]: ("supports", 0.9)},
        )
        seen = {}

        def fake_register(scope, draft, warnings, ctx=None):  # noqa: ANN001
            seen["verdict"] = getattr(ctx, "_semantic_verdict", None)
            return SimpleNamespace(id="s1", text=draft.text)

        monkeypatch.setattr(qs, "_register_statement", fake_register)
        hits = [SimpleNamespace(chunk_id="c1", block_ids=["b1"], anchor_ids=[],
                                media_ids=[], text="正文", vector_score=0.5,
                                lexical_score=1.0, rrf_score=0.03, rerank_score=None, rank=1)]
        ctx = new_ctx(Scope(paper_id=1, revision_id="r"))
        qs._gate_claims(
            Scope(paper_id=1, revision_id="r"),
            [{"text": "事实句", "block_ids": ["c1"], "quote": "正文"}],
            hits, [], ctx,
        )
        assert seen["verdict"] == "supports", "批量判定未写入 ctx 预置位（钩子形同虚设）"

    def test_batch_failure_falls_back_to_per_statement(self, monkeypatch):
        """批量不可用时不得影响结果：仍传原 ctx（逐句判定）。"""
        from app.contracts.common import Scope, new_ctx
        from app.modules.evidence import semantic as semantic_mod
        from app.modules.qa import service as qs

        def boom(items, ctx):  # noqa: ANN001
            raise RuntimeError("batch down")

        monkeypatch.setattr(semantic_mod, "batch_judge", boom)
        captured = {}

        def fake_register(scope, draft, warnings, ctx=None):  # noqa: ANN001
            captured["ctx"] = ctx
            return SimpleNamespace(id="s1", text=draft.text)

        monkeypatch.setattr(qs, "_register_statement", fake_register)
        hits = [SimpleNamespace(chunk_id="c1", block_ids=["b1"], anchor_ids=[],
                                media_ids=[], text="正文", vector_score=0.5,
                                lexical_score=1.0, rrf_score=0.03, rerank_score=None, rank=1)]
        ctx = new_ctx(Scope(paper_id=1, revision_id="r"))
        out = qs._gate_claims(
            Scope(paper_id=1, revision_id="r"),
            [{"text": "事实句", "block_ids": ["c1"], "quote": "正文"}],
            hits, [], ctx,
        )
        assert out, "批量失败仍应逐句走 gate"
        assert captured["ctx"] is ctx and getattr(ctx, "_semantic_verdict", None) is None


# ===================================================== 5. 截止时间必须设置


class TestDeadlinesAreSet:
    def test_legacy_ctx_has_bounded_deadline(self):
        """旧入口的 deadline 必须有界且别太长（此前 300s，用户等到超时）。"""
        import inspect

        from app.modules.qa import legacy as qa_legacy

        src = inspect.getsource(qa_legacy._legacy_ctx)
        assert "deadline_ms" in src, "旧入口必须设置截止时间"
        assert "300_000" not in src, "300s 太长：实测会超过前端等待"

    def test_stream_route_sets_deadline_and_budget(self):
        import inspect

        from app.api import canonical

        src = inspect.getsource(canonical.qa_stream)
        assert "QA_STREAM_DEADLINE_MS" in src and "Budget(" in src, \
            "流式问答必须带截止时间与预算，否则供应商卡住就会一直转"
        assert canonical.QA_STREAM_DEADLINE_MS <= 180_000


# ===================================================== 6. 提示词必须要求核对"问题对象"

class TestPromptChecksQuestionObject:
    """放宽"必须照抄相关句"之后，必须同时要求**核对问题里的对象是否出现在片段里**。

    实测回归（ADR-0066）：放宽后 paper 7（英文 arXiv 论文）的四个"不可答"问题
    （Kubernetes / 联邦学习 / 量子计算 / 区块链）**全被答了**（5–6 句），
    `unanswerable_refusal_rate` 会因此掉到 0 —— 那是拿"实验用了几块 GPU"顶"用没用 Kubernetes"。
    """

    def test_prompt_forbids_answering_absent_objects(self):
        import inspect

        from app.modules.qa import service as qs

        src = inspect.getsource(qs._llm_draft)
        assert "根本没有出现该对象" in src, "提示词必须显式要求核对问题对象是否出现在片段里"
        assert "答非所问" in src, "要说清为什么不能拿别的内容顶上"


# ===================================================== 7. 问题对象不在原文 → 必须拒答

@pytest.fixture
def real_scope():
    from app.contracts.common import Scope, new_ctx

    """服务层测试要真实 revision（answer 会校验 scope 属于该 paper）。"""
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="对象缺失拒答测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="o.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return Scope(paper_id=paper.id, revision_id=revision.id)


class TestAbsentObjectRefusal:
    """问"用了 Kubernetes 吗"而原文里没有 Kubernetes → **拒答**，不拿别的相关内容顶替。

    实测回归（ADR-0066）：paper 7 的四个不可答问题全被答了（5–6 句），
    回答给的是"用了 8 块 P100 GPU"——答非所问，`unanswerable_refusal_rate` 会掉到 0。
    """

    def _hits(self, text: str):
        return [SimpleNamespace(chunk_id="c1", block_ids=["b1"], anchor_ids=[],
                                media_ids=[], text=text, vector_score=0.5,
                                lexical_score=1.0, rrf_score=0.03, rerank_score=None, rank=1)]

    def test_absent_latin_object_is_detected(self):
        from app.modules.qa import service as qs

        hits = self._hits("实验使用 8 块 NVIDIA P100 GPU 训练,批大小 1024.")
        assert qs._object_absent_from_hits("本文是如何使用 Kubernetes 完成实验与部署的？", hits)
        assert qs._object_absent_from_hits("本文是如何使用 联邦学习 完成实验与部署的？", hits)

    def test_present_object_is_not_refused(self):
        from app.modules.qa import service as qs

        hits = self._hits("本文使用 Kubernetes 完成实验与部署.")
        assert not qs._object_absent_from_hits("本文是如何使用 Kubernetes 完成实验与部署的？", hits)

    def test_user_questions_are_not_falsely_refused(self):
        """用户点名要答的三类问题**不能**被这条判据误伤。"""
        from app.modules.qa import service as qs

        hits = self._hits("本文选用公开图像库 BOSS v0.92 与 BOSS v1.01;"
                          "所选用的指标模型较为简单,仍有提升空间;"
                          "本文提出了一种基于 Haar 小波域指标自适应选择载体的隐写方法.")
        assert not qs._object_absent_from_hits("论文用了什么数据集？", hits)
        assert not qs._object_absent_from_hits("这篇论文哪里最值得质疑？", hits)
        assert not qs._object_absent_from_hits("这篇论文的主要贡献是什么？", hits)

    def test_answer_refuses_when_object_absent(self, real_scope, monkeypatch):
        """端到端：对象不在原文时**不许**走模型草稿或抽取兜底。"""
        from app.contracts.common import new_ctx
        from app.contracts.qa import QARequest
        from app.modules.qa import service as qs

        hits = self._hits("实验使用 8 块 NVIDIA P100 GPU 训练.")
        monkeypatch.setattr(qs, "_retrieve", lambda *a, **k: (hits, []))

        def boom(*a, **k):  # noqa: ANN001
            raise AssertionError("对象不在原文时不该调用生成模型")

        monkeypatch.setattr(qs, "_llm_draft", boom)
        rec = qs.answer(real_scope, QARequest(question="本文是如何使用 Kubernetes 完成实验与部署的？"),
                        new_ctx(real_scope))
        # REFACTOR_PLAN M7：拒答也要说人话 —— 从"空白 abstained"改成
        # mode=not_mentioned 且正文点名"论文中没有提到 Kubernetes"。
        assert rec.mode == "not_mentioned", f"必须拒答，实际 {rec.mode}"
        assert "Kubernetes" in rec.text.text
        assert any(getattr(w, "code", "") == "question_object_absent" for w in rec.warnings)



