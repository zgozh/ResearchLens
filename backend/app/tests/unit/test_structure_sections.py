"""M06 结构分节：**文档顺序**与**标题分节**回归测试。

真实缺陷（3 篇真实论文实测）：``section_records`` 全部 ``kind='body'``、
``source_block_ids`` 为空 → 讲解侧拿不到任何归属线索。根因有二：

1. ``claims/repository.get_block_rows`` 用 ``order_by(page_id)`` 排序，而 ``page_id``
   是 UUID 字符串——这是**随机顺序**，不是文档顺序；任何依赖块顺序的分节都不可靠。
2. LLM 结构路径（``_structure_with_llm``）只信模型返回的 heading/block_id 而模型
   并没有给出可用 block_id，于是 section 丢失块级归属。

修复方向：按 ``pages.pdf_page_index`` 恢复文档顺序，并用**确定性的标题分节**为
每个 section 建立块区间，使「陈述 → 引用块 → 章节」这条链路真正可走通。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402


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


def _seed_block(scope, *, page_id, ordinal, text, kind="paragraph"):
    from app.core import db as db_mod
    from app.models.artifacts import BlockORM

    block_id = _uniq("blk")
    with db_mod.SessionLocal() as db:
        db.add(BlockORM(
            id=block_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            page_id=page_id, ordinal=ordinal, kind=kind, text=text,
            origin="source_extraction",
        ))
        db.commit()
    return block_id


def _seed_claim_with_statement(scope, *, claim_id, text, block_ids, type_="RESULT"):
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM, StatementORM

    statement_id = _uniq("st")
    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=text, kind="fact",
            citations=[{"block_id": b} for b in block_ids],
            qualifiers=[], validation=None, evidence_ids=[],
            origin="generated", display_class="verified_fact", ordinal=0,
        ))
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type=type_, status="verified",
            rationale="", evidence_ids=[], confidence=None, visibility="exhibit",
        ))
        db.commit()
    return statement_id


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="分节测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("struct"), SourceMetadata(original_filename="s.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "source": source, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


class TestDocumentOrder:
    def test_block_rows_follow_page_index_not_page_uuid(self, world):
        """块顺序必须按 pdf_page_index，而不是 page_id（UUID 字符串）。"""
        from app.core import db as db_mod
        from app.modules.claims import repository as repo

        scope = world["scope"]
        # 故意让 UUID 字符串顺序与文档顺序**相反**
        first_page = _seed_page(scope, page_id="zzz-page-index-0", pdf_page_index=0)
        second_page = _seed_page(scope, page_id="aaa-page-index-1", pdf_page_index=1)
        _seed_block(scope, page_id=first_page, ordinal=0, text="第一页的正文")
        _seed_block(scope, page_id=second_page, ordinal=0, text="第二页的正文")

        with db_mod.SessionLocal() as db:
            rows = repo.list_block_rows(db, scope.revision_id)

        assert [r.text for r in rows] == ["第一页的正文", "第二页的正文"], \
            "块必须按文档顺序返回；按 page_id 排序会得到随机顺序"


class TestHeadingSections:
    def _seed_paper_body(self, scope):
        """造一篇有 3 个一级标题的迷你正文，返回各块的 id。"""
        page = _seed_page(scope, page_id=_uniq("pg"), pdf_page_index=0)
        spec = [
            ("基于软件度量的Solidity智能合约缺陷预测方法", "title"),
            ("1 引言", "heading"),
            ("软件缺陷预测是缺陷检测技术的有效补充。", "paragraph"),
            ("2 相关背景", "heading"),
            ("目前已在度量元选择方面取得较多成果。", "paragraph"),
            ("5 实验结果与分析", "heading"),
            ("实验采用十折交叉验证。", "paragraph"),
        ]
        return {text: _seed_block(scope, page_id=page, ordinal=i, text=text, kind=kind)
                for i, (text, kind) in enumerate(spec)}

    def test_sections_have_block_ranges_and_inferred_kinds(self, world):
        """标题分节：每个 section 必须有块区间，且 kind 由中英文标题推断。"""
        from app.modules import claims as claims_mod

        scope = world["scope"]
        blocks = self._seed_paper_body(scope)
        _seed_claim_with_statement(
            scope, claim_id="res1", text="实验采用十折交叉验证。",
            block_ids=[blocks["实验采用十折交叉验证。"]], type_="RESULT",
        )

        structure = claims_mod.build_structure(scope, new_ctx())
        by_heading = {s.heading: s for s in structure.sections}

        assert "1 引言" in by_heading, f"实际章节：{list(by_heading)}"
        assert "5 实验结果与分析" in by_heading, f"实际章节：{list(by_heading)}"

        for heading in ("1 引言", "2 相关背景", "5 实验结果与分析"):
            section = by_heading[heading]
            assert section.source_block_ids, f"章节「{heading}」必须有块区间，否则讲解无法归属"

        assert by_heading["1 引言"].kind == "intro"
        assert by_heading["2 相关背景"].kind == "problem"
        assert by_heading["5 实验结果与分析"].kind == "experiment"

    def test_section_block_range_covers_its_own_blocks_only(self, world):
        """块区间必须互不重叠：引言不含实验结果段，反之亦然。"""
        from app.modules import claims as claims_mod

        scope = world["scope"]
        blocks = self._seed_paper_body(scope)

        structure = claims_mod.build_structure(scope, new_ctx())
        by_heading = {s.heading: s for s in structure.sections}

        intro_blocks = set(by_heading["1 引言"].source_block_ids)
        result_blocks = set(by_heading["5 实验结果与分析"].source_block_ids)

        assert blocks["软件缺陷预测是缺陷检测技术的有效补充。"] in intro_blocks
        assert blocks["实验采用十折交叉验证。"] in result_blocks
        assert not (intro_blocks & result_blocks), "章节块区间不得重叠"

    def test_scenes_get_distinct_content_per_section(self, world):
        """端到端：不同章节的断言进入不同场景，内容不得雷同。"""
        from app.modules import claims as claims_mod, scene as scene_mod

        scope = world["scope"]
        blocks = self._seed_paper_body(scope)
        _seed_claim_with_statement(
            scope, claim_id="ctx1", text="软件缺陷预测是缺陷检测技术的有效补充。",
            block_ids=[blocks["软件缺陷预测是缺陷检测技术的有效补充。"]],
            type_="CONTEXT",
        )
        _seed_claim_with_statement(
            scope, claim_id="res1", text="实验采用十折交叉验证。",
            block_ids=[blocks["实验采用十折交叉验证。"]], type_="RESULT",
        )

        structure = claims_mod.build_structure(scope, new_ctx())
        artifact = scene_mod.build(scope, structure)

        populated = [s for s in artifact.scenes if s.statement_ids]
        assert populated, "至少要有场景拿到断言"
        all_ids = [sid for s in artifact.scenes for sid in s.statement_ids]
        assert len(all_ids) == len(set(all_ids)) == 2, \
            f"两条断言各归属一次：{[(s.title.text, s.statement_ids) for s in artifact.scenes]}"

        by_title = {s.title.text: set(s.statement_ids) for s in artifact.scenes}
        intro_scene = by_title.get("1 引言", set())
        result_scene = by_title.get("5 实验结果与分析", set())
        assert intro_scene and result_scene, f"引言与实验结果都应有内容：{by_title}"
        assert not (intro_scene & result_scene), "两个场景的内容不得相同"
