"""评测输入装配 + Golden Set 端点（ADR-0046）。

真实缺陷：``evaluation.legacy._input_for()`` 只组装 ``statements`` + ``answers``，
既不传 ``golden`` 也不传 ``navigation_checks`` → 综合评分的 4 个核心指标里
``support_precision`` / ``unanswerable_refusal_rate`` / ``anchor_page_accuracy``
**永远没有分母**，``overall_score`` 只能是 null。所以"补 golden 数据"这件事
与"装配输入"必须一起做，否则建了真值也不生效。
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

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

    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def world():
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.main import app
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="评测输入", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("eval"), SourceMetadata(original_filename="e.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    from app.core import db as db_mod
    from app.models.artifacts import AnchorORM, BlockORM, PageORM

    page_id, block_id, anchor_id = _uniq("pg"), _uniq("blk"), _uniq("anc")
    with db_mod.SessionLocal() as db:
        db.add(PageORM(id=page_id, paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=2, width_pt=595.0, height_pt=842.0))
        db.add(BlockORM(id=block_id, paper_id=paper.id, revision_id=revision.id,
                        page_id=page_id, ordinal=0, kind="paragraph",
                        text="本文提出一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法,"
                             "以高阶 Haar 小波变换建立像素关系,计算分解矩阵范数均值.",
                        origin="source_extraction"))
        # 锚点落在**同一页**（页对得上 → page_correct=True）
        db.add(AnchorORM(
            id=anchor_id, paper_id=paper.id, revision_id=revision.id,
            source_document_id="", precision="page",
            segments=[{"page_id": page_id, "pdf_page_index": 2, "page_label": None,
                       "rect": None, "quads": [], "block_ids": [block_id], "quote_spans": []}],
            transform=None, raw_ref=None,
        ))
        db.commit()
    return {"scope": scope, "block_id": block_id, "anchor_id": anchor_id,
            "client": TestClient(app)}


class TestNavigationChecksDerivation:
    def test_check_is_built_from_evidence_and_block_page(self, world):
        """证据锚点页 == 引用块所在页 → ``page_correct=True``（真值来自 parser）。"""
        from app.core import db as db_mod
        from app.models.evidence import EvidenceRowORM
        from app.modules.evaluation import legacy as eval_legacy

        scope = world["scope"]
        with db_mod.SessionLocal() as db:
            db.add(EvidenceRowORM(
                id=_uniq("ev"), paper_id=scope.paper_id, revision_id=scope.revision_id,
                claim_id="c1", source_document_id="", anchor_id=world["anchor_id"],
                source_page=3,
                source_region=[{"page_id": None, "pdf_page_index": 2, "page_label": None,
                                "rect": None, "quads": [],
                                "block_ids": [world["block_id"]], "quote_spans": []}],
                source_text="原文证据", quote_spans=[], media_ids=[], confidence=0.9,
                confidence_method="semantic", locator_status="exact",
                support_status="supports", validation_id=None,
            ))
            db.commit()

        checks = eval_legacy._navigation_checks(scope)

        assert checks, "有锚点+引用块的证据必须产生校验样本"
        assert checks[0].page_correct is True
        assert checks[0].region_iou is None, "块没有矩形就不该编 IoU"

    def test_mismatched_page_is_reported_as_incorrect(self, world):
        """锚点页与块页不一致时必须如实记 False（否则该指标没有意义）。"""
        from app.core import db as db_mod
        from app.models.artifacts import AnchorORM
        from app.models.evidence import EvidenceRowORM
        from app.modules.evaluation import legacy as eval_legacy

        scope = world["scope"]
        wrong_anchor = _uniq("anc")
        with db_mod.SessionLocal() as db:
            db.add(AnchorORM(
                id=wrong_anchor, paper_id=scope.paper_id, revision_id=scope.revision_id,
                source_document_id="", precision="page",
                segments=[{"page_id": None, "pdf_page_index": 9, "page_label": None,
                           "rect": None, "quads": [], "block_ids": [world["block_id"]],
                           "quote_spans": []}],
                transform=None, raw_ref=None,
            ))
            db.add(EvidenceRowORM(
                id=_uniq("ev"), paper_id=scope.paper_id, revision_id=scope.revision_id,
                claim_id="c2", source_document_id="", anchor_id=wrong_anchor, source_page=10,
                source_region=[{"page_id": None, "pdf_page_index": 9, "page_label": None,
                                "rect": None, "quads": [],
                                "block_ids": [world["block_id"]], "quote_spans": []}],
                source_text="原文证据", quote_spans=[], media_ids=[], confidence=0.9,
                confidence_method="semantic", locator_status="exact",
                support_status="supports", validation_id=None,
            ))
            db.commit()

        checks = [c for c in eval_legacy._navigation_checks(scope) if c.anchor_id == wrong_anchor]

        assert checks and checks[0].page_correct is False, "页不一致必须记 False"


class TestGoldenSetEndpoint:
    def test_builds_and_reports_counts(self, world, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            "app.core.security.settings",
            SimpleNamespace(admin_token="unit-admin", public_deployment=False),
        )
        scope = world["scope"]
        resp = world["client"].post(
            f"/api/papers/{scope.paper_id}/golden-set?revision_id={scope.revision_id}",
            headers={"x-admin-token": "unit-admin"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()["golden"]
        assert body["claims"] >= 1, f"必须从原文构造出 claim：{body}"
        assert body["unanswerable_questions"] >= 1, f"必须有不可答题做分母：{body}"
        assert body["anchors"] >= 1
        assert body["version"]

    def test_evaluation_input_picks_up_golden_and_checks(self, world, monkeypatch):
        """端到端：建完 golden 后，``_input_for`` 必须真的把它传给评测。"""
        from types import SimpleNamespace

        from app.modules.evaluation import golden_builder, legacy as eval_legacy

        monkeypatch.setattr(
            "app.core.security.settings",
            SimpleNamespace(admin_token="unit-admin", public_deployment=False),
        )
        scope = world["scope"]
        golden_builder.build_and_save(scope)

        payload = eval_legacy._input_for(scope)

        assert payload.golden is not None, "评测输入必须带上 golden（否则 precision 无分母）"
        assert payload.golden.id.startswith("golden-")
