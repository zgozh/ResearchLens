"""M11 — 持久管线、工作进程与有界 Agent（REFACTOR_SPEC §3.3、§5.8、§5.10、§6.13）。

公共 API（canonical）：

    enqueue(spec, ctx) -> JobRecord
    get_job(job_id) -> JobRecord
    claim_next(worker_id, ctx) -> JobLease | None
    heartbeat(lease, ctx) -> JobLease
    run_stage(lease, stage, ctx) -> StageResult
    cancel(job_id, actor, ctx) -> JobRecord
    retry(job_id, actor, ctx) -> JobRecord
    events(job_id, after) -> AsyncIterator[JobEvent]
    dispatch(call, ctx) -> ToolResult
    decide(reports, ctx) -> SupervisorDecision[]

旧兼容（仍在被 ``api/routes.py`` / ``seed_real`` 调用）：

    run_pipeline(session, paper_id)      # 旧同步管线签名（转发到状态机）
    ingest_paper_from_pdf(db, data, ...) # 旧 ingest 签名
    stage_label(stage) -> str
    PIPELINE_STAGES
"""
from __future__ import annotations

from .service import (  # noqa: F401
    cancel,
    claim_next,
    decide,
    dispatch,
    enqueue,
    events,
    get_job,
    heartbeat,
    legacy_status,
    retry,
    run_stage,
    _current_stage,
)
from .stages import ALGORITHM_VERSION, STAGE_WEIGHTS  # noqa: F401
from .repository import EVENT_RETENTION_SECONDS, MAX_ATTEMPTS  # noqa: F401

#: 旧阶段名（保留给旧前端/旧 status 轮询）
PIPELINE_STAGES = ["parse", "structure", "claims", "evidence", "graph", "scene", "qa", "eval"]

_STAGE_LABEL = {
    "acquire": "正在获取源文件…",
    "parse": "正在解析论文…",
    "normalize": "正在规范化页码与块…",
    "media": "正在构建原件媒体…",
    "index": "正在建立原文索引…",
    "claims": "正在提取可验证断言…",
    "verify": "正在校验证据（Evidence Gate）…",
    "exhibits": "正在生成结构/图谱/讲解…",
    "qa_bank": "正在准备证据问答…",
    "evaluate": "正在计算自动评测…",
    "publish": "正在原子发布…",
    # 旧名
    "structure": "正在抽取章节结构…",
    "evidence": "正在链接证据（Evidence Gate）…",
    "graph": "正在构建研究图谱…",
    "scene": "正在生成场景与讲解词…",
    "qa": "正在准备证据问答…",
    "eval": "正在计算自动评测…",
    "done": "已完成",
    "failed": "失败",
    "running": "处理中",
    "pending": "等待中",
}


def stage_label(stage: str) -> str:
    return _STAGE_LABEL.get(stage, stage)


def ingest_paper_from_pdf(db, data: bytes, url: str = "", title: str = "") -> int:
    """旧 ingest 签名兼容（见 ``.ingest``）。"""
    from .ingest import ingest_paper_from_pdf as _impl

    return _impl(db, data, url, title)


def run_pipeline(session, paper_id: int) -> int:
    """旧同步管线签名兼容：入队一个 ingest 任务并内联跑完。

    旧调用方（``api/routes.py`` 的 ``/process`` 后台任务）期待同步执行；
    本适配器保持该语义，但内部走同一状态机（一个 paper_id 贯穿、不删除重建）。
    """
    from app.contracts.common import Scope, new_ctx
    from app.contracts.jobs import STAGE_ORDER, JobSpec
    from app.modules.papers import repository as papers_repo
    from app.models.models import Paper
    from app.models.source import RevisionORM
    from sqlalchemy import select

    from app.core.db import session_scope

    from . import service as svc

    with session_scope() as db:
        papers_repo.require_paper(db, paper_id)
        row = db.get(Paper, paper_id)
        revision_id = (row.readable_revision_id if row else None) or (
            row.published_revision_id if row else None
        )
        if not revision_id:
            found = db.execute(
                select(RevisionORM.id)
                .where(RevisionORM.paper_id == paper_id)
                .order_by(RevisionORM.created_at.desc())
                .limit(1)
            ).first()
            revision_id = found[0] if found else None

    spec = JobSpec(
        paper_id=paper_id,
        revision_id=revision_id,
        kind="ingest",
        idempotency_key=f"process:{paper_id}:{revision_id or 'none'}",
    )
    ctx = new_ctx(Scope(paper_id=paper_id, revision_id=revision_id) if revision_id else None)
    job = svc.enqueue(spec, ctx)

    lease = svc.claim_next(f"inline-process-{job.id}")
    if lease is None or lease.job_id != job.id:
        return job.id
    for _ in range(len(STAGE_ORDER) + 2):
        stage = svc._current_stage(lease.job_id)
        if stage is None:
            break
        try:
            result = svc.run_stage(lease, stage)
        except Exception:  # noqa: BLE001
            break
        if result.status == "failed":
            break
    return job.id


__all__ = [
    "enqueue", "get_job", "claim_next", "heartbeat", "run_stage",
    "cancel", "retry", "events", "dispatch", "decide",
    "legacy_status", "stage_label", "PIPELINE_STAGES",
    "ingest_paper_from_pdf", "run_pipeline",
    "ALGORITHM_VERSION", "STAGE_WEIGHTS", "EVENT_RETENTION_SECONDS", "MAX_ATTEMPTS",
]
