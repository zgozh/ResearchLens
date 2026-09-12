"""方法步骤的确定性来源：**方法/实验章内的已验证陈述**（ADR-0042）。

真实缺陷（paper 1 实测）：`_structure_without_llm` 只把 ``type == "METHOD"`` 的断言
变成步骤，而 ``_claim_type_for`` 是关键词启发式（文本里含"方法/算法/流程/训练"才算
METHOD）。结果：

- paper 1 有 **2 个 method 章 + 1 个 experiment 章**（章节 kind 由标题确定性推断），
  但 5 条展项断言里只有 **1 条**被判成 METHOD → "方法动画"**只有 1 步**；
- 同时 LLM 结构路径实测对 paper 1 返回 ``method_steps=0``，没有任何补充。

修法：步骤改为按**章节归属**取——方法/实验章里按文档顺序排列的已验证陈述即步骤，
``phase`` 用章节标题。文本仍是断言原文（可追溯、不引入新事实），
归属判定与讲解侧同源（块级引用落在本节 ``source_block_ids``）。
归属为空时**退回**原有的"METHOD 类型断言"路径，不改变旧行为。
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
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="方法步骤来源", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("steps"), SourceMetadata(original_filename="s.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM

    page_id = _uniq("pg")
    spec = [
        ("1 引言", "heading"),
        ("软件缺陷预测是缺陷检测技术的有效补充。", "paragraph"),
        ("2 本文方法", "heading"),
        ("先对图像做高阶 Haar 小波变换。", "paragraph"),
        ("再计算各方向分解矩阵的范数均值。", "paragraph"),
        ("3 实验", "heading"),
        ("实验采用十折交叉验证。", "paragraph"),
        ("4 结论", "heading"),
        ("该方法提高了隐蔽性。", "paragraph"),
    ]
    blocks = {}
    with db_mod.SessionLocal() as db:
        db.add(PageORM(id=page_id, paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, width_pt=595.0, height_pt=842.0))
        for i, (text, kind) in enumerate(spec):
            bid = _uniq("blk")
            blocks[text] = bid
            db.add(BlockORM(id=bid, paper_id=paper.id, revision_id=revision.id,
                            page_id=page_id, ordinal=i, kind=kind, text=text,
                            origin="source_extraction"))
        db.commit()
    return {"scope": scope, "blocks": blocks}


def _claim(scope, *, claim_id, text, block_id, type_="RESULT"):
    """写入一条**已验证**的展项断言，引用给定块。"""
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM, StatementORM

    statement_id = _uniq("stmt")
    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=text, kind="fact",
            citations=[{"block_id": block_id}], qualifiers=[], validation=None,
            evidence_ids=[], origin="generated", display_class="verified_fact", ordinal=0,
        ))
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type=type_, status="verified",
            rationale="", evidence_ids=[], confidence=None, visibility="exhibit",
        ))
        db.commit()
    return statement_id


class TestStepsFromMethodSections:
    def test_resolution_typed_claims_in_method_section_become_steps(self, world):
        """**核心**：方法章里的 RESULT 型断言也要成为步骤（此前只认 METHOD 类型）。"""
        from app.contracts.common import new_ctx
        from app.modules import claims as claims_mod

        scope = world["scope"]
        b = world["blocks"]
        _claim(scope, claim_id="m1", text="先对图像做高阶 Haar 小波变换。",
               block_id=b["先对图像做高阶 Haar 小波变换。"], type_="RESULT")
        _claim(scope, claim_id="m2", text="再计算各方向分解矩阵的范数均值。",
               block_id=b["再计算各方向分解矩阵的范数均值。"], type_="RESULT")
        _claim(scope, claim_id="r1", text="该方法提高了隐蔽性。",
               block_id=b["该方法提高了隐蔽性。"], type_="METHOD")

        structure = claims_mod.build_structure(scope, new_ctx(scope))

        labels = [s.label.text for s in structure.method_steps]
        assert len(structure.method_steps) >= 2, f"方法章里的两条陈述都应成为步骤：{labels}"
        assert any("Haar 小波变换" in t for t in labels)
        assert any("范数均值" in t for t in labels)

    def test_phase_is_the_section_heading(self, world):
        """``phase`` 用章节标题，让前端能显示"这一步属于哪一章"。"""
        from app.contracts.common import new_ctx
        from app.modules import claims as claims_mod

        scope = world["scope"]
        b = world["blocks"]
        _claim(scope, claim_id="m1", text="先对图像做高阶 Haar 小波变换。",
               block_id=b["先对图像做高阶 Haar 小波变换。"])

        structure = claims_mod.build_structure(scope, new_ctx(scope))

        assert structure.method_steps, "必须有步骤"
        assert structure.method_steps[0].phase == "2 本文方法", \
            f"phase 应为章节标题，实际 {structure.method_steps[0].phase!r}"

    def test_steps_follow_document_order(self, world):
        from app.contracts.common import new_ctx
        from app.modules import claims as claims_mod

        scope = world["scope"]
        b = world["blocks"]
        _claim(scope, claim_id="m2", text="再计算各方向分解矩阵的范数均值。",
               block_id=b["再计算各方向分解矩阵的范数均值。"])
        _claim(scope, claim_id="m1", text="先对图像做高阶 Haar 小波变换。",
               block_id=b["先对图像做高阶 Haar 小波变换。"])

        structure = claims_mod.build_structure(scope, new_ctx(scope))

        labels = [s.label.text for s in structure.method_steps]
        assert labels and "Haar 小波变换" in labels[0], f"步骤必须按文档顺序：{labels}"

    def test_no_claim_is_duplicated_across_steps(self, world):
        """同一断言不得出现在两个步骤里（与讲解侧同一条不变式）。"""
        from app.contracts.common import new_ctx
        from app.modules import claims as claims_mod

        scope = world["scope"]
        b = world["blocks"]
        _claim(scope, claim_id="m1", text="先对图像做高阶 Haar 小波变换。",
               block_id=b["先对图像做高阶 Haar 小波变换。"])
        _claim(scope, claim_id="e1", text="实验采用十折交叉验证。",
               block_id=b["实验采用十折交叉验证。"])

        structure = claims_mod.build_structure(scope, new_ctx(scope))

        seen = [cid for s in structure.method_steps for cid in (s.claim_ids or [])]
        assert len(seen) == len(set(seen)), f"步骤之间断言重复：{seen}"

    def test_falls_back_to_method_typed_claims(self, world):
        """方法/实验章都没有归属时，退回"METHOD 类型断言"（不改变旧行为）。"""
        from app.contracts.common import new_ctx
        from app.modules import claims as claims_mod

        scope = world["scope"]
        b = world["blocks"]
        # 这条断言引用"引言"里的块，且类型是 METHOD → 章节归属拿不到，应走兜底
        _claim(scope, claim_id="only_method", text="软件缺陷预测是缺陷检测技术的有效补充。",
               block_id=b["软件缺陷预测是缺陷检测技术的有效补充。"], type_="METHOD")

        structure = claims_mod.build_structure(scope, new_ctx(scope))

        labels = [s.label.text for s in structure.method_steps]
        assert len(labels) == 1 and "缺陷预测" in labels[0], f"兜底路径失效：{labels}"
