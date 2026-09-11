"""M08 graph 单元测试（REFACTOR_SPEC §6.10「单元测试」要点）。

覆盖：缺端点、跨 scope 边、重复 ID、**无证据断言不得连 supports**、矛盾证据。

全部使用临时 sqlite，绝不触碰 data/researchlens.db。
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
from app.contracts.evidence import ClaimRecord  # noqa: E402


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


def _seed_claim_row(scope, *, claim_id, statement_id, status="unverified",
                    evidence_ids=(), type_="RESULT"):
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM

    with db_mod.SessionLocal() as db:
        db.add(ClaimRecordORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type=type_, status=status,
            rationale=f"理由 {claim_id}", evidence_ids=list(evidence_ids),
            confidence=None, visibility="exhibit",
        ))
        db.commit()


def _uniq(prefix: str) -> str:
    """测试内 ID 必须全局唯一：PK 是全局的，复用会撞上前一个测试留下的行。"""
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _seed_evidence(scope, *, evidence_id=None, anchor_id="", support="supports"):
    from app.core import db as db_mod
    from app.models.evidence import EvidenceRowORM

    eid = evidence_id or _uniq(f"ev-{scope.revision_id[:8]}")
    with db_mod.SessionLocal() as db:
        db.add(EvidenceRowORM(
            id=eid, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id="", source_document_id="", anchor_id=anchor_id,
            source_page=1, source_region=[], source_text="原文片段",
            quote_spans=[], media_ids=[], confidence=0.9,
            confidence_method="rule", locator_status="exact",
            support_status=support, validation_id=None,
        ))
        db.commit()
    return eid


def _seed_binding(scope, *, binding_id=None, from_kind, from_id, to_kind, to_id,
                  relation="supports", state="verified"):
    from app.core import db as db_mod
    from app.models.evidence import BindingORM

    bid = binding_id or _uniq(f"bd-{scope.revision_id[:8]}")
    with db_mod.SessionLocal() as db:
        db.add(BindingORM(
            id=bid, paper_id=scope.paper_id, revision_id=scope.revision_id,
            from_kind=from_kind, from_id=from_id, to_kind=to_kind, to_id=to_id,
            relation=relation, method="verified_claim_join", validation_id=None,
            state=state, reason="测试", score=None,
        ))
        db.commit()
    return bid


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="图谱测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("graph"), SourceMetadata(original_filename="g.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "source": source, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


def _claim(scope, claim_id, *, status="verified", evidence_ids=(), type_="RESULT"):
    return ClaimRecord(
        scope=scope, id=f"stmt-{claim_id}", claim_id=claim_id,
        statement_id=f"stmt-{claim_id}", type=type_, status=status,
        rationale=f"理由 {claim_id}", evidence_ids=list(evidence_ids),
        confidence=None, visibility="exhibit",
    )


# =============================================================== 核心红线


class TestNoSupportsWithoutEvidence:
    def test_unsupported_claim_has_no_supports_edge(self, world):
        """**无证据断言不得连 supports 边**——必须是孤立 unverified 节点。"""
        from app.modules import graph

        scope = world["scope"]
        artifact = graph.build(scope, [_claim(scope, "c_noev", status="unverified")])

        assert artifact.nodes, "应有节点"
        node = next(n for n in artifact.nodes if n.claim_id == "c_noev")
        assert node.status == "unverified"
        assert all(e.source != node.id for e in artifact.edges), \
            "无证据节点不得有任何出边"

    def test_unverified_claim_never_upgraded(self, world):
        from app.modules import graph

        scope = world["scope"]
        artifact = graph.build(scope, [_claim(scope, "c1", status="unverified")])
        node = next(n for n in artifact.nodes if n.claim_id == "c1")
        assert node.status == "unverified"

    def test_verified_claim_with_evidence_gets_edge(self, world):
        """有验证通过的证据时，才产出 verified supports 边。"""
        from app.modules import graph

        scope = world["scope"]
        eid = _seed_evidence(scope)
        _seed_binding(scope, from_kind="claim", from_id="c1",
                      to_kind="evidence", to_id=eid, relation="supports",
                      state="verified")
        artifact = graph.build(scope, [_claim(scope, "c1", status="verified",
                                             evidence_ids=[eid])])

        edge = next((e for e in artifact.edges if e.relation == "supports"), None)
        assert edge is not None, "已验证证据应产生 supports 边"
        assert edge.status == "verified"

    def test_candidate_binding_does_not_become_verified_edge(self, world):
        """candidate 绑定不得升为 verified 边。"""
        from app.modules import graph

        scope = world["scope"]
        eid = _seed_evidence(scope)
        _seed_binding(scope, from_kind="claim", from_id="c2",
                      to_kind="evidence", to_id=eid, relation="supports",
                      state="candidate")
        artifact = graph.build(scope, [_claim(scope, "c2", status="verified",
                                             evidence_ids=[eid])])
        edge = next((e for e in artifact.edges if e.relation == "supports"), None)
        assert edge is not None
        assert edge.status == "candidate", "candidate 绑定必须保持 candidate"


# =============================================================== 矛盾证据


class TestContradiction:
    def test_contradicts_edge_preserved(self, world):
        """矛盾证据连 contradicts 边，且节点状态保留 contested。"""
        from app.modules import graph

        scope = world["scope"]
        eid = _seed_evidence(scope, support="contradicts")
        _seed_binding(scope, from_kind="claim", from_id="cc",
                      to_kind="evidence", to_id=eid, relation="contradicts",
                      state="verified")
        artifact = graph.build(scope, [_claim(scope, "cc", status="contested",
                                              evidence_ids=[eid])])
        edge = next((e for e in artifact.edges if e.relation == "contradicts"), None)
        assert edge is not None
        node = next(n for n in artifact.nodes if n.claim_id == "cc")
        assert node.status == "contested"


# =============================================================== 端点 / 跨 scope


class TestEndpoints:
    def test_missing_endpoint_edge_skipped(self, world):
        """绑定目标不在本图内 → 跳过该边 + warning。"""
        from app.modules import graph

        scope = world["scope"]
        _seed_binding(scope, from_kind="claim", from_id="cm",
                      to_kind="evidence", to_id="no-such-evidence",
                      relation="supports", state="verified")
        artifact = graph.build(scope, [_claim(scope, "cm", status="verified")])
        assert artifact.edges == []

    def test_cross_scope_binding_excluded(self, world):
        """跨 scope 的证据不得进入本图（同图同 scope 约束）。"""
        from app.contracts.documents import PaperCreate
        from app.modules import graph
        from app.modules import papers as papers_mod

        scope = world["scope"]
        # 另一篇论文的证据行
        other = papers_mod.create_paper(
            PaperCreate(title="另一篇", source_mode="upload",
                        provenance_class="source_document")
        )
        other_source = papers_mod.store_source(
            other.id, _minimal_pdf("other"), SourceMetadata(original_filename="o.pdf")
        )
        other_rev = papers_mod.create_revision(other.id, other_source.id, "source")
        other_scope = Scope(paper_id=other.id, revision_id=other_rev.id)
        other_eid = _seed_evidence(other_scope)

        _seed_binding(scope, from_kind="claim", from_id="cx",
                      to_kind="evidence", to_id=other_eid, relation="supports",
                      state="verified")
        artifact = graph.build(scope, [_claim(scope, "cx", status="verified")])
        assert all(e.source != "n:claim:cx" for e in artifact.edges), \
            "跨 revision 的目标不得连边"

    def test_edges_reference_nodes_in_same_graph(self, world):
        from app.modules import graph

        scope = world["scope"]
        eid = _seed_evidence(scope)
        _seed_binding(scope, from_kind="claim", from_id="cxs",
                      to_kind="evidence", to_id=eid, relation="supports",
                      state="verified")
        artifact = graph.build(scope, [_claim(scope, "cxs", status="verified")])
        node_ids = {n.id for n in artifact.nodes}
        for edge in artifact.edges:
            assert edge.source in node_ids
            assert edge.target in node_ids


# =============================================================== 重复 / 稳定性


class TestStability:
    def test_duplicate_claim_id_collapsed(self, world):
        """重复 claim_id → 折叠为单一节点 + warning。"""
        from app.modules import graph

        scope = world["scope"]
        artifact = graph.build(scope, [
            _claim(scope, "dup", status="unverified"),
            _claim(scope, "dup", status="unverified"),
        ])
        ids = [n.id for n in artifact.nodes]
        assert ids.count("n:claim:dup") == 1

    def test_node_ids_stable_across_builds(self, world):
        """同输入两次构建 → 节点/边 ID 完全一致。"""
        from app.modules import graph

        scope = world["scope"]
        claims = [_claim(scope, "s1", status="unverified"),
                  _claim(scope, "s2", status="verified")]
        a = graph.build(scope, claims)
        b = graph.build(scope, claims)
        assert [n.id for n in a.nodes] == [n.id for n in b.nodes]
        assert [e.id for e in a.edges] == [e.id for e in b.edges]


# =============================================================== GET 只读


class TestGet:
    def test_get_without_build_returns_empty_graph(self, world):
        """无持久化图 → 空图，不抛异常、不写库。"""
        from app.modules import graph

        artifact = graph.get(world["scope"])
        assert artifact.nodes == []
        assert artifact.edges == []

    def test_get_after_build_returns_snapshot(self, world):
        from app.modules import graph

        scope = world["scope"]
        graph.build(scope, [_claim(scope, "g1", status="unverified")])
        loaded = graph.get(scope)
        assert any(n.claim_id == "g1" for n in loaded.nodes)

    def test_get_does_not_write(self, world):
        """GET 不得写库：调用前后行数不变。"""
        from app.core import db as db_mod
        from app.models.artifacts import ArtifactBlobORM
        from app.modules import graph

        scope = world["scope"]
        graph.build(scope, [_claim(scope, "ro", status="unverified")])

        with db_mod.SessionLocal() as db:
            before = db.query(ArtifactBlobORM).filter(
                ArtifactBlobORM.revision_id == scope.revision_id).count()
        graph.get(scope)
        graph.get(scope)
        with db_mod.SessionLocal() as db:
            after = db.query(ArtifactBlobORM).filter(
                ArtifactBlobORM.revision_id == scope.revision_id).count()
        assert before == after

    def test_unknown_paper_raises_not_found(self):
        from app.core.errors import DomainError
        from app.modules import graph

        bad = Scope(paper_id=999999, revision_id="missing")
        with pytest.raises(DomainError):
            graph.get(bad)


# =============================================================== 兼容层


class TestLegacyCompat:
    def test_get_graph_returns_nodes_edges(self, world):
        """旧签名 ``get_graph(db, paper_id)`` 可用且形状兼容。"""
        from app.core import db as db_mod
        from app.modules import graph

        scope = world["scope"]
        graph.build(scope, [_claim(scope, "lg", status="unverified")])
        with db_mod.SessionLocal() as db:
            payload = graph.get_graph(db, world["paper"].id)
        assert "nodes" in payload and "edges" in payload
        assert any(n["id"] == "n:claim:lg" for n in payload["nodes"])

    def test_get_graph_unknown_paper_returns_empty(self):
        from app.core import db as db_mod
        from app.modules import graph

        with db_mod.SessionLocal() as db:
            payload = graph.get_graph(db, 999999)
        assert payload == {"nodes": [], "edges": []}
