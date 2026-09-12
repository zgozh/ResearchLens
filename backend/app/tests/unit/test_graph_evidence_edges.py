"""研究图谱的 claim → evidence 边：由**已判定的证据行**投影（ADR-0037）。

真实缺陷（Postgres 实测）：``bindings`` 全库只有 6 行，且**全部**是
``statement → media / illustrates``；``claim → evidence`` 一条都没有。
于是研究图谱**没有任何 supports 边**：paper 1 = 8 节点 / 4 边（全是 illustrates），
paper 2 = 12 节点 / **0 边**（整张图是散点）。用户看到的正是"节点不全且连线不齐"。

而 gate 早已把判定写进了 ``evidence_records``（``claim_id`` + ``support_status``），
``claim_records.evidence_ids`` 也指得到这些证据——那是**已验证的证据**，不是编造。

因此这里把"已判定的证据行"投影为等价的 claim→evidence 绑定，**只补图谱边、不写库**：
- 只认 ``supports`` / ``contradicts``（``insufficient`` / ``unreviewed`` 一律不进图）；
- 已有显式绑定的 (claim, evidence) 不重复补；
- 推导发生时留 ``evidence_bindings_derived`` 告警，让"数据缺口"可见。
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


def _seed_evidence(scope, *, claim_id, support_status="supports", text="原文证据片段"):
    from app.core import db as db_mod
    from app.models.evidence import EvidenceRowORM

    evidence_id = _uniq("ev")
    with db_mod.SessionLocal() as db:
        db.add(EvidenceRowORM(
            id=evidence_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, source_document_id="", anchor_id=_uniq("anc"),
            source_page=2, source_region=[], source_text=text,
            quote_spans=[], media_ids=[], confidence=0.9,
            confidence_method="semantic", locator_status="exact",
            support_status=support_status, validation_id=None,
        ))
        db.commit()
    return evidence_id


def _seed_claim_with_statement(scope, *, claim_id, text, evidence_ids=(), status="verified"):
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM, StatementORM

    statement_id = _uniq("st")
    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=text, kind="fact", citations=[], qualifiers=[],
            validation=None, evidence_ids=list(evidence_ids), origin="generated",
            display_class="verified_fact", ordinal=0,
        ))
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type="RESULT", status=status,
            rationale="", evidence_ids=list(evidence_ids), confidence=None,
            visibility="exhibit",
        ))
        db.commit()
    return statement_id


def _seed_explicit_binding(scope, *, claim_id, evidence_id, relation="supports", state="verified"):
    from app.core import db as db_mod
    from app.models.evidence import BindingORM

    with db_mod.SessionLocal() as db:
        db.add(BindingORM(
            id=_uniq("bg"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            from_kind="claim", from_id=claim_id, to_kind="evidence", to_id=evidence_id,
            relation=relation, method="verified_claim_join", validation_id=None,
            state=state, reason="测试显式绑定", score=None,
        ))
        db.commit()


@pytest.fixture
def world():
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="图谱证据边", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("graph-ev"), SourceMetadata(original_filename="g.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {"paper": paper, "scope": Scope(paper_id=paper.id, revision_id=revision.id)}


class TestSupportsEdgesFromEvidenceRows:
    def test_supports_edge_created_without_binding_row(self, world):
        """**核心**：claim 有已判定的证据、但 bindings 表没有对应行时，仍必须有 supports 边。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        ev_id = _seed_evidence(scope, claim_id="haar_superior", support_status="supports")
        _seed_claim_with_statement(
            scope, claim_id="haar_superior", text="Haar 指标优于线性指标。",
            evidence_ids=[ev_id],
        )

        artifact = graph_mod.build(scope)

        supports = [e for e in artifact.edges if e.relation == "supports"]
        assert supports, (
            f"必须有 supports 边，否则图谱就是散点（实际边：{[(e.relation, e.status) for e in artifact.edges]}）"
        )
        assert any(e.target for e in supports)
        evidence_nodes = [n for n in artifact.nodes if n.kind == "evidence"]
        assert evidence_nodes, "证据节点必须入图，否则边没有落点"
        assert artifact.edges[0].status == "verified"

    def test_insufficient_evidence_is_not_linked(self, world):
        """``insufficient``/``unreviewed`` 的证据**不得**连边（不伪造 supports）。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        ev_id = _seed_evidence(scope, claim_id="weak_claim", support_status="insufficient")
        _seed_claim_with_statement(
            scope, claim_id="weak_claim", text="证据不足的结论。", evidence_ids=[ev_id],
        )

        artifact = graph_mod.build(scope)

        assert [e for e in artifact.edges if e.relation == "supports"] == []
        assert [n for n in artifact.nodes if n.kind == "evidence"] == []

    def test_contradicts_evidence_links_as_contradicts(self, world):
        """被证据反驳的断言要连 ``contradicts`` 而不是 ``supports``。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        ev_id = _seed_evidence(scope, claim_id="wrong_claim", support_status="contradicts")
        _seed_claim_with_statement(
            scope, claim_id="wrong_claim", text="被反驳的结论。", evidence_ids=[ev_id],
        )

        artifact = graph_mod.build(scope)

        assert [e.relation for e in artifact.edges] == ["contradicts"]

    def test_explicit_binding_is_not_duplicated(self, world):
        """已有显式绑定时不得再补一条等价边（边必须唯一）。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        ev_id = _seed_evidence(scope, claim_id="dup_claim", support_status="supports")
        _seed_claim_with_statement(
            scope, claim_id="dup_claim", text="已有显式绑定的结论。", evidence_ids=[ev_id],
        )
        _seed_explicit_binding(scope, claim_id="dup_claim", evidence_id=ev_id)

        artifact = graph_mod.build(scope)

        keys = [(e.source, e.target, e.relation) for e in artifact.edges]
        assert len(keys) == len(set(keys)), f"不得出现重复边：{keys}"
        assert len(keys) == 1

    def test_derivation_is_reported_as_warning(self, world):
        """推导必须留告警——数据缺口要可见，不能悄悄补上。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        ev_id = _seed_evidence(scope, claim_id="warn_claim", support_status="supports")
        _seed_claim_with_statement(
            scope, claim_id="warn_claim", text="需要推导绑定的结论。", evidence_ids=[ev_id],
        )

        artifact = graph_mod.build(scope)

        codes = [w.code for w in artifact.warnings]
        assert "evidence_bindings_derived" in codes, codes
        assert "isolated_claim" not in codes, "有证据的断言不该被报成孤立节点"
