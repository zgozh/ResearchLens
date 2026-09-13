"""M11 — 真实论文 seed（REFACTOR_SPEC §6.13、§6.17）。

统一走数据库任务状态机：**入队 ingest 任务**（URL 下载归 worker 的 acquire 阶段），
不再在 API/启动路径同步下载解析。幂等按源 URL 判定：已存在则跳过。

``seed_catalog``（M15 入口）与旧的 ``provision_real_papers`` 共用本模块。

**启动只自动导入 1 篇**（``AUTO_SEED_PAPERS``）：另外两篇留在 ``REAL_PAPERS`` 目录里，
由使用者在导入页自己点（见 `app/tests/unit/test_seed_real_auto_policy.py`）。
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

# 真实中文论文目录：软件学报（开放获取），正式出版。
#
# 为什么**三篇都留在这个目录里**：导入页（frontend/app/upload/page.tsx 的
# EXAMPLE_PAPERS）要用这三条链接做「点一下就能测」的示例 —— 删掉就等于把它们藏起来。
# 但**启动自举只用第一篇**（见下面的 AUTO_SEED_PAPERS）。
REAL_PAPERS = [
    ("https://www.jos.org.cn/josen/article/pdf/5281",
     "基于Haar小波域指标自适应选择载体的JPEG隐写"),
    ("https://www.jos.org.cn/josen/article/pdf/6106",
     "数据驱动的移动应用用户接受度建模与预测"),
    ("https://www.jos.org.cn/josen/article/pdf/6550",
     "基于软件度量的Solidity智能合约缺陷预测方法"),
]

# 启动自动导入的子集：**只 1 篇**。
#
# 为什么不是三篇：自举的代价落在每个克隆者身上 —— 首次启动就要串行跑完（实测未配
# MinerU 约 4 分钟、配 MinerU 约 10 分钟，worker 单进程串行），占着队列与模型配额，
# 而另外两篇往往不是他想看的那一篇。留一篇真实的打底（不是空库、也不只剩自绘示例），
# 其余让他在导入页按需触发。
AUTO_SEED_PAPERS = REAL_PAPERS[:1]


def provision_real_papers() -> None:
    """如数据库缺失**自动子集**（``AUTO_SEED_PAPERS``）则**入队**；下载/解析由 worker 执行。

    - 按标题幂等（同标题不重复建论文）；
    - 不要求 LLM 健康才能入队；无 LLM 时解析/原始文本仍可读；
    - 目录里其余论文**不自动导入**，由使用者在导入页自行触发。
    """
    try:
        report = seed_catalog("real")
        # 注意键名：seed_catalog 返回的是 `skipped_keys`（不是 `skipped`）。
        # 这里曾读错键 → 日志永远打印"跳过 0 篇"，运维看到会以为
        # "既没入队也没跳过"，而实际是"已经导过、被正确跳过了"。
        log.info("seed_real: 入队 %d 篇，跳过 %d 篇", len(report.get("job_ids", [])),
                 len(report.get("skipped_keys", [])))
    except Exception as exc:  # noqa: BLE001
        log.warning("seed_real: 入队失败 %s", exc)


def seed_catalog(mode: str = "real", ctx=None) -> dict:
    """M15 入口：按模式幂等入队 seed 任务。返回 SeedReport 形状 dict。

    ``real`` 模式入队的是 ``AUTO_SEED_PAPERS``（**自动子集，当前 1 篇**），
    不是整个 ``REAL_PAPERS`` 目录 —— 目录里其余篇目留给导入页由使用者手动触发。
    """
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

    for url, title in AUTO_SEED_PAPERS:
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


__all__ = [
    "REAL_PAPERS",
    "AUTO_SEED_PAPERS",
    "provision_real_papers",
    "seed_catalog",
    "start_real_provision_thread",
]
