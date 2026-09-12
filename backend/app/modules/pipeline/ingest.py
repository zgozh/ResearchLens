"""M11 — 旧 ingest 签名兼容适配（REFACTOR_SPEC §6.13 交付限制）。

旧调用方（``api/routes.py``、``seed_real``）仍在用：

    ingest_paper_from_pdf(db, data, url, title) -> paper_id

重构后**统一走数据库任务状态机**：本适配器创建稳定 paper_id + staging revision +
入队 ingest 任务，然后内联跑完（旧调用方期待同步拿到 paper_id 并随后可读）。

与旧实现的关键差异（有意修复，不保留旧缺陷）：
- **不再「同 slug 删除重建」**：paper_id 稳定，重导入复用同一论文；
- 解析走 M02（MinerU 优先、PyMuPDF 降级），不再用临时 pypdf 链路；
- 一个 paper_id 贯穿全程，恢复不靠删除论文。
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Scope, new_ctx
from app.contracts.documents import PaperCreate, SourceInput, SourceMetadata
from app.contracts.jobs import STAGE_ORDER, JobSpec
from app.core.db import session_scope
from app.core.errors import DomainError

log = logging.getLogger("researchlens.pipeline.ingest")

_TERMINAL = ("succeeded", "partial", "failed", "cancelled")


def _ingest_ctx(paper_id: int, revision_id: str = ""):
    """建 revision 用的 CallContext：**必须带运行时模型快照**（ADR-0067）。

    真实缺陷：``create_revision`` 只在 ``ctx.model_snapshot`` 非空时才登记
    ``model_snapshots`` 行并把 ``revision.model_snapshot_id`` 指向它。这里以前传 ``None``，
    于是**通过网址/上传导入的论文 revision 没有快照** → ``snapshot_for_revision`` 回退到
    运行时快照（**没有 id**）→ ``qa._snapshot_id(ctx)`` 为 None → 下游一律按"无模型"处理：
    问答退化成抽取式、**通用回答永远返回 None**（用户实测"问了转圈后没反应"）。
    """
    try:
        from app.modules.ai import capabilities as capabilities_mod

        snapshot = capabilities_mod.get_snapshot()
    except Exception:  # noqa: BLE001  拿不到快照不阻断 ingest（只是记录不到）
        snapshot = None
    return new_ctx(Scope(paper_id=paper_id, revision_id=revision_id), snapshot=snapshot)


def ingest_pdf_for_paper(
    paper_id: int,
    data: bytes,
    *,
    url: str = "",
    title: str = "",
) -> int:
    """为**已存在的 paper** 跑完整 ingest，返回 job_id（ADR-0066）。

    为什么需要（真实缺陷）：上传接口 ``POST /api/papers/upload`` 以前只写一行 **legacy**
    ``GenerationJob(status=pending)`` 就返回 —— 没有任何东西消费它，
    ``pipeline.run_pipeline`` 对这种"没有 revision/源"的论文**静默什么都不做**（实测直接调用
    返回 5 且论文状态一直是 pending）。而"粘贴网址"走的是 canonical ingest，所以那条链路是好的。
    这里补一个公共入口，让上传走**同一条**链路：建 revision → 入队 → 内联执行完整 pipeline。
    """
    from app.modules import papers as papers_mod

    resolved_title = (title or "").strip() or "Uploaded Paper"
    source = _store_inline_source(paper_id, data, url, resolved_title)
    # 传 ctx：让 revision 登记模型快照（见 _ingest_ctx 的说明）
    revision = papers_mod.create_revision(
        paper_id, _source_id_of(source), "source", _ingest_ctx(paper_id),
    )
    spec = JobSpec(
        paper_id=paper_id,
        revision_id=revision.id,
        kind="ingest",
        source=source,
    )
    ctx = _ingest_ctx(paper_id, revision.id)
    from app.modules.pipeline import service as svc

    job = svc.enqueue(spec, ctx)
    _run_job_inline(job.id)
    return job.id


def ingest_paper_from_pdf(
    db: Session,
    data: bytes,
    url: str = "",
    title: str = "",
) -> int:
    """旧签名兼容：入队并内联执行 ingest，返回稳定 paper_id。

    ``db`` 只用于兼容旧调用约定；本函数不把它带入任何云调用。
    """
    from app.modules import papers as papers_mod

    resolved_title = (title or "").strip() or "Uploaded Paper"
    provenance = "source_document" if (data or url) else "synthetic"

    paper_id = _find_paper_by_slug(resolved_title)
    if paper_id is None:
        paper = papers_mod.create_paper(
            PaperCreate(
                title=resolved_title,
                source_mode="real" if url else "upload",
                provenance_class=provenance,
                idempotency_key=_idem_key(resolved_title, url),
            )
        )
        paper_id = paper.id

    job_id = _enqueue_and_run(paper_id, data=data, url=url, title=resolved_title)
    log.info("ingest_paper_from_pdf: paper=%s job=%s", paper_id, job_id)
    return paper_id


def _idem_key(title: str, url: str) -> str:
    seed = f"{title}|{url}".encode("utf-8")
    return "ingest:" + hashlib.sha256(seed).hexdigest()[:24]


def _find_paper_by_slug(title: str) -> Optional[int]:
    from app.models.models import Paper
    from app.modules.papers import repository as papers_repo

    slug_candidate = papers_repo.make_slug(title)
    with session_scope() as db:
        row = db.execute(select(Paper).where(Paper.slug == slug_candidate)).scalars().first()
        return int(row.id) if row is not None else None


def _enqueue_and_run(paper_id: int, *, data: bytes, url: str, title: str) -> int:
    """建 revision + 入队 + 内联跑一遍（旧调用方需要同步可读）。"""
    from app.modules import papers as papers_mod
    from app.modules.pipeline import service as svc

    source_input: Optional[SourceInput] = None
    if data:
        source_input = _store_inline_source(paper_id, data, url, title)
    elif url:
        source_input = SourceInput(kind="url", url=url, title=title)

    revision = papers_mod.create_revision(
        paper_id, _source_id_of(source_input), "source", _ingest_ctx(paper_id)
    )
    spec = JobSpec(
        paper_id=paper_id,
        revision_id=revision.id,
        kind="ingest",
        source=source_input,
    )
    # 跑 pipeline 的 ctx 也要带快照（分批判定/问答/判定都依赖它）
    ctx = _ingest_ctx(paper_id, revision.id)
    job = svc.enqueue(spec, ctx)
    _run_job_inline(job.id)
    return job.id


def _store_inline_source(paper_id: int, data: bytes, url: str, title: str) -> SourceInput:
    from app.modules import papers as papers_mod

    metadata = SourceMetadata(
        original_filename=f"{title[:40] or 'paper'}.pdf",
        source_url=url or None,
        acquisition="url" if url else "upload",
    )
    source = papers_mod.store_source(paper_id, io.BytesIO(data), metadata)
    return SourceInput(kind="stored", source_document_id=source.id)


def _source_id_of(source_input: Optional[SourceInput]) -> Optional[str]:
    return source_input.source_document_id if source_input is not None else None


def _run_job_inline(job_id: int) -> None:
    """内联跑完整个 job（旧调用方语义：同步完成）。"""
    from app.modules.pipeline import service as svc

    lease = svc.claim_next(f"inline-{job_id}")
    if lease is None or lease.job_id != job_id:
        return
    for _ in range(len(STAGE_ORDER) + 2):
        stage = svc._current_stage(lease.job_id)
        if stage is None:
            return
        try:
            result = svc.run_stage(lease, stage)
        except DomainError as exc:
            log.warning("inline 阶段 %s 失败：%s", stage, exc.message)
            return
        if result.status == "failed" and result.error and not result.error.get("retryable"):
            return


__all__ = ["ingest_paper_from_pdf"]
