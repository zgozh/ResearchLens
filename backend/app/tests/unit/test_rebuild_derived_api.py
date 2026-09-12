"""``POST /papers/{id}/rebuild-derived``：让派生产物可被 API 重建（ADR-0043）。

为什么需要（ADR-0037）：``retrieval.index`` 与 ``graph.build`` 此前**只有脚本能调**。
实测 papers 1–3 的 ``chunks``/``chunk_vectors`` 全为 0（经 seed 路径入库、跳过了
pipeline 的 index 阶段）→ "证据问答"整块不可用，而**没有任何 API** 能补起来。
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


@pytest.fixture
def client_and_scope():
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate, SourceMetadata
    from app.main import app
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="重建派生", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("rebuild"), SourceMetadata(original_filename="r.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)

    # 放一个原文块，保证 index 有东西可分块。id 必须每个测试唯一（单测共用同一个库）。
    import uuid

    from app.core import db as db_mod
    from app.models.artifacts import BlockORM, PageORM

    page_id, block_id = f"pg-{uuid.uuid4().hex[:10]}", f"blk-{uuid.uuid4().hex[:10]}"
    with db_mod.SessionLocal() as db:
        db.add(PageORM(id=page_id, paper_id=paper.id, revision_id=revision.id,
                       pdf_page_index=0, width_pt=595.0, height_pt=842.0))
        db.add(BlockORM(id=block_id, paper_id=paper.id, revision_id=revision.id,
                        page_id=page_id, ordinal=0, kind="paragraph",
                        text="本文提出一种基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法。",
                        origin="source_extraction"))
        db.commit()
    return TestClient(app), scope


def _url(scope) -> str:
    """必须显式带 ``revision_id``：测试里的 revision 未发布，路径解析会得到空 scope。"""
    return f"/api/papers/{scope.paper_id}/rebuild-derived?revision_id={scope.revision_id}"


@pytest.fixture
def admin_env(monkeypatch):
    """把管理凭据置为一个已知值（本地默认无 token → 放行，测不出拒绝路径）。"""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.core.security.settings",
        SimpleNamespace(admin_token="unit-admin", public_deployment=False),
    )
    return {"x-admin-token": "unit-admin"}


class TestRebuildDerived:
    def test_requires_admin_token(self, client_and_scope, admin_env):
        """配了 ADMIN_TOKEN 时，写操作必须校验凭据（与 jobs cancel/retry 同级）。"""
        client, scope = client_and_scope
        resp = client.post(_url(scope), json={"index": True, "graph": True},
                           headers={"x-admin-token": "wrong-token"})
        assert resp.status_code == 403, f"错误凭据必须拒绝，实际 {resp.status_code}：{resp.text}"

    def test_rebuilds_index_and_graph(self, client_and_scope, admin_env):
        """默认范围（index + graph）必须真的重建，并返回可核对的计数。"""
        client, scope = client_and_scope
        resp = client.post(_url(scope), json={"index": True, "graph": True}, headers=admin_env)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["scope"]["revision_id"] == scope.revision_id
        assert body["index"]["chunk_count"] >= 1, f"分块必须产出：{body['index']}"
        assert "graph" in body and "nodes" in body["graph"]
        # 无 LLM 时向量为 0、状态降级为 lexical_only（诚实报告，不假装 ready）
        assert body["index"]["status"] in ("ready", "lexical_only")

    def test_structure_is_opt_in_because_it_costs_llm(self, client_and_scope, admin_env):
        """``structure`` 默认关闭：它要调 LLM，不能因为"重建"就悄悄花钱。"""
        client, scope = client_and_scope
        resp = client.post(_url(scope), json={"index": False, "graph": False, "scene": False},
                           headers=admin_env)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "structure" not in body, "structure 必须显式开启"
        assert "index" not in body and "graph" not in body and "scene" not in body

    def test_scene_rebuild_is_default_on_and_reports_counts(self, client_and_scope, admin_env):
        """分镜是确定性派生且不需要 LLM → 默认重建，并返回可核对的计数。"""
        client, scope = client_and_scope
        resp = client.post(_url(scope), json={"index": False, "graph": False}, headers=admin_env)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "scene" in body, f"分镜应默认重建：{body}"
        assert set(body["scene"]) >= {"scenes", "statement_ids", "warnings"}

    def test_is_idempotent(self, client_and_scope, admin_env):
        """重复调用不得产生重复分块（index 按 content_hash 去重）。"""
        client, scope = client_and_scope
        first = client.post(_url(scope), json={"index": True, "graph": False},
                            headers=admin_env).json()
        second = client.post(_url(scope), json={"index": True, "graph": False},
                             headers=admin_env).json()

        assert first["index"]["chunk_count"] == second["index"]["chunk_count"], \
            f"重复重建不得新增分块：{first['index']} vs {second['index']}"
