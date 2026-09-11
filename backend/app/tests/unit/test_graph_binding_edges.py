"""M08 图谱边：``claim → media`` 的 illustrates 边必须真正连通（ADR-0020）。

真实缺陷：三篇真实论文的图谱都是 ``nodes=9/14/15, edges=0`` —— 图看着是散点，
不是"图谱"。根因有两层：

1. ``_build_edges`` 只消费 ``from_kind="claim"`` 的绑定，而 M04 的媒体绑定是
   ``from_kind="statement"``（更精确的出处）→ 绑定根本没被图看见；
2. 即使被看见，``build()`` **从不把 media 节点加入 ``node_ids``**，
   ``_target_node_id`` 对 ``to_kind="media"`` 返回 ``n:media:*`` 会以
   ``edge_endpoint_missing`` 被丢弃；且 ``NodeKind`` 字面量不含 ``media``。

硬约束不变：**无绑定即无边**，绝不统一补 supports；candidate 绑定不得升为 verified。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402


def _uniq(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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


def _seed_media(scope, *, kind="table", legacy_no=10, label="10", caption="表 10 PDM 与 F1-score 值"):
    from app.core import db as db_mod
    from app.models.artifacts import MediaORM

    media_id = _uniq("md")
    with db_mod.SessionLocal() as db:
        db.add(MediaORM(
            id=media_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            kind=kind, original_label=label, legacy_no=legacy_no, caption=caption,
            anchor_ids=[], original_asset_ids=[], thumbnail_asset_id=None,
            extracted=None, provenance={"representation": "mineru_crop"},
            excluded=False, exclusion_reason=None,
        ))
        db.commit()
    return media_id


def _seed_claim_with_statement(scope, *, claim_id, text, display_class="verified_fact",
                               status="verified"):
    from app.core import db as db_mod
    from app.models.evidence import ClaimRecordORM, StatementORM

    statement_id = _uniq("st")
    with db_mod.SessionLocal() as db:
        db.add(StatementORM(
            id=statement_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, text=text, kind="fact", citations=[], qualifiers=[],
            validation=None, evidence_ids=[], origin="generated",
            display_class=display_class, ordinal=0,
        ))
        db.add(ClaimRecordORM(
            id=_uniq("cr"), paper_id=scope.paper_id, revision_id=scope.revision_id,
            claim_id=claim_id, statement_id=statement_id, type="RESULT", status=status,
            rationale=f"理由 {claim_id}", evidence_ids=[], confidence=None,
            visibility="exhibit",
        ))
        db.commit()
    return statement_id


def _seed_binding(scope, *, from_kind, from_id, to_id, relation="illustrates",
                  state="verified", method="verified_claim_join"):
    from app.core import db as db_mod
    from app.models.evidence import BindingORM

    binding_id = _uniq("bg")
    with db_mod.SessionLocal() as db:
        db.add(BindingORM(
            id=binding_id, paper_id=scope.paper_id, revision_id=scope.revision_id,
            from_kind=from_kind, from_id=from_id, to_kind="media", to_id=to_id,
            relation=relation, method=method, validation_id=None, state=state,
            reason="测试", score=None,
        ))
        db.commit()
    return binding_id


@pytest.fixture
def world():
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="图谱边测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("graph"), SourceMetadata(original_filename="g.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {"paper": paper, "scope": Scope(paper_id=paper.id, revision_id=revision.id)}


class TestMediaEdges:
    def test_statement_level_media_binding_creates_edge(self, world):
        """M04 生成的 statement→media 绑定必须真正连成图边，且 media 节点入图。"""
        from app.modules import evidence as evidence_mod, graph as graph_mod

        scope = world["scope"]
        media_id = _seed_media(scope)
        _seed_claim_with_statement(
            scope, claim_id="c1", text="Table 10 reports PDM and F1-score values.")

        created = evidence_mod.bind_media_for_statements(
            scope, _statements(scope), new_ctx()
        )
        assert created, "前置条件：应已产生一条媒体绑定"

        graph = graph_mod.build(scope)

        assert graph.edges, "绑定存在时图谱必须连出边（不能是 nodes>0/edges=0 的散点）"
        edge = graph.edges[0]
        assert edge.relation == "illustrates"
        assert edge.status == "verified"

        node_ids = {n.id for n in graph.nodes}
        assert edge.source in node_ids, "边起点必须在本图内"
        assert edge.target in node_ids, "边终点必须在本图内"

        media_nodes = [n for n in graph.nodes if n.kind == "media"]
        assert media_nodes, "media 节点必须入图，否则边端点缺失"
        assert media_nodes[0].id == edge.target
        assert media_nodes[0].media_id == media_id

    def test_claim_level_binding_still_creates_edge(self, world):
        """兼容历史约定：from_kind=claim（公开 claim_id）的绑定同样成边。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        media_id = _seed_media(scope)
        _seed_claim_with_statement(scope, claim_id="c2", text="图 10 结果。")
        _seed_binding(scope, from_kind="claim", from_id="c2", to_id=media_id)

        graph = graph_mod.build(scope)

        assert len(graph.edges) == 1
        assert graph.edges[0].relation == "illustrates"
        assert graph.edges[0].status == "verified"

    def test_candidate_binding_yields_candidate_edge(self, world):
        """candidate 绑定不得升为 verified 边。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        media_id = _seed_media(scope)
        _seed_claim_with_statement(scope, claim_id="c3", text="图 10 结果。")
        _seed_binding(scope, from_kind="claim", from_id="c3", to_id=media_id,
                      state="candidate")

        graph = graph_mod.build(scope)

        assert len(graph.edges) == 1
        assert graph.edges[0].status == "candidate"

    def test_no_binding_no_edge(self, world):
        """无绑定即无边——绝不统一补 supports（图谱硬约束）。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        _seed_media(scope)
        _seed_claim_with_statement(scope, claim_id="c4", text="无绑定的断言。")

        graph = graph_mod.build(scope)

        assert graph.nodes, "节点仍应在（孤立节点）"
        assert graph.edges == [], "无绑定不得凭空连边"

    def test_all_edge_endpoints_exist(self, world):
        """所有边的端点都必须在本图内（契约 §5.4）。"""
        from app.modules import graph as graph_mod

        scope = world["scope"]
        media_id = _seed_media(scope)
        _seed_claim_with_statement(scope, claim_id="c5", text="图 10 结果。")
        _seed_binding(scope, from_kind="claim", from_id="c5", to_id=media_id)
        # 指向一个不存在的 media → 该边必须被丢弃而不是留下悬空端点
        _seed_binding(scope, from_kind="claim", from_id="c5", to_id="missing-media")

        graph = graph_mod.build(scope)

        node_ids = {n.id for n in graph.nodes}
        for edge in graph.edges:
            assert edge.source in node_ids and edge.target in node_ids


def _statements(scope):
    from app.modules import claims as claims_mod

    return claims_mod.get_verified_statements(scope)
