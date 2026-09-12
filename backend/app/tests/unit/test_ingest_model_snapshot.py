"""导入的 revision **必须登记模型快照**（ADR-0067）。

真实缺陷（用户实测"问了转圈后没反应"的根因之一）：网址/上传导入走
``pipeline.ingest``，而它建 revision 时**没传 ctx** → ``create_revision`` 于是不登记
``model_snapshots`` 行、``revision.model_snapshot_id`` 为空 →
``snapshot_for_revision`` 回退到**没有 id** 的运行时快照 →
``qa._snapshot_id(ctx)`` 恒为 None → 下游一律按"无模型"处理：
问答退化成抽取式、**通用回答永远返回 None**（于是界面转圈后什么都没有）。

实测证据：paper 1–3（早期 seed）snapshot=<uuid>；paper 7/9/10（网址/上传导入）snapshot=None。
"""
from __future__ import annotations

import os

os.environ["LLM_API_KEY"] = "test-key-for-snapshot"

from app.contracts.common import Scope  # noqa: E402


class TestIngestCtxCarriesSnapshot:
    def test_ingest_ctx_has_model_snapshot(self):
        """建 revision 用的 ctx 必须带模型快照，否则下游当"无模型"。"""
        from app.modules.pipeline import ingest as ingest_mod

        ctx = ingest_mod._ingest_ctx(1)
        assert ctx is not None
        assert getattr(ctx, "model_snapshot", None) is not None, \
            "_ingest_ctx 没带模型快照 → revision 不会登记 snapshot_id"

    def test_revision_created_by_ingest_records_snapshot(self):
        """端到端一层：用该 ctx 建的 revision 必须指向已登记的 snapshot 行。"""
        from app.contracts.documents import PaperCreate, SourceMetadata
        from app.core.db import SessionLocal
        from app.models.source import RevisionORM
        from app.modules import papers as papers_mod
        from app.modules.pipeline import ingest as ingest_mod

        paper = papers_mod.create_paper(
            PaperCreate(title="快照登记测试", source_mode="upload",
                        provenance_class="source_document")
        )
        source = papers_mod.store_source(
            paper.id, b"%PDF-1.4\n%%EOF\n", SourceMetadata(original_filename="s.pdf")
        )
        revision = papers_mod.create_revision(
            paper.id, source.id, "source", ingest_mod._ingest_ctx(paper.id)
        )
        with SessionLocal() as db:
            row = db.get(RevisionORM, revision.id)
        assert row is not None and row.model_snapshot_id, \
            "导入的 revision 必须登记 model_snapshot_id（否则问答退化成'无模型'）"
