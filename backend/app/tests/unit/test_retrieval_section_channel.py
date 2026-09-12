"""检索的**章节通道**（D-54）：问句点名了某章节时，必须召回该章节的块。

真实缺陷（live 3 篇实测）：`build_bank` 用**章节标题**造问题（"论文中「2 相关背景」
这一部分主要讲了什么？"），但 hybrid 检索的向量通道把别的章节排到了前面，章节自己的块
根本没进 top-5 → 模型判"证据不足"→ 返回空 claims → 按设计拒答。
实测 paper 3 的 4 道可答章节题有 2 道被这样拒答（`answerable_false_refusal_rate=0.5`）。
验证实验：只把该章节自己的 2 个块喂给 `_draft`，两道题都产出了**带证据的验证句**。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402
from app.contracts.retrieval import RetrievalRequest  # noqa: E402


def _row(cid: str, section: str, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=cid, section_path=[section] if section else [],
                           text=text or f"【章节：{section}】{cid}")


class TestSectionChannelUnit:
    def test_returns_chunks_of_named_section(self):
        from app.modules.retrieval import service as S

        rows = [_row("a1", "方法设计"), _row("a2", "方法设计"), _row("b1", "结果分析")]
        hits = S._section_channel("论文中「结果分析」这一部分主要讲了什么？", rows)
        assert [cid for cid, _ in hits] == ["b1"], "点名了「结果分析」就只该召回它"

    def test_no_section_named_returns_empty(self):
        from app.modules.retrieval import service as S

        rows = [_row("a1", "方法设计"), _row("b1", "结果分析")]
        assert S._section_channel("这篇论文用了什么优化器？", rows) == []

    def test_longest_title_wins(self):
        """「方法」与「方法实现流程」同时命中时取**更具体**的那个。"""
        from app.modules.retrieval import service as S

        rows = [_row("a1", "方法"), _row("b1", "方法实现流程")]
        hits = S._section_channel("论文中「方法实现流程」主要讲了什么？", rows)
        assert [cid for cid, _ in hits] == ["b1"]

    def test_ignores_one_char_titles(self):
        """单字标题（如 "1"）太泛，不做章节匹配，避免误召回。"""
        from app.modules.retrieval import service as S

        rows = [_row("a1", "1")]
        assert S._section_channel("第 1 节讲了什么？", rows) == []

    def test_capped_and_deduped(self):
        from app.modules.retrieval import service as S

        rows = [_row(f"x{i}", "长章节") for i in range(40)]
        hits = S._section_channel("「长章节」讲了什么？", rows)
        assert len(hits) <= S.SECTION_CHANNEL_LIMIT
        assert len({cid for cid, _ in hits}) == len(hits), "不得重复 chunk"

    def test_quotes_and_spaces_are_ignored(self):
        """问题里的书名号/引号/空格不能挡住标题匹配。"""
        from app.modules.retrieval import service as S

        rows = [_row("a1", "2 相关背景")]
        assert S._section_channel("论文中「2  相关背景」这一部分主要讲了什么？", rows)


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
def two_sections():
    """「方法设计」措辞与问句高度重合，「结果分析」则不然 —— 词法/向量都偏向方法节。"""
    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM
    from app.models.source import new_id
    from app.modules import papers as papers_mod
    from app.modules import retrieval

    paper = papers_mod.create_paper(
        PaperCreate(title="章节通道测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("sections"), SourceMetadata(original_filename="s.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    # 每节都要**超过 TARGET_CHARS(700)**，否则两节会被并进同一个 chunk，测不出章节归属
    pad = "本节其余内容用于说明该步骤的细节与实现取舍。"
    blocks = [
        ("方法设计", "方法设计的核心是图神经网络编码器与对比学习目标。" + pad * 12),
        ("方法设计", "训练使用 AdamW 优化器，学习率 3e-4，批大小 64。" + pad * 12),
        ("方法设计", "模型包含三层 GIN 与一个读出层，参数量 1.2M。" + pad * 12),
        ("结果分析", "在 QM9 数据集上，平均绝对误差相比基线下降 12%。" + pad * 12),
        ("结果分析", "消融实验显示去掉对比学习目标后误差上升 8%。" + pad * 12),
    ]
    with db_mod.SessionLocal() as db:
        page = PageORM(id=new_id(), paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, page_label="1", label_status="verified",
                       width_pt=612.0, height_pt=792.0,
                       text="\n".join(t for _, t in blocks))
        db.add(page)
        db.flush()
        for idx, (section, text) in enumerate(blocks):
            db.add(BlockORM(
                id=new_id(), paper_id=paper.id, revision_id=revision.id,
                page_id=page.id, ordinal=idx, kind="paragraph", text=text,
                origin="source_extraction", anchor_id=None, section_path=[section],
            ))
        db.commit()

    retrieval.index(scope, new_ctx(scope))
    return {"scope": scope}


class TestSectionChannelRetrieval:
    def test_named_section_reaches_top_hits(self, two_sections):
        """点名「结果分析」时，该章节的块必须出现在 top-5（修复前会被方法节挤掉）。"""
        from app.modules import retrieval

        scope = two_sections["scope"]
        result = retrieval.retrieve(
            RetrievalRequest(scope=scope, query="论文中「结果分析」这一部分主要讲了什么？",
                             top_k=5),
            new_ctx(scope),
        )
        assert result.hits, "应有命中"
        assert any("【章节：结果分析】" in h.text for h in result.hits), \
            f"点名章节未被召回：{[h.text[:30] for h in result.hits]}"

    def test_plain_query_has_no_section_boost(self, two_sections):
        """没点名章节的普通查询不注入章节通道（行为不变）。"""
        from app.modules import retrieval
        from app.modules.retrieval import service as S

        scope = two_sections["scope"]
        result = retrieval.retrieve(
            RetrievalRequest(scope=scope, query="学习率是多少？", top_k=5),
            new_ctx(scope),
        )
        assert result.hits, "普通查询仍应正常命中"
        assert S._section_channel("学习率是多少？", []) == []

    def test_retrieval_has_no_new_warnings(self, two_sections):
        """章节通道是功能不是降级：不得新增告警（否则会被 recovery 指标当降级）。"""
        from app.modules import retrieval

        scope = two_sections["scope"]
        result = retrieval.retrieve(
            RetrievalRequest(scope=scope, query="论文中「结果分析」这一部分主要讲了什么？",
                             top_k=5),
            new_ctx(scope),
        )
        codes = [getattr(w, "code", "") for w in (result.warnings or [])]
        assert not any("section" in c for c in codes), codes


class TestHybridRankingRegression:
    """**复现 live 失败的确切排序**（不需要 embedding，纯融合层）。

    实测 paper 3：问「2 相关背景」时，该章节的块在**词法**里排第 1（lex=34.7），
    但只有单通道贡献 → RRF≈0.0164；而向量+词法双通道的无关块 RRF≈0.026–0.030。
    结果目标块排第 **6**，被 `top_k=5` 截掉 → 模型判"证据不足"→ 拒答。
    """

    def test_single_channel_target_is_cut_without_section_channel(self):
        from app.modules.retrieval import fusion

        lexical = [(f"c{i:02d}", 10.0 - i) for i in range(1, 7)]  # 目标 c06 词法第 6
        vector = [(f"c{i:02d}", 0.9) for i in range(1, 6)]
        base = fusion.rrf_fuse([("lexical", lexical), ("vector", vector)])
        assert [c.chunk_id for c in base[:5]] == ["c01", "c02", "c03", "c04", "c05"], \
            "前提：不注入章节通道时，单通道的目标块确实进不了 top-5"

    def test_section_weight_lifts_target_into_top_k(self):
        from app.modules.retrieval import fusion
        from app.modules.retrieval import service as S

        lexical = [(f"c{i:02d}", 10.0 - i) for i in range(1, 7)]
        vector = [(f"c{i:02d}", 0.9) for i in range(1, 6)]
        rows = [_row("c06", "2 相关背景")]
        section = S._section_channel("论文中「2 相关背景」这一部分主要讲了什么？", rows)
        assert section, "点名了章节就必须产出一路候选"
        boosted = fusion.rrf_fuse(
            [("lexical", lexical), ("vector", vector), ("section", section)],
            weights={**fusion.DEFAULT_WEIGHTS, "section": S.SECTION_WEIGHT},
        )
        assert "c06" in [c.chunk_id for c in boosted[:5]], \
            "章节权重必须把被 top_k 截掉的目标章节块抬回 top-5"
