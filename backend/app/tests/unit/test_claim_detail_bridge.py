"""旧端点 ``GET /papers/{id}/claims/{claim_id}`` 的 canonical 桥接（ADR-0031）。

真实缺陷（Postgres 实测）：``/api/papers/1/claims`` 能列出 5 条 canonical 断言，
但 ``/api/papers/1/claims/{claim_id}`` 对**同一批 claim_id 全部 404**。

根因：列表走的是 ``claims/legacy.py`` 的 canonical 桥接，详情却仍转发
``app.services.claims.get_claim``（只查旧 ``claims`` 表，真实论文那表是空的）。
``schemas/adapters.to_legacy_claim`` 早就写好了，只是没人调用它。

后果（用户可见）：研究图谱里点断言节点 → 详情面板调该端点 → 404 →
"该断言的证据"永远空白；前端还会提示"未绑定证据"。
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
        PaperCreate(title="断言详情桥接", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("detail"), SourceMetadata(original_filename="d.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


def _seed_claim(scope, *, claim_id, statement_text, rationale="", evidence_count=1,
                source_region=None):
    """写入一条 canonical 断言 + 陈述（+ 可选证据记录）。"""
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM, EvidenceRowORM, StatementORM

    statement_id = _uniq("stmt")
    evidence_ids = []
    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=statement_text, kind="fact",
            citations=[], qualifiers=[], validation=None, evidence_ids=[],
            origin="generated", display_class="verified_fact", ordinal=0,
        ))
        for i in range(evidence_count):
            evidence_id = _uniq("ev")
            evidence_ids.append(evidence_id)
            db.add(EvidenceRowORM(
                id=evidence_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
                claim_id=claim_id, source_document_id="", anchor_id="",
                source_page=1, source_region=list(source_region or []),
                source_text=f"证据原文 {i}",
                quote_spans=[], media_ids=[], confidence=0.9,
                confidence_method="semantic", locator_status="exact",
                support_status="supports", validation_id=None,
            ))
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type="RESULT", status="verified",
            rationale=rationale, evidence_ids=list(evidence_ids), confidence=None,
            visibility="exhibit",
        ))
        db.commit()
    return {"statement_id": statement_id, "evidence_ids": evidence_ids}


class TestCanonicalClaimDetail:
    def test_detail_is_found_for_canonical_claim(self, world):
        """canonical 断言必须能按 claim_id 取到详情，而不是 404。"""
        from app.core import db as db_mod
        from app.modules.claims import legacy as claims_legacy

        scope = world["scope"]
        _seed_claim(scope, claim_id="haar_superior", statement_text="Haar 指标优于线性指标。")

        with db_mod.SessionLocal() as db:
            out = claims_legacy.get_claim(db, scope.paper_id, "haar_superior")

        assert out is not None, "canonical 断言详情不得 404"
        assert out.claim_id == "haar_superior"
        assert out.statement == "Haar 指标优于线性指标。", \
            f"statement 必须来自 statements 表，实际 {out.statement!r}"

    def test_detail_carries_evidence_bodies(self, world):
        """详情必须带出证据正文，否则图谱详情面板"该断言的证据"仍是空的。"""
        from app.core import db as db_mod
        from app.modules.claims import legacy as claims_legacy

        scope = world["scope"]
        seeded = _seed_claim(scope, claim_id="with_evidence",
                             statement_text="结论成立。", evidence_count=2)

        with db_mod.SessionLocal() as db:
            out = claims_legacy.get_claim(db, scope.paper_id, "with_evidence")

        assert out is not None
        assert len(out.evidence) == 2, f"应带出 2 条证据，实际 {len(out.evidence)}"
        # 旧契约的 ``id`` 只接受 int，canonical 的字符串 id 落在 ``evidence_id``
        assert {e.evidence_id for e in out.evidence} == set(seeded["evidence_ids"])
        assert all((e.text or "").strip() for e in out.evidence), "证据正文不得为空"

    def test_unknown_claim_returns_none_not_exception(self, world):
        """未知 claim_id 返回 None（路由据此 404），不得抛异常变成 500。"""
        from app.core import db as db_mod
        from app.modules.claims import legacy as claims_legacy

        scope = world["scope"]
        _seed_claim(scope, claim_id="known", statement_text="已知。")

        with db_mod.SessionLocal() as db:
            assert claims_legacy.get_claim(db, scope.paper_id, "not-there") is None

    def test_evidence_with_real_source_region_does_not_500(self, world):
        """**回归**：证据带真实 ``source_region`` 时详情不得 500。

        真实缺陷（2026-09-12 实测端点 500）：
        ``adapters.to_legacy_evidence`` 读 ``source_region[0].block_id``，
        而 ``AnchorSegment`` 只有 ``block_ids``（列表）→
        ``AttributeError: 'AnchorSegment' object has no attribute 'block_id'``。
        这条路径此前因"详情恒 404"从未被执行，所以长期潜伏。
        """
        from app.core import db as db_mod
        from app.modules.claims import legacy as claims_legacy

        scope = world["scope"]
        # AnchorSegment 的真实形状：block_ids 是**列表**，没有 block_id
        _seed_claim(
            scope, claim_id="region_real", statement_text="带区域定位的结论。",
            source_region=[{
                "page_id": _uniq("pg"), "pdf_page_index": 2, "page_label": "2503",
                "rect": None, "quads": [], "block_ids": ["blk-real-1", "blk-real-2"],
                "quote_spans": [],
            }],
        )

        with db_mod.SessionLocal() as db:
            out = claims_legacy.get_claim(db, scope.paper_id, "region_real")

        assert out is not None, "带 source_region 的证据不得让详情失败"
        assert len(out.evidence) == 1
        assert out.evidence[0].region == "blk-real-1", \
            f"旧 region 字段应取首个 block_id，实际 {out.evidence[0].region!r}"
