"""金标集来源纪律 —— **R4-M5 按新语义重写**（ADR D-105，推翻 D-50）。

原语义为什么失效（逐条说明，不是"删掉不测了"）：

本文件此前钉死的是 D-50：「机器构造的集合**不得当人工真值**；未走
``POST /golden-set/confirm`` 人工确认前，precision/recall 一律 not_evaluated、
``overall_score`` 保持 null」。这条纪律在**当时**是对的（防止"让机器给自己出卷子"）。

R4 的产品决策（用户拍板："取消一切跟人工有关的，那个自动评测直接全部 ai 评 ai 打分"）
推翻了它，理由是**真实约束**：人工确认在真实使用中永远不会发生（单人参赛、没有标注人力），
于是主分恒为 null，界面只能永远显示"未确认"，用户永远看不到分数。

**新语义**（本文件现在锁住的）：
- 金标集只有一种形态：AI/确定性构造，**需要标注的是来源而不是等人工确认**；
- ``support_precision/recall`` 一律走 **AI 裁判语义判等**，状态 `proxy`（**不是** measured）；
- ``overall_score`` 是**主分**且**允许 proxy 参与**，带 ``overall_score_basis="ai_generated"``；
- **保留的纪律**（这才是 D-50 里真正不能丢的部分）：
  1. proxy 就是 proxy，不许声称 measured；
  2. AI 裁判没出结论时 → ``not_evaluated`` + 原因告警，**绝不用 0 冒充**；
  3. 分数来源必须对用户可见（`overall_score_basis`）。
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
    def test_auto_built_set_is_selectable(self, world):
        """构造出来的集合必须可被评测选中（不再有"待人工确认"这个前置状态）。"""
        from app.core.db import session_scope
        from app.modules.evaluation import golden_builder

        scope = world["scope"]
        golden_builder.build_and_save(scope)
        with session_scope() as db:
            golden, is_tuning = golden_builder.find_for_scope_ex(db, scope)

        assert golden is not None
        # `is_tuning` 是保留的历史返回位（恒 False），不再承载产品语义
        assert is_tuning is False

    def test_confirm_machinery_is_deleted(self, world):
        """人工确认环节**删除**（不是留着不用）。"""
        from app.modules.evaluation import golden_builder

        assert not hasattr(golden_builder, "confirm_for_scope")

    def test_build_and_save_takes_no_annotated_flag(self, world):
        """`annotated=` 参数随人工确认一并删除：金标集只有一种形态。"""
        import inspect

        from app.modules.evaluation import golden_builder

        params = inspect.signature(golden_builder.build_and_save).parameters
        assert "annotated" not in params, params


class TestEvaluationUnderNewSemantics:
    def test_support_is_proxy_not_measured(self, world, monkeypatch):
        """**保留的纪律**：AI 裁判给的 precision 是 proxy，**不许声称 measured**。"""
        from app.modules.evaluation import golden_builder, legacy as eval_legacy
        from app.modules.evaluation import service as eval_service

        scope = world["scope"]
        golden_builder.build_and_save(scope)

        payload = eval_legacy._input_for(scope)
        assert payload.golden is not None
        assert not hasattr(payload, "golden_is_tuning"), "该字段已随人工确认删除"

        # 无 LLM → AI 裁判不可用 → not_evaluated（**不是 0**），并给出说明性告警
        report = eval_service.compute(payload)
        precision = report.metric("support_precision")
        assert precision is not None
        assert precision.status in ("proxy", "not_evaluated"), precision.status
        assert precision.status != "measured", "AI 裁判结果不得声称是 measured"
        codes = [w.code for w in report.warnings]
        assert "golden_not_annotated" not in codes, "人工语义告警必须清零"
        assert "golden_ai_constructed" in codes, codes

    def test_judge_available_yields_ai_basis_score(self, world, monkeypatch):
        """AI 裁判有结论 → 主分可算且标明 `ai_generated`（这正是决策 3/4 要的效果）。"""
        from app.contracts.evaluation import AiJudgeResult
        from app.modules.evaluation import golden_builder, legacy as eval_legacy
        from app.modules.evaluation import service as eval_service

        scope = world["scope"]
        golden_builder.build_and_save(scope)
        payload = eval_legacy._input_for(scope)
        payload = payload.model_copy(update={"ai_judge": AiJudgeResult(
            matches=[], true_positive=0, total_predicted=0, total_golden=1,
            model="judge", digest="d", judge_version="v1",
        )})

        report = eval_service.compute(payload)
        precision = report.metric("support_precision")
        if precision is not None and precision.status == "proxy":
            # 主分若可算，来源必须写明；若核心指标仍缺样本则必须为 None（不许 0）
            if report.overall_score is not None:
                assert report.overall_score_basis == "ai_generated"
            else:
                assert any(w.code == "ai_overall_not_evaluated" for w in report.warnings)
        assert not any(w.code == "golden_not_annotated" for w in report.warnings)

    def test_missing_core_metric_never_zero(self, world):
        """**底线**：核心指标缺样本 → 主分为 None（不以 0 冒充）。"""
        from app.modules.evaluation import golden_builder, legacy as eval_legacy
        from app.modules.evaluation import service as eval_service

        scope = world["scope"]
        golden_builder.build_and_save(scope)
        report = eval_service.compute(eval_legacy._input_for(scope))
        if report.overall_score is None:
            assert report.overall_score_basis is None
            assert any(w.code == "ai_overall_not_evaluated" for w in report.warnings)
        else:
            assert report.overall_score_basis == "ai_generated"
