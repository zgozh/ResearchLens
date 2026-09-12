"""章节 → 正文页定位：**块级锚点回填**与**章节锚点派生**（ADR-0029）。

真实缺陷（3 篇真实论文实测，Postgres）：

* ``blocks.anchor_id`` **823/823 全为 NULL**；
* ``section_records.anchor_ids`` **21/21 全为 ``[]``**；
* ``manifest.section_index[].anchor_ids`` 因此全空，``exhibits.structure.sections`` 亦然。

后果：前端"论文地图 → 阅读该章节正文"拿不到任何锚点，只能退化成"打开论文视图"，
用户看到的就是"点了章节但没有跳转到对应正文页"。

根因：``parse/service.py`` 为每页构造了页级 ``Anchor``（``segments[0].block_ids``
列出该页所有块），但**从不回填 ``Block.anchor_id``** —— 反向指针缺失，
于是"块 → 锚点 → 物理页"这条定位链条从第一步就断了。

修复方向（本文件锁定）：
1. 解析期把 ``Block.anchor_id`` 指向其所在页的页锚点（双向一致）；
2. 分节期由本节块的锚点**派生** ``SectionRecord.anchor_ids``；
3. 读路径对历史数据做**自愈式补齐**（``anchor_ids`` 为空时按
   ``块 → 所在页 → 页锚点`` 现算），避免为了修数据显示层而重跑昂贵的 LLM 抽取。
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


def _uniq(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def world():
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="章节定位测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("anchor"), SourceMetadata(original_filename="a.pdf")
    )
    from app.contracts.common import Scope

    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "source": source, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


def _seed_page(scope, *, page_id, pdf_page_index):
    from app.core import db as db_mod
    from app.models.artifacts import PageORM

    with db_mod.SessionLocal() as db:
        db.add(PageORM(
            id=page_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            pdf_page_index=pdf_page_index, width_pt=595.0, height_pt=842.0,
        ))
        db.commit()
    return page_id


def _seed_block(scope, *, page_id, ordinal, text, kind="paragraph", anchor_id=None):
    from app.core import db as db_mod
    from app.models.artifacts import BlockORM

    block_id = _uniq("blk")
    with db_mod.SessionLocal() as db:
        db.add(BlockORM(
            id=block_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            page_id=page_id, ordinal=ordinal, kind=kind, text=text,
            origin="source_extraction", anchor_id=anchor_id,
        ))
        db.commit()
    return block_id


def _seed_page_anchor(scope, *, page_id, pdf_page_index, block_ids, many=True):
    """造页锚点；``many=False`` 造"单块证据锚点"（用于验证不会误选）。"""
    from app.core import db as db_mod
    from app.models.artifacts import AnchorORM

    anchor_id = _uniq("anc") if not many else _uniq("panchor")
    with db_mod.SessionLocal() as db:
        db.add(AnchorORM(
            id=anchor_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            source_document_id="", precision="page",
            segments=[{
                "page_id": page_id, "pdf_page_index": pdf_page_index,
                "page_label": None, "rect": None, "quads": [],
                "block_ids": list(block_ids), "quote_spans": [],
            }],
            transform=None, raw_ref=None,
        ))
        db.commit()
    return anchor_id


def _seed_section(scope, *, section_id, heading, block_ids, anchor_ids=None, ordinal=0, kind="intro"):
    from app.core import db as db_mod
    from app.models.evidence import SectionRecordORM

    with db_mod.SessionLocal() as db:
        db.add(SectionRecordORM(
            id=section_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            heading=heading, kind=kind, source_block_ids=list(block_ids),
            anchor_ids=list(anchor_ids or []), summary={"text": "", "spans": []},
            key_points=[], ordinal=ordinal,
        ))
        db.commit()
    return section_id


# ===================================================== 1. 解析期：块 ↔ 页锚点双向一致


class TestParseBackfillsBlockAnchors:
    def test_every_block_points_at_its_page_anchor(self, world):
        """每个块都必须带上所在页的锚点 id，否则章节定位无锚可用。"""
        from app.contracts.common import new_ctx
        from app.modules import parse as parse_mod

        scope = world["scope"]
        result = parse_mod.parse(world["source"], new_ctx(scope))

        assert result.blocks, "解析必须产出块"
        assert result.anchors, "解析必须产出页级锚点"

        anchor_by_id = {a.id: a for a in result.anchors}
        for block in result.blocks:
            assert block.anchor_id, (
                f"块 {block.id!r} 没有 anchor_id —— blocks.anchor_id 恒 NULL 会让"
                f"「块 → 锚点 → 物理页」整条定位链条断裂（真实库 823/823 全空）"
            )
            assert block.anchor_id in anchor_by_id, "块必须指向本次解析产出的锚点"

    def test_anchor_and_block_agree_in_both_directions(self, world):
        """锚点的 block_ids 与块的 anchor_id 必须互相一致（不产生孤儿指针）。"""
        from app.contracts.common import new_ctx
        from app.modules import parse as parse_mod

        scope = world["scope"]
        result = parse_mod.parse(world["source"], new_ctx(scope))

        block_by_id = {b.id: b for b in result.blocks}
        for anchor in result.anchors:
            for segment in anchor.segments:
                for block_id in segment.block_ids:
                    block = block_by_id.get(block_id)
                    assert block is not None, "锚点不得引用不存在的块"
                    assert block.anchor_id == anchor.id, (
                        f"块 {block_id!r} 指向 {block.anchor_id!r}，但锚点 {anchor.id!r} "
                        f"声称包含它 —— 双向指针必须一致"
                    )

    def test_persisted_blocks_keep_anchor_id(self, world):
        """落库后 ``blocks.anchor_id`` 不得丢失（否则读路径又变回 NULL）。"""
        from app.contracts.common import new_ctx
        from app.modules import parse as parse_mod

        scope = world["scope"]
        ctx = new_ctx(scope)
        result = parse_mod.parse(world["source"], ctx)
        parse_mod.persist(scope, result, ctx)

        rows = parse_mod.get_blocks(scope, [b.id for b in result.blocks])
        got = {r.id: r.anchor_id for r in rows}
        assert got, "必须能读回块"
        for block_id, anchor_id in got.items():
            assert anchor_id, f"落库后块 {block_id!r} 的 anchor_id 必须保留"


# ===================================================== 2. 分节期：章节锚点由块派生


class TestSectionAnchorDerivation:
    def _seed_paper_body(self, scope):
        page = _seed_page(scope, page_id=_uniq("pg"), pdf_page_index=0)
        spec = [
            ("基于软件度量的Solidity智能合约缺陷预测方法", "title"),
            ("1 引言", "heading"),
            ("软件缺陷预测是缺陷检测技术的有效补充。", "paragraph"),
            ("5 实验结果与分析", "heading"),
            ("实验采用十折交叉验证。", "paragraph"),
        ]
        block_ids = [
            _seed_block(scope, page_id=page, ordinal=i, text=text, kind=kind)
            for i, (text, kind) in enumerate(spec)
        ]
        anchor_id = _seed_page_anchor(scope, page_id=page, pdf_page_index=0, block_ids=block_ids)
        # 解析期已回填锚点：这里显式模拟修复后的状态
        from app.core import db as db_mod
        from app.models.artifacts import BlockORM

        with db_mod.SessionLocal() as db:
            for block_id in block_ids:
                row = db.get(BlockORM, block_id)
                row.anchor_id = anchor_id
            db.commit()
        return {"page": page, "anchor": anchor_id, "blocks": dict(zip((s[0] for s in spec), block_ids))}

    def test_sections_derive_anchor_ids_from_their_blocks(self, world):
        """章节的 anchor_ids 必须来自本节块的页锚点，且**本节自成集合**。"""
        from app.contracts.common import new_ctx
        from app.modules import claims as claims_mod

        scope = world["scope"]
        seeded = self._seed_paper_body(scope)

        structure = claims_mod.build_structure(scope, new_ctx())
        by_heading = {s.heading: s for s in structure.sections}

        assert "1 引言" in by_heading, f"实际章节：{list(by_heading)}"
        for section in structure.sections:
            assert section.anchor_ids, (
                f"章节「{section.heading}」没有 anchor_ids —— "
                f"前端「阅读该章节正文」就无处可跳（真实库 21/21 全空）"
            )
            assert seeded["anchor"] in section.anchor_ids

    def test_sections_without_page_anchor_do_not_fabricate_ids(self, world):
        """块没有锚点时不许编造：宁可留空，也不能给假锚点。"""
        from app.contracts.common import new_ctx
        from app.modules import claims as claims_mod

        scope = world["scope"]
        page = _seed_page(scope, page_id=_uniq("pg"), pdf_page_index=0)
        _seed_block(scope, page_id=page, ordinal=0, text="1 引言", kind="heading")
        _seed_block(scope, page_id=page, ordinal=1, text="正文。", kind="paragraph")

        structure = claims_mod.build_structure(scope, new_ctx())
        for section in structure.sections:
            assert section.anchor_ids == [], "无锚点时必须留空，不得伪造"


# ===================================================== 3. 读路径：历史数据自愈补齐


class TestSectionAnchorReadBackfill:
    def test_get_structure_backfills_from_page_anchors(self, world):
        """老数据（section.anchor_ids 为空、blocks.anchor_id 也为 NULL）必须能现算补齐。

        这是修数据显示层而不重跑 LLM 抽取的关键：库里有页锚点，就一定能算出来。
        """
        from app.modules import claims as claims_mod

        scope = world["scope"]
        page = _seed_page(scope, page_id=_uniq("pg"), pdf_page_index=3)
        b1 = _seed_block(scope, page_id=page, ordinal=0, text="1 引言", kind="heading")
        b2 = _seed_block(scope, page_id=page, ordinal=1, text="正文。", kind="paragraph")
        page_anchor = _seed_page_anchor(scope, page_id=page, pdf_page_index=3, block_ids=[b1, b2])
        # 历史形态：块不带锚点、章节 anchor_ids 为空
        _seed_section(scope, section_id=_uniq("sec"), heading="1 引言",
                      block_ids=[b1, b2], anchor_ids=[])

        # 先确认这确实是"老数据"形态
        from app.core import db as db_mod
        from app.models.artifacts import BlockORM

        with db_mod.SessionLocal() as db:
            assert db.get(BlockORM, b1).anchor_id is None

        structure = claims_mod.get_structure(scope)
        assert structure.sections, "必须读回章节"
        section = structure.sections[0]
        assert section.anchor_ids == [page_anchor], (
            f"读路径必须按「块 → 所在页 → 页锚点」补齐，实际 {section.anchor_ids!r}"
        )
        # 只读补齐：不得写库
        from app.models.evidence import SectionRecordORM

        with db_mod.SessionLocal() as db:
            row = db.get(SectionRecordORM, section.id)
            if row is not None:
                assert list(row.anchor_ids or []) == [], "读路径不得产生写副作用"

    def test_prefers_page_anchor_over_single_block_evidence_anchor(self, world):
        """同页存在单块证据锚点时，必须选页锚点（块数最多的那个），否则跳转不稳定。"""
        from app.modules import claims as claims_mod

        scope = world["scope"]
        page = _seed_page(scope, page_id=_uniq("pg"), pdf_page_index=1)
        b1 = _seed_block(scope, page_id=page, ordinal=0, text="1 引言", kind="heading")
        b2 = _seed_block(scope, page_id=page, ordinal=1, text="正文。", kind="paragraph")
        _seed_page_anchor(scope, page_id=page, pdf_page_index=1, block_ids=[b1], many=False)
        page_anchor = _seed_page_anchor(scope, page_id=page, pdf_page_index=1, block_ids=[b1, b2])
        _seed_section(scope, section_id=_uniq("sec"), heading="1 引言",
                      block_ids=[b1, b2], anchor_ids=[])

        structure = claims_mod.get_structure(scope)
        assert structure.sections[0].anchor_ids == [page_anchor]

    def test_existing_anchor_ids_are_preserved(self, world):
        """已写好的 anchor_ids 不得被读路径覆盖。"""
        from app.modules import claims as claims_mod

        scope = world["scope"]
        page = _seed_page(scope, page_id=_uniq("pg"), pdf_page_index=2)
        b1 = _seed_block(scope, page_id=page, ordinal=0, text="1 引言", kind="heading")
        _seed_page_anchor(scope, page_id=page, pdf_page_index=2, block_ids=[b1])
        _seed_section(scope, section_id=_uniq("sec"), heading="1 引言",
                      block_ids=[b1], anchor_ids=["explicit-anchor"])

        structure = claims_mod.get_structure(scope)
        assert structure.sections[0].anchor_ids == ["explicit-anchor"]
