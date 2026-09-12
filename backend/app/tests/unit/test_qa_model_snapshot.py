"""QA 必须拿到 revision 固定的模型快照（ADR-0032）。

真实缺陷（Postgres + SSE 实测）：``POST /papers/{id}/qa/stream`` 恒返回
``meta/status/status/final`` 四个事件，**没有 citation/sentence**，
``answer.text.text = ""``、``mode = abstained`` —— 用户看到的就是"证据问答不能聊天"。

根因：``api/canonical.py`` 用 ``new_ctx(scope)`` 构造 CallContext，而 ``new_ctx``
的 ``snapshot`` 默认是 ``None``。于是：

- ``retrieval/vector.py`` → ``embedding_unavailable``（拿不到 embedding 模型名）；
- ``qa/service.py`` 因 ``not snapshot_id`` 直接判 ``llm_unavailable`` → 拒答。

而 revision 上明明已经 pin 了 ``model_snapshot_id``（实测 ``fd4c8b11…``）。
本文件锁定"快照必须从 revision 解析出来"这条契约。
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
        PaperCreate(title="QA 快照", source_mode="upload", provenance_class="source_document")
    )
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("qa"), SourceMetadata(original_filename="q.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    return {
        "paper": paper, "revision": revision,
        "scope": Scope(paper_id=paper.id, revision_id=revision.id),
    }


def _pin_snapshot(revision_id: str, *, chat_model: str = "qwen-plus",
                  embedding_model: str = "text-embedding-v3") -> str:
    """给 revision pin 一条模型快照（模拟 pipeline 的正常行为）。

    ``model_snapshots`` 有 ``(chat_model, embedding_model, capability_version)``
    唯一约束，且单测共用同一个临时库——所以已存在同身份快照时**复用**它。
    """
    from sqlalchemy import select

    from app.core import db as db_mod
    from app.models.source import ModelSnapshotORM, RevisionORM

    with db_mod.SessionLocal() as db:
        existing = db.execute(
            select(ModelSnapshotORM).where(
                ModelSnapshotORM.chat_model == chat_model,
                ModelSnapshotORM.embedding_model == embedding_model,
                ModelSnapshotORM.capability_version == "rl.capabilities/1",
            )
        ).scalars().first()
        if existing is not None:
            snap_id = existing.id
        else:
            snap = ModelSnapshotORM(
                id=f"snap-{revision_id[:12]}", provider="dashscope",
                base_url="https://example.invalid/v1",
                chat_model=chat_model, embedding_model=embedding_model,
                embedding_dimension=1024, capability_version="rl.capabilities/1",
                temperature=0.2,
            )
            db.add(snap)
            db.flush()
            snap_id = snap.id
        row = db.get(RevisionORM, revision_id)
        row.model_snapshot_id = snap_id
        db.commit()
    return snap_id


class TestSnapshotForRevision:
    def test_returns_pinned_snapshot(self, world):
        """revision pin 了快照时，必须返回**那一条**（不是当前运行时配置）。"""
        from app.modules import papers as papers_mod

        scope = world["scope"]
        snap_id = _pin_snapshot(scope.revision_id)

        snap = papers_mod.snapshot_for_revision(scope)

        assert snap is not None, "必须解析出快照，否则 QA 永远 llm_unavailable"
        assert snap.id == snap_id
        assert snap.chat_model == "qwen-plus"
        assert snap.embedding_model == "text-embedding-v3", \
            "embedding 模型名缺失会让检索报 embedding_unavailable"

    def test_falls_back_to_runtime_snapshot_when_not_pinned(self, world):
        """revision 未 pin 快照（历史数据）时退回运行时快照，而不是返回 None。"""
        from app.modules import papers as papers_mod

        snap = papers_mod.snapshot_for_revision(world["scope"])

        assert snap is not None, "没有 pin 也必须给一个可用快照，不能让问答直接降级"
        assert snap.chat_model, "运行时快照必须带 chat_model"

    def test_never_raises_on_bad_scope(self):
        """scope 非法时不得抛异常（否则路由 500）；返回 None 由调用方降级。"""
        from app.contracts.common import Scope
        from app.modules import papers as papers_mod

        snap = papers_mod.snapshot_for_revision(Scope(paper_id=0, revision_id=""))
        # 允许返回运行时快照或 None，但绝不允许抛异常
        assert snap is None or snap.chat_model

    def test_ctx_built_from_snapshot_reaches_qa(self, world):
        """端到端契约：``new_ctx(scope, snapshot=...)`` 的 ctx 必须带得到快照 id。

        这条同时锁住一个**真实事故**：``CallContext.model_snapshot`` 一度被声明为
        ``ModelSnapshotLike``，pydantic 会把完整快照**降级**成 Like 视图；而
        ``CompletionRequest.model_snapshot`` 要求完整 ``ModelSnapshot`` →
        ValidationError → ``qa/service._llm_draft`` 抛异常 → 降级"抽取式" →
        抽取为空 → **问答恒拒答**（用户看到空气泡）。所以这里必须断言
        ctx 里装的是**完整 ModelSnapshot**，并且能直接喂给 CompletionRequest。
        """
        from app.contracts.ai import CompletionRequest, ModelSnapshot
        from app.contracts.common import new_ctx
        from app.modules import papers as papers_mod
        from app.modules.qa.service import _snapshot_id

        scope = world["scope"]
        snap_id = _pin_snapshot(scope.revision_id)

        ctx = new_ctx(scope, snapshot=papers_mod.snapshot_for_revision(scope))

        assert ctx.model_snapshot is not None
        assert _snapshot_id(ctx) == snap_id, \
            "qa/service 取到的 snapshot_id 必须等于 revision pin 的那条"
        assert isinstance(ctx.model_snapshot, ModelSnapshot), \
            f"ctx 里必须是完整 ModelSnapshot，实际 {type(ctx.model_snapshot).__name__}"

        # 下游请求契约必须能直接接受它（这正是此前 500/拒答的触发点）
        request = CompletionRequest(model_snapshot=ctx.model_snapshot, messages=[])
        assert request.model_snapshot is not None
        assert request.model_snapshot.chat_model == ctx.model_snapshot.chat_model

    def test_dict_snapshot_is_normalized_to_model_snapshot(self, world):
        """传 dict 也必须归一化成完整 ModelSnapshot（否则又是同一类静默降级）。"""
        from app.contracts.ai import ModelSnapshot
        from app.contracts.common import new_ctx

        ctx = new_ctx(world["scope"], snapshot={"chat_model": "qwen-plus", "provider": "dashscope"})

        assert isinstance(ctx.model_snapshot, ModelSnapshot)
        assert ctx.model_snapshot.chat_model == "qwen-plus"
