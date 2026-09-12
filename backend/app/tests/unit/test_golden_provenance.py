"""金标集来源纪律：**机器构造的集合不得当人工真值**（ADR-0050）。

规格（`docs/REFACTOR_SPEC.md:613`）明确：

> 自动流水线只可报告可直接测量项或 proxy；**support precision/recall 等必须有标注集
> 才叫 measured**。……只在**包含人工真值的核心指标均可测**时计算 overall_score；
> 否则 canonical null。

而我上一轮把"机器从原文自动构造的金标集"直接当成了真值 → `support_precision` 被
算成 measured、`overall_score` 出了 60/55/75。**那等于让机器给自己出卷子**，
既违反规格也违背"不以假数字冒充"的产品纪律。本文件把它钉死：

- 未确认（`is_tuning=True`）→ precision/recall 一律 ``not_evaluated`` + 告警，
  综合评分保持 **null**（proxy 数值写进告警便于排查，但不当真值）；
- 走 ``POST /golden-set/confirm`` 人工确认后 → 才算 measured、才允许出分。
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


@pytest.fixture
def world():
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="金标来源", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("golden-src"), SourceMetadata(original_filename="g.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    import uuid

    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM

    with db_mod.SessionLocal() as db:
        page_id = f"pg-{uuid.uuid4().hex[:8]}"
        db.add(PageORM(id=page_id, paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, width_pt=595.0, height_pt=842.0))
        db.add(BlockORM(id=f"blk-{uuid.uuid4().hex[:8]}", paper_id=paper.id,
                        revision_id=revision.id, page_id=page_id, ordinal=0,
                        kind="paragraph",
                        text="实验结果表明,该方法把隐蔽性提高了约 7.7%,相比现有指标平均提高约 2.0%.",
                        origin="source_extraction"))
        db.commit()
    return {"scope": scope}


class TestGoldenProvenance:
    def test_auto_built_set_is_marked_tuning(self, world):
        """默认构造出来的集合必须是**调参集**（机器构造、待人确认）。"""
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder

        scope = world["scope"]
        golden_builder.build_and_save(scope)
        with session_scope() as db:
            golden, is_tuning = golden_builder.find_for_scope_ex(db, scope)

        assert golden is not None
        assert is_tuning is True, "机器自动构造的金标集不得被当成人工真值"

    def test_confirm_clears_tuning_flag(self, world):
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder

        scope = world["scope"]
        golden_builder.build_and_save(scope)
        confirmed = golden_builder.confirm_for_scope(scope)

        assert confirmed is not None
        with session_scope() as db:
            _golden, is_tuning = golden_builder.find_for_scope_ex(db, scope)
        assert is_tuning is False, "确认后必须不再标为调参集"

    def test_confirm_without_set_returns_none(self, world):
        from app.modules.evaluation import golden_builder

        assert golden_builder.confirm_for_scope(world["scope"]) is None


class TestEvaluationRespectsProvenance:
    def test_tuning_set_keeps_score_null_and_reports_proxy(self, world):
        """**核心纪律**：调参集不得让 precision 变 measured，也不得算出 overall_score。"""
        from app.modules.evaluation import golden_builder, legacy as eval_legacy
        from app.modules.evaluation import service as eval_service

        scope = world["scope"]
        golden_builder.build_and_save(scope)   # annotated=False → 调参集

        payload = eval_legacy._input_for(scope)
        assert payload.golden is not None and payload.golden_is_tuning is True

        report = eval_service.compute(payload)

        precision = report.metric("support_precision")
        assert precision is not None and precision.status == "not_evaluated", \
            f"调参集不得让 precision 变 measured：{precision}"
        assert report.overall_score is None, \
            f"调参集不得算出综合评分（会变成机器给自己打分）：{report.overall_score}"
        codes = [w.code for w in report.warnings]
        assert "golden_not_annotated" in codes, codes

    def test_confirmed_set_allows_measured_metrics(self, world):
        """人工确认后，precision/recall 才允许 measured（此例无预测断言 → 仍可能 not_evaluated，
        但**原因不能是"未确认"**）。"""
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder, legacy as eval_legacy
        from app.modules.evaluation import service as eval_service

        scope = world["scope"]
        golden_builder.build_and_save(scope)
        golden_builder.confirm_for_scope(scope)

        payload = eval_legacy._input_for(scope)
        with session_scope() as db:
            _g, is_tuning = golden_builder.find_for_scope_ex(db, scope)
        assert is_tuning is False
        assert payload.golden_is_tuning is False

        report = eval_service.compute(payload)
        codes = [w.code for w in report.warnings]
        assert "golden_not_annotated" not in codes, \
            f"已确认的集合不该再报'未人工确认'：{codes}"
