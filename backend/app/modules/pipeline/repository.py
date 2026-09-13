"""M11 — 持久任务仓储（REFACTOR_SPEC §5.8、§5.14）。

私有实现：只在本模块内使用。所有写入都是**短事务**；云调用绝不在此持锁。

关键不变量：
- 领取任务使用条件更新（SQLite 单 worker）与行锁（Postgres），保证 at-least-once；
- ``fence`` 单调递增，每次领取 +1；提交阶段产物必须携带当前 fence；
- JobEvent 的 ``event_id`` 在同一 job 内**严格递增**，由 ``MAX(event_id)+1`` 生成；
- 阶段幂等键唯一约束 ``(revision_id, stage, input_digest, algorithm_version)``。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.contracts.ai import ModelSnapshot, Usage
from app.contracts.common import Budget, Warning
from app.contracts.jobs import (
    JobEvent,
    JobEventData,
    JobLease,
    JobRecord,
    StageResult,
)
from app.core.clock import utc_now
from app.models.jobs import JobEventORM, JobORM, JobStageKeyORM

#: 事件保留窗口（秒）——SSE 游标早于保留范围返回 409（§5.8）
EVENT_RETENTION_SECONDS = 7 * 24 * 3600

#: 最多阶段尝试次数（§5.8）
MAX_ATTEMPTS = 3


# ------------------------------------------------------------------ DTO 投影


def _dt(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite 读回的 naive datetime 统一补 UTC，避免与前端的时区比较漂移。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _snapshot_from(raw: Any) -> Optional[ModelSnapshot]:
    if not raw:
        return None
    try:
        return ModelSnapshot.model_validate(raw)
    except Exception:  # noqa: BLE001 - 脏快照不得使整个 job 不可读
        return None


def job_dto(row: JobORM) -> JobRecord:
    return JobRecord(
        id=row.id,
        paper_id=row.paper_id,
        revision_id=row.revision_id,
        state=row.state or "queued",
        stage=row.stage or "acquire",
        progress=float(row.progress or 0.0),
        attempt=int(row.attempt or 0),
        lease_owner=row.lease_owner,
        lease_until=_dt(row.lease_until),
        fence=int(row.fence or 0),
        cancel_requested=bool(row.cancel_requested),
        error=row.error or None,
        model_snapshot=_snapshot_from(row.model_snapshot),
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
    )


def event_dto(row: JobEventORM) -> JobEvent:
    data = JobEventData.model_validate(row.data or {"stage": "acquire"})
    return JobEvent(
        event_id=int(row.event_id),
        job_id=row.job_id,
        occurred_at=_dt(row.occurred_at) or utc_now(),
        type=row.type or "stage_started",
        data=data,
    )


# ------------------------------------------------------------------ 读取


def get_job_row(db: Session, job_id: int) -> Optional[JobORM]:
    return db.get(JobORM, job_id)


def require_job(db: Session, job_id: int) -> JobORM:
    row = db.get(JobORM, job_id)
    if row is None:
        from app.core.errors import not_found

        raise not_found(f"job {job_id} 不存在")
    return row


def find_by_idempotency(db: Session, key: str) -> Optional[JobORM]:
    if not key:
        return None
    return db.execute(select(JobORM).where(JobORM.idempotency_key == key)).scalars().first()


def active_job_for_paper(db: Session, paper_id: int, kinds: Sequence[str] = ("ingest", "reprocess", "evaluate")) -> Optional[JobORM]:
    """当前活动 job（queued/running/retry_wait）——``process`` 幂等复用目标。"""
    stmt = (
        select(JobORM)
        .where(
            JobORM.paper_id == paper_id,
            JobORM.state.in_(list(kinds) and ["queued", "running", "retry_wait"]),
        )
        .order_by(JobORM.id.desc())
    )
    return db.execute(stmt).scalars().first()


def list_paper_jobs(db: Session, paper_id: int) -> List[JobORM]:
    return list(
        db.execute(
            select(JobORM).where(JobORM.paper_id == paper_id).order_by(JobORM.id.asc())
        ).scalars()
    )


# ------------------------------------------------------------------ 入队


def insert_job(
    db: Session,
    *,
    paper_id: int,
    revision_id: Optional[str],
    kind: str,
    spec: Dict[str, Any],
    budget: Dict[str, Any],
    model_snapshot: Dict[str, Any],
    idempotency_key: Optional[str],
    start_stage: str = "acquire",
) -> JobORM:
    row = JobORM(
        paper_id=paper_id,
        revision_id=revision_id,
        kind=kind,
        state="queued",
        # M12：`stage` 就是 runner 的"当前阶段"。续跑时把它设成起点阶段，
        # 之前的阶段天然不会执行（它们已成功、产物已在）。
        stage=(start_stage or "acquire"),
        progress=0.0,
        attempt=0,
        fence=0,
        cancel_requested=False,
        stage_results=[],
        spec=spec,
        budget=budget,
        model_snapshot=model_snapshot,
        idempotency_key=idempotency_key or None,
    )
    db.add(row)
    db.flush()
    return row


# ------------------------------------------------------------------ 领取 / 心跳


def claim_next(db: Session, worker_id: str, lease_seconds: int) -> Optional[JobORM]:
    """领取下一个可执行 job。

    - ``queued`` 直接领取；
    - ``running`` 但租约过期（worker 掉线）可重新领取；
    - 条件更新保证只有一个 worker 成功；
    - 每次领取 ``fence += 1``（stale worker 提交将被拒绝）。
    """
    now = utc_now()
    lease_until = now + timedelta(seconds=max(1, lease_seconds))

    stmt = (
        select(JobORM)
        .where(
            JobORM.state.in_(["queued", "retry_wait", "running"]),
        )
        .order_by(JobORM.state.desc(), JobORM.id.asc())
        .limit(20)
    )
    candidates = list(db.execute(stmt).scalars())
    for row in candidates:
        if row.state == "running":
            expired = row.lease_until is None or _dt(row.lease_until) <= now
            if not expired:
                continue
            if int(row.attempt or 0) >= MAX_ATTEMPTS:
                row.state = "failed"
                row.error = {"code": "INTERNAL_ERROR", "message": "阶段尝试次数耗尽"}
                db.flush()
                continue
        if row.cancel_requested:
            # 取消请求：不领取，直接进入终态（未完成产物不发布）
            row.state = "cancelled"
            db.flush()
            continue

        # 条件更新：只有状态与 fence 仍与读到的一致时才真正领取
        result = db.execute(
            update(JobORM)
            .where(
                JobORM.id == row.id,
                JobORM.fence == row.fence,
                JobORM.state == row.state,
            )
            .values(
                state="running",
                lease_owner=worker_id,
                lease_until=lease_until,
                fence=row.fence + 1,
                attempt=int(row.attempt or 0) + 1,
                updated_at=now,
            )
        )
        if result.rowcount == 1:
            db.flush()
            db.refresh(row)
            return row
        # 竞争失败：尝试下一个候选
    return None


def heartbeat(db: Session, job_id: int, fence: int, worker_id: str, lease_seconds: int) -> Optional[JobORM]:
    """延长租约。fence 不匹配返回 None（stale worker 不得续租）。

    注意：心跳**不复用业务 Session**（独立短事务，见 worker 实现）。
    """
    now = utc_now()
    result = db.execute(
        update(JobORM)
        .where(JobORM.id == job_id, JobORM.fence == fence, JobORM.lease_owner == worker_id)
        .values(lease_until=now + timedelta(seconds=max(1, lease_seconds)), updated_at=now)
    )
    db.flush()
    if result.rowcount != 1:
        return None
    return db.get(JobORM, job_id)


def fence_valid(db: Session, job_id: int, fence: int) -> bool:
    row = db.get(JobORM, job_id)
    if row is None:
        return False
    return int(row.fence or 0) == int(fence)


# ------------------------------------------------------------------ 阶段提交


def record_stage(
    db: Session,
    *,
    job_id: int,
    fence: int,
    result: StageResult,
    stage: str,
    progress: float,
    next_stage: str,
    state: str,
) -> Optional[JobORM]:
    """提交阶段结果（短事务）。fence 过期返回 None，调用方转 CONFLICT。"""
    now = utc_now()
    row = db.get(JobORM, job_id)
    if row is None or int(row.fence or 0) != int(fence):
        return None
    results = list(row.stage_results or [])
    results.append(
        {
            "stage": result.stage,
            "status": result.status,
            "artifact_ids": list(result.artifact_ids or []),
            "artifact_digest": result.artifact_digest,
            "warnings": [w.model_dump() for w in (result.warnings or [])],
            "usage": result.usage.model_dump() if result.usage else None,
            "error": result.error,
            "at": now.isoformat(),
        }
    )
    row.stage_results = results
    row.stage = next_stage or stage
    row.progress = max(0.0, min(1.0, float(progress)))
    # 提交成功，交还租约（worker 不再持有）——但如果已进入终态则清空租约
    if state in ("succeeded", "partial", "failed", "cancelled"):
        row.state = state
        row.lease_owner = None
        row.lease_until = None
    else:
        row.state = state
    row.updated_at = now
    db.flush()
    return row


def mark_state(
    db: Session,
    job_id: int,
    *,
    state: str,
    error: Optional[dict] = None,
    progress: Optional[float] = None,
    release_lease: bool = True,
) -> Optional[JobORM]:
    row = db.get(JobORM, job_id)
    if row is None:
        return None
    row.state = state
    if error is not None:
        row.error = error
    if progress is not None:
        row.progress = max(0.0, min(1.0, float(progress)))
    if release_lease and state in ("succeeded", "partial", "failed", "cancelled", "retry_wait"):
        row.lease_owner = None
        row.lease_until = None
    row.updated_at = utc_now()
    db.flush()
    return row


def set_cancel_requested(db: Session, job_id: int) -> Optional[JobORM]:
    row = db.get(JobORM, job_id)
    if row is None:
        return None
    row.cancel_requested = True
    row.updated_at = utc_now()
    db.flush()
    return row


def set_job_revision(db: Session, job_id: int, revision_id: str, fence: int) -> Optional[JobORM]:
    """acquire 阶段建立 revision 后写回 job（fence 校验，stale worker 不得写）。"""
    row = db.get(JobORM, job_id)
    if row is None or int(row.fence or 0) != int(fence):
        return None
    row.revision_id = revision_id
    row.updated_at = utc_now()
    db.flush()
    return row


def cas_publish_guard(db: Session, job_id: int, fence: int) -> bool:
    """发布前 fence 校验：取消请求或 fence 过期都不得发布。"""
    row = db.get(JobORM, job_id)
    if row is None:
        return False
    if bool(row.cancel_requested):
        return False
    if int(row.fence or 0) != int(fence):
        return False
    return row.state in ("running", "retry_wait")


# ------------------------------------------------------------------ 事件


def next_event_id(db: Session, job_id: int) -> int:
    current = db.execute(
        select(func.max(JobEventORM.event_id)).where(JobEventORM.job_id == job_id)
    ).scalar()
    return int(current or 0) + 1


def append_event(
    db: Session,
    *,
    job_id: int,
    type: str,
    data: JobEventData,
) -> JobEventORM:
    row = JobEventORM(
        job_id=job_id,
        event_id=next_event_id(db, job_id),
        occurred_at=utc_now(),
        type=type,
        data=data.model_dump(mode="json"),
    )
    db.add(row)
    db.flush()
    return row


def last_event(db: Session, job_id: int) -> Optional[JobEventORM]:
    """该 job 的**最后一条**事件（用于事件幂等抑制，M12）。"""
    return db.execute(
        select(JobEventORM)
        .where(JobEventORM.job_id == job_id)
        .order_by(JobEventORM.event_id.desc())
        .limit(1)
    ).scalars().first()


def events_after(db: Session, job_id: int, after: int, limit: int = 500) -> List[JobEventORM]:
    return list(
        db.execute(
            select(JobEventORM)
            .where(JobEventORM.job_id == job_id, JobEventORM.event_id > int(after or 0))
            .order_by(JobEventORM.event_id.asc())
            .limit(limit)
        ).scalars()
    )


def min_event_id(db: Session, job_id: int) -> int:
    value = db.execute(
        select(func.min(JobEventORM.event_id)).where(JobEventORM.job_id == job_id)
    ).scalar()
    return int(value or 0)


# ------------------------------------------------------------------ 阶段幂等键


def find_stage_key(
    db: Session, revision_id: str, stage: str, input_digest: str, algorithm_version: str
) -> Optional[JobStageKeyORM]:
    return db.execute(
        select(JobStageKeyORM).where(
            JobStageKeyORM.revision_id == revision_id,
            JobStageKeyORM.stage == stage,
            JobStageKeyORM.input_digest == input_digest,
            JobStageKeyORM.algorithm_version == algorithm_version,
        )
    ).scalars().first()


def put_stage_key(
    db: Session,
    *,
    revision_id: str,
    stage: str,
    input_digest: str,
    algorithm_version: str,
    status: str,
    artifact_digest: Optional[str],
    detail: str = "",
) -> JobStageKeyORM:
    """写入/更新阶段幂等键。唯一约束冲突说明另一 worker 已提交同一 key。"""
    row = find_stage_key(db, revision_id, stage, input_digest, algorithm_version)
    if row is None:
        row = JobStageKeyORM(
            revision_id=revision_id,
            stage=stage,
            input_digest=input_digest,
            algorithm_version=algorithm_version,
            status=status,
            artifact_digest=artifact_digest,
            detail=detail,
        )
        db.add(row)
    else:
        row.status = status
        row.artifact_digest = artifact_digest
        row.detail = detail
    db.flush()
    return row


def artifact_digest_for(
    db: Session, revision_id: str, stage: str, algorithm_version: str
) -> Optional[str]:
    """已成功的阶段产物 digest（重试/重放时复用，不重复生成）。"""
    row = db.execute(
        select(JobStageKeyORM)
        .where(
            JobStageKeyORM.revision_id == revision_id,
            JobStageKeyORM.stage == stage,
            JobStageKeyORM.algorithm_version == algorithm_version,
            JobStageKeyORM.status == "succeeded",
        )
        .order_by(JobStageKeyORM.created_at.desc())
    ).scalars().first()
    return row.artifact_digest if row else None


__all__ = [
    "EVENT_RETENTION_SECONDS",
    "MAX_ATTEMPTS",
    "job_dto",
    "event_dto",
    "get_job_row",
    "require_job",
    "find_by_idempotency",
    "active_job_for_paper",
    "list_paper_jobs",
    "insert_job",
    "claim_next",
    "heartbeat",
    "fence_valid",
    "record_stage",
    "mark_state",
    "set_cancel_requested",
    "set_job_revision",
    "cas_publish_guard",
    "next_event_id",
    "append_event",
    "events_after",
    "min_event_id",
    "find_stage_key",
    "put_stage_key",
    "artifact_digest_for",
]
