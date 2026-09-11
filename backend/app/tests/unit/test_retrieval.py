"""M07 retrieval 单元测试（REFACTOR_SPEC §6.9「单元测试」要点）。

覆盖：中文无空格、连字符技术词、空结果、重复 chunk 去重、
不同论文相同语句、**向量维度变化不污染旧索引**、embedding 超时降级 lexical_only。

全部使用临时 sqlite，绝不触碰 data/researchlens.db。
"""
from __future__ import annotations

import os

import pytest

# 数据库/密钥隔离由 conftest.py 统一负责；这里确保绝不发起真实云调用。
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402
from app.contracts.retrieval import RetrievalRequest  # noqa: E402


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


def _make_paper(paragraphs, *, origin="source_extraction", label="p"):
    """建论文 + revision + 页 + 块，返回 ``(scope, block_ids)``。"""
    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM
    from app.models.source import new_id
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title=f"检索测试 {label}", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf(label), SourceMetadata(original_filename=f"{label}.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    with db_mod.SessionLocal() as db:
        page = PageORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, page_label="1", label_status="verified",
                       width_pt=612.0, height_pt=792.0, text="\n".join(paragraphs))
        db.add(page)
        db.flush()
        rows = []
        for idx, text in enumerate(paragraphs):
            rows.append(BlockORM(
                id=new_id(), paper_id=paper.id, revision_id=revision.id,
                page_id=page.id, ordinal=idx,
                kind="caption" if text.startswith(("图", "表")) else "paragraph",
                text=text, origin=origin, anchor_id=None,
                section_path=["Method"] if idx % 2 == 0 else ["Results"],
            ))
        db.add_all(rows)
        db.commit()
        ids = [r.id for r in rows]

    return scope, ids


@pytest.fixture
def world():
    """中文无空格 + 拉丁连字符技术词 + 单位混排的原文。"""
    from app.modules import retrieval

    scope, ids = _make_paper([
        "本文提出一种基于图神经网络的分子性质预测方法，在QM9数据集上取得最优结果。",
        "训练使用 AdamW 优化器，学习率设为 3e-4，批大小为 mA g-1 级别。",
        "图 1 展示了模型在 ESOL 与 FreeSolv 上的 generalization gap 对比。",
        "表 2 报告了不同 backbone 的 ablation 结果，其中 GIN 表现最好。",
    ], label="retr")
    retrieval.index(scope, new_ctx(scope))
    return {"scope": scope, "blocks": ids}


# =============================================================== 中文 / 术语


class TestChineseAndTerms:
    def test_chinese_without_spaces(self, world):
        """中文无空格查询必须命中（靠字符 bigram）。"""
        from app.modules import retrieval

        result = retrieval.retrieve(
            RetrievalRequest(scope=world["scope"], query="图神经网络", top_k=5),
            new_ctx(world["scope"]),
        )
        assert result.hits, "中文查询应有命中"
        assert any("图神经网络" in h.text for h in result.hits)

    def test_hyphenated_technical_term(self, world):
        """连字符技术词（mA g-1）应作为整体被索引并可命中。"""
        from app.modules import retrieval

        result = retrieval.retrieve(
            RetrievalRequest(scope=world["scope"], query="mA g-1", top_k=5),
            new_ctx(world["scope"]),
        )
        assert result.hits
        assert any("mA g-1" in h.text for h in result.hits)

    def test_latin_and_numeric_term(self, world):
        from app.modules import retrieval

        result = retrieval.retrieve(
            RetrievalRequest(scope=world["scope"], query="AdamW 3e-4", top_k=5),
            new_ctx(world["scope"]),
        )
        assert result.hits

    def test_caption_and_table_kept_in_context(self, world):
        """图题/表头上下文应保留，使「表头」「图题」类查询可命中。"""
        from app.modules import retrieval

        result = retrieval.retrieve(
            RetrievalRequest(scope=world["scope"], query="表题 表格", top_k=5),
            new_ctx(world["scope"]),
        )
        assert result.hits, "带上下文标注的 caption/table 块应可被结构词命中"


# =============================================================== 空结果 / 边界


class TestEmptyAndScope:
    def test_empty_result_is_not_exception(self, world):
        """无命中 → hits=[]，不是异常。"""
        from app.modules import retrieval

        result = retrieval.retrieve(
            RetrievalRequest(scope=world["scope"], query="完全不相关的量子色动力学", top_k=5),
            new_ctx(world["scope"]),
        )
        assert result.hits == []

    def test_empty_query_returns_empty_with_warning(self, world):
        from app.modules import retrieval

        result = retrieval.retrieve(
            RetrievalRequest(scope=world["scope"], query="   ", top_k=5),
            new_ctx(world["scope"]),
        )
        assert result.hits == []
        assert any(w.code == "empty_query" for w in result.warnings)

    def test_top_k_clamped_with_warning(self, world):
        """旧请求越界 top_k 先 clamp 并记 warning，不直接报错。

        ``RetrievalRequest`` 契约自带 ``le=20``，会先被 Pydantic 拦下；
        这里用 ``model_construct`` 跳过校验，专门验证 service 的适配逻辑。
        """
        from app.modules import retrieval

        raw = RetrievalRequest.model_construct(
            scope=world["scope"], query="方法", top_k=50,
            mode="lexical", max_context_tokens=6000, rerank=False,
        )
        result = retrieval.retrieve(raw, new_ctx(world["scope"]))
        assert len(result.hits) <= 20
        assert any(w.code == "top_k_clamped" for w in result.warnings)

    def test_scope_limits_search(self, world):
        """必须限定 Scope：另一 revision 的块不得被检索到。"""
        from app.modules import retrieval

        other_scope, _ = _make_paper(["另一篇论文的独特内容：量子纠缠实验。"], label="other")
        retrieval.index(other_scope, new_ctx(other_scope))

        result = retrieval.retrieve(
            RetrievalRequest(scope=other_scope, query="图神经网络 方法", top_k=5),
            new_ctx(other_scope),
        )
        assert all("图神经网络" not in h.text for h in result.hits)
        assert all("量子纠缠" in h.text for h in result.hits) or result.hits == []

    def test_unknown_revision_raises(self, world):
        from app.core.errors import DomainError
        from app.modules import retrieval

        bad = Scope(paper_id=world["scope"].paper_id, revision_id="missing-rev")
        with pytest.raises(DomainError):
            retrieval.retrieve(
                RetrievalRequest(scope=bad, query="方法"), new_ctx(bad)
            )


# =============================================================== 只索引原文


class TestSourceExtractionOnly:
    def test_generated_blocks_not_indexed(self):
        """AI 摘要（origin=generated）**绝不**作一级证据进入索引。"""
        from app.modules import retrieval

        scope, _ = _make_paper(
            ["这是模型生成的摘要内容，不应被检索到。"], origin="generated", label="gen"
        )
        result = retrieval.index(scope, new_ctx(scope))
        assert result.chunk_count == 0
        assert any(w.code == "no_source_blocks" for w in result.warnings)

        hits = retrieval.retrieve(
            RetrievalRequest(scope=scope, query="模型生成的摘要", top_k=5),
            new_ctx(scope),
        )
        assert hits.hits == []


# =============================================================== 去重


class TestDedup:
    def test_duplicate_chunk_deduped(self):
        """同 revision 内文本完全相同的两块 → 只产生一个 chunk（content_hash 唯一）。"""
        from app.modules import retrieval

        same = "本研究采用统一的实验设置以确保结果可比。"
        scope, _ = _make_paper([same, same], label="dup")
        result = retrieval.index(scope, new_ctx(scope))
        assert result.chunk_count == 1

    def test_same_text_across_papers_is_isolated(self):
        """不同论文出现相同语句 → 各自独立，互不污染。"""
        from app.modules import retrieval

        same = "实验结果表明该方法具有良好泛化能力。"
        scope_a, _ = _make_paper([same], label="sameA")
        scope_b, _ = _make_paper([same], label="sameB")
        retrieval.index(scope_a, new_ctx(scope_a))
        retrieval.index(scope_b, new_ctx(scope_b))

        hits_a = retrieval.retrieve(
            RetrievalRequest(scope=scope_a, query="泛化能力"), new_ctx(scope_a)
        )
        hits_b = retrieval.retrieve(
            RetrievalRequest(scope=scope_b, query="泛化能力"), new_ctx(scope_b)
        )
        assert hits_a.hits and hits_b.hits
        assert {h.chunk_id for h in hits_a.hits}.isdisjoint({h.chunk_id for h in hits_b.hits})

    def test_reindex_is_idempotent(self, world):
        """重复索引不产生重复块。"""
        from app.modules import retrieval

        first = retrieval.index(world["scope"], new_ctx(world["scope"]))
        second = retrieval.index(world["scope"], new_ctx(world["scope"]))
        assert first.chunk_count == second.chunk_count


# =============================================================== 降级


class TestDegradation:
    def test_no_embedding_degrades_to_lexical_only(self, world):
        """embedding 不可用 → status=lexical_only + warnings，**绝不中断**。"""
        from app.modules import retrieval

        result = retrieval.index(world["scope"], new_ctx(world["scope"]))
        assert result.status in ("lexical_only", "ready")
        if result.vector_count == 0:
            assert result.status == "lexical_only"
            assert any("embedding" in w.code for w in result.warnings)

    def test_hybrid_without_embedding_uses_lexical(self, world):
        """hybrid 模式下无 embedding → mode_used=lexical，仍返回结果。"""
        from app.modules import retrieval

        result = retrieval.retrieve(
            RetrievalRequest(scope=world["scope"], query="图神经网络",
                             mode="hybrid", top_k=5),
            new_ctx(world["scope"]),
        )
        assert result.mode_used == "lexical"
        assert result.hits

    def test_embedding_failure_does_not_break_index(self, monkeypatch):
        """embedding 抛异常 → index 仍成功（词法索引可用）+ warning。"""
        from app.contracts.ai import EmbeddingBatch
        from app.modules import ai as ai_svc
        from app.modules import retrieval

        def _boom(*args, **kwargs):
            raise TimeoutError("embedding timeout")

        monkeypatch.setattr(ai_svc, "embed", _boom)
        scope, _ = _make_paper(["应当仍可被词法检索到的中文内容。"], label="boom")
        result = retrieval.index(scope, new_ctx(scope))
        assert result.chunk_count >= 1
        assert result.status == "lexical_only"

        hits = retrieval.retrieve(
            RetrievalRequest(scope=scope, query="词法检索", mode="hybrid"),
            new_ctx(scope),
        )
        assert hits.mode_used == "lexical"
        assert hits.hits


# =============================================================== 向量空间隔离


class TestVectorSpaceIsolation:
    def test_dimension_change_does_not_pollute_old_index(self):
        """向量维度变化 → 旧空间保持只读，不被误用也不被删除。"""
        from app.core import db as db_mod
        from app.models.retrieval import ChunkVectorORM
        from app.modules import retrieval
        from app.modules.retrieval import repository as repo

        scope, _ = _make_paper(["向量空间隔离测试内容。"], label="vec")
        retrieval.index(scope, new_ctx(scope))

        with db_mod.SessionLocal() as db:
            chunks = repo.list_chunks(db, scope.revision_id)
            assert chunks, "应先产生 chunk"
            # 手工写入两个不同空间（模拟历史 768 维 + 新 1024 维）
            cid = chunks[0].id
            repo.upsert_vector(
                db, vector_id=f"v768-{cid}", chunk_id=cid,
                paper_id=scope.paper_id, revision_id=scope.revision_id,
                space="emb:768:l2v1", vector=[0.1] * 768,
            )
            repo.upsert_vector(
                db, vector_id=f"v1024-{cid}", chunk_id=cid,
                paper_id=scope.paper_id, revision_id=scope.revision_id,
                space="emb:1024:l2v1", vector=[0.2] * 1024,
            )
            db.commit()

        with db_mod.SessionLocal() as db:
            spaces = set(repo.spaces_in_use(db, scope.revision_id))
        assert {"emb:768:l2v1", "emb:1024:l2v1"} <= spaces, "旧空间不得被删除"

    def test_mismatched_dimension_skipped_in_search(self):
        """查询向量与索引维度不一致的行必须被跳过，不抛异常。"""
        from app.modules.retrieval import vector as vec

        class _Row:
            def __init__(self, cid, space, dim):
                self.chunk_id = cid
                self.space = space
                self.dimension = dim
                self.vector = [0.5] * dim

        rows = [_Row("c1", "m:3:l2v1", 3), _Row("c2", "m:3:l2v1", 5)]
        channel = vec.search([0.5, 0.5, 0.5], "m:3:l2v1", rows, limit=10)
        assert channel.available
        assert [cid for cid, _ in channel.hits] == ["c1"]

    def test_space_name_includes_model_dimension_normalization(self):
        from app.modules.retrieval.vector import space_name

        assert space_name("text-embedding-v3", 1024) == "text-embedding-v3:1024:l2v1"


# =============================================================== RRF 参数


class TestFusion:
    def test_rrf_constant_and_limits(self):
        from app.modules.retrieval import fusion

        assert fusion.RRF_K == 60
        assert fusion.PER_LIST_LIMIT == 30
        assert fusion.TOTAL_CANDIDATES == 60
        assert fusion.MAX_RERANK == 12

    def test_rrf_scores_are_stable_and_deduped(self):
        from app.modules.retrieval import fusion

        lists = [
            ("lexical", [("c1", 3.0), ("c2", 2.0)]),
            ("vector", [("c1", 0.9), ("c3", 0.8)]),
        ]
        out = fusion.rrf_fuse(lists)
        ids = [c.chunk_id for c in out]
        assert ids == list(dict.fromkeys(ids)), "同一 chunk 不得重复出现"
        # c1 两路都命中 → RRF 分最高
        assert ids[0] == "c1"
        assert out[0].lexical_score == 3.0
        assert out[0].vector_score == 0.9

    def test_truncate_by_tokens_keeps_at_least_one(self):
        from app.modules.retrieval import fusion

        cands = [fusion.FusedCandidate(chunk_id="c1"), fusion.FusedCandidate(chunk_id="c2")]
        out = fusion.truncate_by_tokens(cands, {"c1": 999999, "c2": 1}, budget=10)
        assert len(out) == 1
