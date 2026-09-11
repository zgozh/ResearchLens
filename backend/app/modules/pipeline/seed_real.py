"""M11 — 真实论文 seed（REFACTOR_SPEC §6.13、§6.17）。

统一走数据库任务状态机：**入队 ingest 任务**（URL 下载归 worker 的 acquire 阶段），
不再在 API/启动路径同步下载解析。幂等按源 URL 判定：已存在则跳过。

``seed_catalog``（M15 入口）与旧的 ``provision_real_papers`` 共用本模块。
"""
from __future__ import annotations

import hashlib
import logging
import threading
from typing import List, Optional

from sqlalchemy import select

from app.contracts.common import Scope, new_ctx
from app.contracts.documents import PaperCreate, SourceInput
from app.contracts.jobs import JobSpec
from app.core.config import settings
from app.core.db import session_scope

log = logging.getLogger("researchlens.seed_real")

# 真实中文论文：软件学报（开放获取），正式出版。
REAL_PAPERS = [
    ("https://www.jos.org.cn/josen/article/pdf/5281",
     "基于Haar小波域指标自适应选择载体的JPEG隐写"),
    ("https://www.jos.org.cn/josen/article/pdf/6106",
     "数据驱动的移动应用用户接受度建模与预测"),
    ("https://www.jos.org.cn/josen/article/pdf/6550",
     "基于软件度量的Solidity智能合约缺陷预测方法"),
]


def provision_real_papers() -> None:
    """如数据库缺失真实论文则**入队**；下载/解析由 worker 执行。

    - 按标题幂等（同标题不重复建论文）；
    - 不要求 LLM 健康才能入队；无 LLM 时解析/原始文本仍可读。
    """
    if settings.demo_mode:
        log.info("seed_real: DEMO_MODE=true — 跳过真实论文入队")
        return

    try:
        report = seed_catalog("real")
        log.info("seed_real: 入队 %d 篇，跳过 %d 篇", len(report.get("job_ids", [])),
                 len(report.get("skipped", [])))
    except Exception as exc:  # noqa: BLE001
        log.warning("seed_real: 入队失败 %s", exc)


def seed_catalog(mode: str = "real", ctx=None) -> dict:
    """M15 入口：按模式幂等入队 seed 任务。返回 SeedReport 形状 dict。"""
    if mode not in ("synthetic", "real"):
        raise ValueError("mode 必须是 synthetic|real")
    if mode == "synthetic":
        # synthetic 由演示 seed 提供（不要求 LLM）；此处只报告状态
        return {"paper_ids": [], "job_ids": [], "skipped_keys": [], "warnings": []}

    from app.modules import papers as papers_mod
    from app.modules.pipeline import service as svc

    paper_ids: List[int] = []
    job_ids: List[int] = []
    skipped: List[str] = []

    for url, title in REAL_PAPERS:
        key = _idem_key(title)
        existing = _find_paper(title)
        if existing is not None:
            # 已有论文且有活动/完成 job：跳过（不重复下载）
            if _has_active_or_done(existing):
                skipped.append(key)
                continue
            paper_id = existing
        else:
            paper = papers_mod.create_paper(
                PaperCreate(
                    title=title, source_mode="real",
                    provenance_class="source_document", idempotency_key=key,
                )
            )
            paper_id = paper.id

        spec = JobSpec(
            paper_id=paper_id,
            kind="ingest",
            source=SourceInput(kind="url", url=url, title=title),
            idempotency_key=f"seed:{key}",
            model_snapshot=_snapshot(),
        )
        job = svc.enqueue(spec, new_ctx(None))
        paper_ids.append(paper_id)
        job_ids.append(job.id)

    return {
        "paper_ids": _dedup(paper_ids),
        "job_ids": _dedup(job_ids),
        "skipped_keys": skipped,
        "warnings": [],
    }


def _snapshot():
    try:
        from app.modules.ai import get_snapshot

        return get_snapshot()
    except Exception:  # noqa: BLE001
        return None


def _idem_key(title: str) -> str:
    return "seed:" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:24]


def _find_paper(title: str) -> Optional[int]:
    from app.models.models import Paper
    from app.modules.papers import repository as papers_repo

    slug_candidate = papers_repo.make_slug(title)
    with session_scope() as db:
        row = db.execute(select(Paper).where(Paper.slug == slug_candidate)).scalars().first()
        return int(row.id) if row is not None else None


def _has_active_or_done(paper_id: int) -> bool:
    from app.models.jobs import JobORM

    with session_scope() as db:
        row = db.execute(
            select(JobORM).where(JobORM.paper_id == paper_id)
        ).scalars().first()
        return row is not None


def _dedup(values: List[int]) -> List[int]:
    seen: List[int] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen


def start_real_provision_thread() -> None:
    """lifespan 调用：后台线程入队（快速返回，不阻塞健康检查）。"""
    t = threading.Thread(target=provision_real_papers, name="seed-real", daemon=True)
    t.start()


__all__ = ["REAL_PAPERS", "provision_real_papers", "seed_catalog", "start_real_provision_thread"]
