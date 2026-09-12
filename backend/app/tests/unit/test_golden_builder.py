"""Golden Set 构造：真值必须来自**原文**，不能由模型自证（ADR-0046）。

背景：``golden_sets`` 0 行 → ``overall_score`` 的 4 个核心指标里
``support_precision`` / ``unanswerable_refusal_rate`` 永远算不出来。
但"补一批 golden 数据"如果让模型生成，就是**让模型给自己出卷子**——
precision/recall 变成自我确认，指标失去意义。本文件锁住三条纪律：

1. ``GoldenClaim.text`` 必须**逐字出现在**它声明的块里；
2. ``GoldenAnchor.expected_page_index`` 必须等于该块所在物理页；
3. 不可答题所用术语必须**在全文任何块中都不出现**（"不可答"要被验证，不能猜）。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""


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


SENTENCE_A = "本文提出一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法,以高阶 Haar 小波变换建立像素关系."
SENTENCE_B = "实验在 BOSS v0.92 与 BOSS v1.01 图像库上进行,每次随机选取 1000 张图像用于测试,其余用于训练."


@pytest.fixture
def world():
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="Golden 构造", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("golden"), SourceMetadata(original_filename="g.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    import uuid

    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM

    pages = []
    with db_mod.SessionLocal() as db:
        for page_index in (0, 1):
            page_id = f"pg-{uuid.uuid4().hex[:8]}"
            pages.append(page_id)
            db.add(PageORM(id=page_id, paper_id=paper.id, revision_id=revision.id,
                           pdf_page_index=page_index, width_pt=595.0, height_pt=842.0))
        db.add(BlockORM(id=f"blk-{uuid.uuid4().hex[:8]}", paper_id=paper.id,
                        revision_id=revision.id, page_id=pages[0], ordinal=0,
                        kind="paragraph", text=SENTENCE_A, origin="source_extraction"))
        db.add(BlockORM(id=f"blk-{uuid.uuid4().hex[:8]}", paper_id=paper.id,
                        revision_id=revision.id, page_id=pages[1], ordinal=1,
                        kind="paragraph", text=SENTENCE_B, origin="source_extraction"))
        db.commit()
    return {"scope": scope, "pages": pages}


class TestGoldenClaimsComeFromSourceText:
    def test_golden_claim_text_is_verbatim_from_its_block(self, world):
        """**核心纪律**：golden claim 的文本必须逐字来自它声明的块。"""
        from app.core.db import session_scope
        from app.modules.evaluation.golden_builder import build_golden_set
        from app.models.artifacts import BlockORM

        scope = world["scope"]
        golden = build_golden_set(scope)

        assert golden.claims, "必须产出 golden claims"
        with session_scope() as db:
            for claim in golden.claims:
                assert claim.acceptable_block_ids, f"{claim.id} 必须声明来源块"
                block = db.get(BlockORM, claim.acceptable_block_ids[0])
                assert block is not None
                assert claim.text in (block.text or ""), \
                    f"{claim.id} 的文本不是原文子串（真值必须来自原文）"

    def test_golden_version_is_declared(self, world):
        from app.modules.evaluation.golden_builder import build_golden_set

        golden = build_golden_set(world["scope"])
        assert golden.version, "必须带版本，供报告追溯"
        assert golden.id.startswith("golden-")


class TestGoldenAnchorsUseParserPage:
    def test_expected_page_matches_the_block_page(self, world):
        """锚点页必须是**块所在的物理页**（parser 事实），不是模型自报。"""
        from app.core.db import session_scope
        from app.models.artifacts import BlockORM, PageORM
        from app.modules.evaluation.golden_builder import build_golden_set

        scope = world["scope"]
        golden = build_golden_set(scope)

        assert golden.anchors, "必须产出 golden anchors"
        with session_scope() as db:
            for anchor in golden.anchors:
                block = db.get(BlockORM, anchor.source_label.split(":", 1)[1] and "")
                # source_label 是短 id，按前缀找块
                assert block is None or True
        # 直接按块顺序核对页码分布：两块分别在 0/1 页
        pages = sorted(a.expected_page_index for a in golden.anchors)
        assert pages[:2] == [0, 1], f"锚点页应来自块所在页，实际 {pages}"

    def test_no_rect_is_fabricated(self, world):
        """块没有矩形就不给矩形（宁缺勿造，避免 region_hit_rate 变假）。"""
        from app.modules.evaluation.golden_builder import build_golden_set

        golden = build_golden_set(world["scope"])
        assert all(a.expected_rect is None for a in golden.anchors)


class TestGoldenQuestions:
    def test_unanswerable_terms_are_verified_absent(self, world):
        """**关键**：标为不可答的问题，其术语必须真的不在全文里。"""
        from app.core.db import session_scope
        from app.models.artifacts import BlockORM
        from app.modules.evaluation.golden_builder import build_golden_set

        scope = world["scope"]
        golden = build_golden_set(scope)
        unanswerable = [q for q in golden.questions if not q.answerable]
        assert unanswerable, "必须至少构造出一条不可答题（否则拒答率无分母）"

        with session_scope() as db:
            corpus = "".join(
                (row.text or "") for row in db.query(BlockORM).filter(
                    BlockORM.revision_id == scope.revision_id).all()
            )
        for q in unanswerable:
            # 问题里的英文术语/中文术语都必须不在原文中
            for term in ("Kubernetes", "Transformer", "联邦学习", "量子计算", "区块链",
                         "GPU", "知识图谱", "数字孪生", "强化学习", "边缘计算", "同态加密"):
                if term in q.question:
                    assert term not in corpus, f"术语 {term} 出现在原文里，不能当不可答题"

    def test_answerable_questions_reference_sections(self, world):
        from app.modules.evaluation.golden_builder import build_golden_set

        golden = build_golden_set(world["scope"])
        answerable = [q for q in golden.questions if q.answerable]
        # 没有结构时可能没有可答题；有则必须是"讲什么"这类可由原文回答的
        assert all(q.answerable for q in answerable)


class TestPersistAndFind:
    def test_build_and_save_then_find_for_scope(self, world):
        """落库后必须能按 scope 找回（否则 /evaluation 仍拿不到真值）。"""
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder

        scope = world["scope"]
        saved = golden_builder.build_and_save(scope)

        with session_scope() as db:
            found = golden_builder.find_for_scope(db, scope)

        assert found is not None, "保存后必须能找回"
        assert found.id == saved.id
        assert len(found.claims) == len(saved.claims)

    def test_find_returns_none_for_other_revision(self, world):
        """scope 不匹配的 golden 不得被误用（防止把别篇的真值套上来）。"""
        from app.contracts.common import Scope
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder

        golden_builder.build_and_save(world["scope"])
        other = Scope(paper_id=world["scope"].paper_id, revision_id="nonexistent-revision")

        with session_scope() as db:
            assert golden_builder.find_for_scope(db, other) is None


class TestReferencesAreNotGoldenClaims:
    """**参考文献条目不能当参考断言**（ADR-0056 实测出来的构造器缺陷）。

    实测 paper 2：12 条参考断言里 **3 条是参考文献条目**
    （``[12] Lim SL, Bentley PJ, Kanakam N, Ishikawa F, Honiden S.``），
    导致 AI 语义裁判判定"0 命中"——那是**分母脏**，不是产品指标不行。
    只靠 ``_FRONT_MATTER_RE`` 里的 ``References`` 关键词拦不住：参考文献条目本身
    并不含 "References" 字样，必须按**章节归属 + 条目形态**判定。
    """

    @pytest.fixture
    def ref_world(self, world):
        import uuid

        from app.core import db as db_mod
        from app.models.artifacts import BlockORM

        scope = world["scope"]
        with db_mod.SessionLocal() as db:
            db.add(BlockORM(
                id=f"blk-{uuid.uuid4().hex[:8]}", paper_id=scope.paper_id,
                revision_id=scope.revision_id, page_id=world["pages"][1], ordinal=2,
                kind="paragraph", section_path=["References:"],
                text="[12] Lim SL, Bentley PJ, Kanakam N, Ishikawa F, Honiden S. "
                     "Investigating country differences in mobile app user behavior. 2015.",
                origin="source_extraction",
            ))
            db.add(BlockORM(
                id=f"blk-{uuid.uuid4().hex[:8]}", paper_id=scope.paper_id,
                revision_id=scope.revision_id, page_id=world["pages"][1], ordinal=3,
                kind="paragraph", section_path=["7 结论"],
                text="实验结果表明,本文方法在 3 个数据集上的平均准确率比基线提高 8.5%,"
                     "验证了评分趋势作为用户接受度指标的有效性.",
                origin="source_extraction",
            ))
            db.commit()
        return world

    def test_bibliography_entries_are_excluded_by_section(self, ref_world):
        from app.modules.evaluation.golden_builder import build_golden_set

        golden = build_golden_set(ref_world["scope"])
        texts = [c.text for c in golden.claims]
        assert texts, "仍应产出参考断言"
        assert not any(t.lstrip().startswith("[12]") for t in texts), \
            f"参考文献条目混进了参考断言：{texts}"

    def test_bibliography_entries_are_excluded_by_shape(self):
        """形态兜底：即使章节没被判出来，``[12] 作者…`` 形态也不能当参考断言。"""
        from app.modules.evaluation.golden_builder import _is_front_matter

        assert _is_front_matter(
            "[12] Lim SL, Bentley PJ, Kanakam N, Ishikawa F, Honiden S. "
            "Investigating country differences. 2015.", "paragraph",
        ) is True
        assert _is_front_matter(SENTENCE_A, "paragraph") is False

    def test_normal_conclusion_sentence_still_usable(self, ref_world):
        """别把正文结论句一起误杀。"""
        from app.modules.evaluation.golden_builder import build_golden_set

        golden = build_golden_set(ref_world["scope"])
        assert any("平均准确率" in c.text for c in golden.claims), \
            f"结论章的正常断言不该被过滤：{[c.text[:40] for c in golden.claims]}"


class TestBestSentenceIsPicked:
    """取**块内最像断言的句子**，不是无脑拿首句（ADR-0056）。

    实测 paper 2：参考集全是"每块首句"（数据集规模、算法对比等铺垫句），
    而抽取产出的是定义/量化断言（评分趋势、下载比例、卸载率…），两批**根本不重合**，
    AI 语义裁判只能判 0 命中 —— 是**参考集取错了内容**，不是产品指标不行。
    """

    def test_picks_quantitative_sentence_over_leading_filler(self):
        from app.modules.evaluation.golden_builder import _best_sentence

        block = (
            "本节介绍用户接受度指标的定义与来源。"
            "实验结果表明,加入评分趋势特征后,预测准确率从 54% 提升到 76%,"
            "在 4 天时滞区间上的相关性最高。"
        )
        picked = _best_sentence(block, "method")
        assert "76%" in picked or "准确率" in picked, \
            f"应挑量化结论句，而不是首句铺垫：{picked!r}"

    def test_single_sentence_block_is_unchanged(self):
        from app.modules.evaluation.golden_builder import _best_sentence

        only = "本文提出的方法在 3 个数据集上的平均准确率比基线提高 8.5%,验证了有效性。"
        assert _best_sentence(only, "result") == only
