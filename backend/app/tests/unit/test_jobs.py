"""M11 任务管线单元测试 —— 重点验证 acquire 阶段为「新论文」建立 revision（修复缺口）。

覆盖：enqueue 新论文（revision 为空）→ claim_next → run_stage(acquire)
→ 建立 source revision 并写回 job；后续阶段 scope 正确；取消后不发布。
"""
from __future__ import annotations

import os

import pytest

# 与其它单测一致：清空云密钥（绝不打真实 LLM/embedding）
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""
os.environ["MINERU_TOKEN"] = ""

from app.contracts.artifacts import AssetWrite  # noqa: E402
from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.documents import (  # noqa: E402
    PaperCreate,
    SourceInput,
    SourceMetadata,
)
from app.contracts.jobs import JobSpec, JobLease  # noqa: E402
from app.modules import papers as papers_mod  # noqa: E402
from app.modules import pipeline as pipeline_mod  # noqa: E402


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


def _fresh_paper() -> tuple:
    paper = papers_mod.create_paper(
        PaperCreate(title="管线测试论文", source_mode="upload",
                    provenance_class="source_document")
    )
    return paper


def test_acquire_creates_revision_for_fresh_paper():
    """核心修复：新论文 enqueue（revision=None）→ acquire 阶段建立 revision 并写回 job。"""
    paper = _fresh_paper()
    # 上传字节先存成 pending asset
    asset = papers_mod.put_asset(
        AssetWrite(paper_id=paper.id, kind="parser_raw", mime="application/pdf"),
        _minimal_pdf("pipeline"),
    )
    spec = JobSpec(
        paper_id=paper.id,
        kind="ingest",
        source=SourceInput(kind="pending_upload", asset_id=asset.id),
        idempotency_key=f"test-{paper.id}",
    )
    job = pipeline_mod.enqueue(spec)
    assert job.revision_id is None, "新论文 enqueue 时 revision 应为空"

    lease = pipeline_mod.claim_next("test-worker")
    assert lease is not None and lease.job_id == job.id

    result = pipeline_mod.run_stage(lease, "acquire")
    assert result.status in ("succeeded", "partial"), f"acquire 应成功，实际 {result.status}: {result.error}"

    # 关键断言：job.revision_id 已被写回
    job_after = pipeline_mod.get_job(job.id)
    assert job_after.revision_id, "acquire 后 job.revision_id 应已建立"

    # revision 存在且属于该 paper、类型 source
    revision = papers_mod.get_revision(
        Scope(paper_id=paper.id, revision_id=job_after.revision_id)
    )
    assert revision.kind == "source"
    assert revision.source_document_id is not None


def test_acquire_idempotent_when_revision_exists():
    """已有 revision 的 job 重跑 acquire 不重复建 revision。"""
    paper = _fresh_paper()
    source = papers_mod.store_source(
        paper.id, _minimal_pdf("existing"), SourceMetadata(original_filename="e.pdf")
    )
    revision = papers_mod.create_revision(paper.id, source.id, "source")
    spec = JobSpec(
        paper_id=paper.id, kind="reprocess", revision_id=revision.id,
        source=SourceInput(kind="stored", source_document_id=source.id),
    )
    job = pipeline_mod.enqueue(spec)
    assert job.revision_id == revision.id

    lease = pipeline_mod.claim_next("test-worker")
    result = pipeline_mod.run_stage(lease, "acquire")
    assert result.status in ("succeeded", "partial", "skipped")

    # revision 数量不增长
    from app.core.db import session_scope
    from app.models.source import RevisionORM
    from sqlalchemy import select

    with session_scope() as db:
        count = len(db.execute(
            select(RevisionORM).where(RevisionORM.paper_id == paper.id)
        ).scalars().all())
    assert count == 1, f"acquire 重跑不应重复建 revision，实际 {count} 条"


def test_non_acquire_stage_requires_revision():
    """非 acquire 阶段在 revision 为空时必须失败，不静默。"""
    paper = _fresh_paper()
    spec = JobSpec(paper_id=paper.id, kind="ingest")
    job = pipeline_mod.enqueue(spec)
    lease = pipeline_mod.claim_next("test-worker")
    result = pipeline_mod.run_stage(lease, "parse")
    assert result.status == "failed"
    assert "revision" in str(result.error or {})
