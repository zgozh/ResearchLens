"""契约测试：canonical 资源接口（§5.12）—— manifest / document / pages / media /
statements / exhibits / evidence-export 的核心路径与错误码。

隔离策略继承 ``unit/conftest.py``；用 ``world`` 造 paper+source+revision。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""
os.environ["MINERU_TOKEN"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.contracts.artifacts import AssetWrite  # noqa: E402
from app.contracts.documents import PaperCreate, SourceMetadata  # noqa: E402
from app.modules import papers as papers_mod  # noqa: E402
from app.main import app  # noqa: E402


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
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    return bytes(out)


@pytest.fixture(scope="module")
def client(_shared_engine):
    return TestClient(app)  # 不进入 lifespan（conftest 已 create_all）


@pytest.fixture(scope="module")
def world():
    import io
    from app.contracts.common import Scope

    paper = papers_mod.create_paper(
        PaperCreate(title="canonical 测试", source_mode="upload",
                    provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, io.BytesIO(_minimal_pdf("canonical")),
        SourceMetadata(original_filename="c.pdf"),
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    # 设 readable 指针，使 _resolve_scope 能解析到 revision（否则 staging 状态解析不到）
    papers_mod.set_readable(Scope(paper_id=paper.id, revision_id=revision.id))
    return {"paper": paper, "source": source, "revision": revision}


def test_manifest_no_revision(client):
    """无 revision 的论文 manifest 返回 200，revision/source 为 null。"""
    p = papers_mod.create_paper(PaperCreate(title="空论文", source_mode="upload",
                                            provenance_class="source_document"))
    r = client.get(f"/api/papers/{p.id}/manifest")
    assert r.status_code == 200
    body = r.json()
    assert body["revision"] is None
    assert body["source"] is None
    assert body["page_count"] == 0
    assert "paper" in body and "capabilities" in body


def test_manifest_with_revision(client, world):
    r = client.get(f"/api/papers/{world['paper'].id}/manifest")
    assert r.status_code == 200
    body = r.json()
    assert body["revision"] is not None
    assert body["source"] is not None
    assert body["source"]["sha256"] == world["source"].sha256


def test_document_streams_pdf(client, world):
    r = client.get(f"/api/papers/{world['paper'].id}/document")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.headers.get("etag") == f'"{world["source"].sha256}"'
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.content[:5] == b"%PDF-"


def test_document_range_206(client, world):
    r = client.get(f"/api/papers/{world['paper'].id}/document",
                   headers={"Range": "bytes=0-10"})
    assert r.status_code == 206
    assert "content-range" in r.headers


def test_pages_and_media(client, world):
    assert client.get(f"/api/papers/{world['paper'].id}/pages").status_code == 200
    assert client.get(f"/api/papers/{world['paper'].id}/media").status_code == 200
    assert client.get(f"/api/papers/{world['paper'].id}/statements").status_code == 200


def test_exhibits_requires_revision(client):
    p = papers_mod.create_paper(PaperCreate(title="无 revision", source_mode="upload",
                                            provenance_class="source_document"))
    r = client.get(f"/api/papers/{p.id}/exhibits")
    assert r.status_code == 409  # 尚无可读 revision


def test_missing_paper_404(client):
    assert client.get("/api/papers/999999/manifest").status_code == 404
    assert client.get("/api/papers/999999/document").status_code == 404


def test_manifest_tolerates_legacy_method_steps_without_id(client):
    """回归：旧库 method_steps 没有 id 时，manifest 必须 200 而非 500。

    真实缺陷背景（Postgres 实测发现，规格 §5.11 明确禁止）：
    历史真实论文的 ``method_steps`` 是 ``{"label","phase","detail","color"}``，
    **无 ``id``**；而契约 ``LegacyMethodStep.id`` 必填 str。
    直接透传会让 pydantic 校验失败 → 整个 manifest 500，
    即"以新 DTO 验证导致整个旧详情 500"。本测试锁住容错投影。
    """
    import json
    from app.core.db import session_scope
    from app.models.models import Paper

    paper = papers_mod.create_paper(
        PaperCreate(title="旧数据容错", source_mode="upload",
                    provenance_class="source_document")
    )
    # 模拟旧库形态：无 id、figure_ref 为字符串、混入非 dict 脏项
    legacy_steps = [
        {"label": "第一步", "phase": "encoder", "detail": "细节", "color": "2E8B57"},
        {"id": "keep-me", "label": "第二步", "figure_ref": "3"},
        {"label": "第三步", "phase": 1},
        "not-a-dict",
    ]
    with session_scope() as db:
        row = db.get(Paper, paper.id)
        row.method_steps = legacy_steps

    r = client.get(f"/api/papers/{paper.id}/manifest")
    assert r.status_code == 200, r.text            # 修复前这里是 500
    assert "paper" in r.json()

    # canonical 侧：get_metadata 的容错投影（补 id、收敛脏类型）
    from app.modules import papers as papers_mod2
    meta = papers_mod2.get_metadata(paper.id)
    steps = [s.model_dump() for s in meta.method_steps]
    assert len(steps) == 4                         # §5.11：不改变旧响应条目数
    assert steps[0]["id"] == "legacy-step-0"       # 缺失 id 补稳定占位
    assert steps[0]["label"] == "第一步"
    assert steps[1]["id"] == "keep-me"             # 已有 id 不被覆盖
    assert steps[1]["figure_ref"] is None          # 字符串 figure_ref 不猜数字
    assert steps[2]["id"] == "legacy-step-2"
    assert steps[3]["label"] == "not-a-dict"       # 非 dict 降级为最小结构

    # 旧路由侧：§5.11 要求保留旧有效值（旧响应本就无 id，不能强行注入）
    detail = client.get(f"/api/papers/{paper.id}")
    assert detail.status_code == 200
    legacy_steps = detail.json()["method_steps"]
    assert len(legacy_steps) == 4
    assert legacy_steps[0]["label"] == "第一步"



def test_capability_claims_ready_when_list_nonempty(client):
    """回归：``capabilities.claims`` 必须反映真实 claim 数。

    真实缺陷背景（Postgres 实测）：``_capabilities`` 只探测
    ``.items/.nodes/.scenes/.metrics``，而 ``claims_mod.list_claims`` 返回的是
    **普通 list**（没有 ``.items`` 属性）→ 永远判为 pending。于是即便库里已有
    30 条 claim，manifest 仍报 ``capabilities.claims=pending``，前端据此认为
    「本文无断言」而不渲染断言视图。
    """
    import io

    from app.contracts.common import Scope, new_ctx
    from app.contracts.evidence import StatementDraft
    from app.modules import claims as claims_mod

    paper = papers_mod.create_paper(PaperCreate(
        title="capability claims 测试", source_mode="upload",
        provenance_class="source_document",
    ))
    source = papers_mod.store_source(
        paper.id, io.BytesIO(_minimal_pdf("cap")),
        SourceMetadata(original_filename="cap.pdf"),
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    scope = Scope(paper_id=paper.id, revision_id=revision.id)
    papers_mod.set_readable(scope)

    # 先确认空库时是 pending（探测器本身没坏）
    body = client.get(f"/api/papers/{paper.id}/manifest").json()
    caps = {c["name"]: c["state"] for c in body["capabilities"]}
    assert caps["claims"] == "pending"

    # 注册一条**展项可见**的陈述（register 只建身份，不需要 LLM）
    claim = claims_mod.register_statement(
        StatementDraft(
            scope=scope, id="stmt-cap-1", claim_id="cap_one",
            text="本文方法在 ImageNet 上达到 91.2% 的准确率。",
        ),
        visibility="exhibit", ctx=new_ctx(scope),
    )
    assert claim.claim_id == "cap_one"

    body = client.get(f"/api/papers/{paper.id}/manifest").json()
    caps = {c["name"]: c["state"] for c in body["capabilities"]}
    assert caps["claims"] == "ready", (
        "有 claim 时必须报 ready——旧实现只探测 .items，list 永远 pending"
    )
