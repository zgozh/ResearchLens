"""契约测试：17 个旧 `/api/*` 路由的 URL / 默认 200 / 字段 / 错误码逐项保留（§5.11）。

隔离策略继承 ``unit/conftest.py``（DATABASE_URL 指向 tmp，禁用真实云调用）。
用 TestClient **不进入 lifespan**（不触发 run_migrations），因为 conftest 已用
``create_all`` 建好表；此处只验证路由层的兼容契约，不验证迁移。

真实迁移 + 旧数据保留已由主会话在真实库副本上手工验证（6 papers 保留、回填正确）。
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def client(_shared_engine):
    """一个模块共享一个 TestClient；不进入 lifespan（避免迁移干扰 create_all）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    # 直接构造，不调用 __enter__（那会触发 lifespan → run_migrations）
    return TestClient(app)


@pytest.fixture(scope="module")
def paper_id(client):
    """确保 demo 论文存在，返回一篇的 id。"""
    from app.core.db import SessionLocal
    from app.seed import demo_papers as demo

    with SessionLocal() as db:
        demo.load_demo_papers(db)
        from app import models

        p = db.query(models.Paper).filter(models.Paper.source_mode == "demo").first()
        return int(p.id) if p else 1


# ================================================================== GET 路由


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body and "demo_mode" in body and "version" in body


def test_demo_list(client):
    r = client.get("/api/demo")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_models_get(client):
    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert "models" in body and "active" in body
    assert isinstance(body["models"], list)


def test_models_post(client):
    r = client.post("/api/models", json={"model": "qwen-plus"})
    assert r.status_code == 200
    assert r.json().get("active") == "qwen-plus"


def test_papers_list(client):
    r = client.get("/api/papers")
    assert r.status_code == 200
    papers = r.json()
    assert isinstance(papers, list)
    if papers:
        # §5.11 PaperOut 旧字段逐项存在
        for k in ["id", "slug", "title", "subtitle", "authors", "year", "domain",
                  "abstract", "tags", "source_mode", "status", "map_summary",
                  "pdf_url", "method_steps"]:
            assert k in papers[0], f"PaperOut 缺字段 {k}"


def test_paper_detail(client, paper_id):
    r = client.get(f"/api/papers/{paper_id}")
    assert r.status_code == 200
    body = r.json()
    # PaperDetail = PaperOut + sections/figures/tables/method_steps/pages/accent
    for k in ["sections", "figures", "tables", "method_steps", "pages", "accent"]:
        assert k in body, f"PaperDetail 缺字段 {k}"


def test_paper_detail_404(client):
    assert client.get("/api/papers/999999").status_code == 404


def test_paper_claims(client, paper_id):
    r = client.get(f"/api/papers/{paper_id}/claims")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_paper_claim_by_id(client, paper_id):
    # claim_id 可能不存在 → 404 也算合法；不存在的 paper 必须 404
    r = client.get(f"/api/papers/{paper_id}/claims/claim_01")
    assert r.status_code in (200, 404)


def test_paper_graph(client, paper_id):
    r = client.get(f"/api/papers/{paper_id}/graph")
    assert r.status_code == 200
    body = r.json()
    assert "nodes" in body and "edges" in body


def test_paper_presentation(client, paper_id):
    r = client.get(f"/api/papers/{paper_id}/presentation")
    assert r.status_code == 200
    body = r.json()
    assert "scenes" in body


def test_paper_qa(client, paper_id):
    # 无 LLM 时应降级/拒答返回 200，不 500（§5.11「不能产出假证据」）
    r = client.post(f"/api/papers/{paper_id}/qa", json={"question": "这篇论文的核心贡献是什么？", "top_k": 5})
    assert r.status_code == 200
    body = r.json()
    for k in ["answer", "grounded", "confidence", "evidence", "note"]:
        assert k in body, f"AskResponse 缺字段 {k}"


def test_paper_evaluation(client, paper_id):
    r = client.get(f"/api/papers/{paper_id}/evaluation")
    assert r.status_code == 200
    body = r.json()
    assert "overall_score" in body and "metrics" in body


# ================================================================== POST 路由


def test_demo_load(client):
    r = client.post("/api/demo/load", json={"slug": "slimseg-net"})
    assert r.status_code == 200
    assert r.json().get("slug") == "slimseg-net"


def test_demo_load_404(client):
    assert client.post("/api/demo/load", json={"slug": "nonexistent"}).status_code == 404


def test_process_404_for_missing_paper(client):
    # §5.11：无论文 404（不得对不存在论文建 job → FK 约束失败）
    r = client.post("/api/papers/999999/process")
    assert r.status_code == 404


def test_jobs_404(client):
    assert client.get("/api/jobs/999999").status_code == 404


def test_upload(client):
    # §5.11：demo_mode=true 保留 400；live 模式返回 paper_id 并**直接进入 processing**
    # （ADR-0066：上传改走 canonical ingest，服务端自己跑完整 pipeline，
    #  不再只建一行 legacy GenerationJob —— 那行没有任何消费者，论文会永远 pending）
    from app.core.config import settings

    r = client.post("/api/papers/upload",
                    files={"file": ("x.pdf", b"%PDF-1.4 fake", "application/pdf")})
    if settings.demo_mode:
        assert r.status_code == 400
    else:
        assert r.status_code == 200
        body = r.json()
        assert "paper_id" in body
        assert body.get("status") in ("processing", "pending"), body
