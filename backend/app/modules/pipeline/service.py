"""M11 — 持久管线公共入口（REFACTOR_SPEC §5.8、§5.10、§6.13）。

公共签名（严格照 §5.10 M11）：

    enqueue(spec: JobSpec, ctx) -> JobRecord
    get_job(job_id) -> JobRecord
    claim_next(worker_id, ctx) -> JobLease | None
    heartbeat(lease, ctx) -> JobLease
    run_stage(lease, stage, ctx) -> StageResult
    cancel(job_id, actor, ctx) -> JobRecord
    retry(job_id, actor, ctx) -> JobRecord
    events(job_id, after) -> AsyncIterator[JobEvent]
    dispatch(call: ToolCall, ctx) -> ToolResult
    decide(reports, ctx) -> SupervisorDecision[]

硬约束：
- 一个 paper_id 贯穿全程，绝不「删除论文重建」恢复；
- 云 I/O 不占长事务：领取 → 心跳 → 阶段产物（无事务）→ 短事务提交；
- 队列 at-least-once，**不声称 exactly-once**；
- fence 过期 → CONFLICT；取消后不再发新工具调用，未完成产物不发布。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from app.contracts.ai import ModelSnapshot, Usage
from app.contracts.common import (
    Budget,
    CallContext,
    Scope,
    Warning,
    new_ctx,
)
from app.contracts.documents import SourceInput
from app.contracts.evidence import ValidationReport
from app.contracts.jobs import (
    STATE_TO_LEGACY,
    STAGE_ORDER,
    JobEvent,
    JobEventData,
    JobLease,
    JobRecord,
    JobSpec,
    Stage,
    StageResult,
    SupervisorDecision,
    ToolCall,
    ToolResult,
)
from app.core.clock import utc_now
from app.core.config import settings
from app.core.db import session_scope
from app.core.errors import (
    DomainError,
    ErrorCode,
    conflict,
    invalid_input,
    not_found,
)

from . import repository as repo
from . import stages as stages_mod
from .repository import EVENT_RETENTION_SECONDS, MAX_ATTEMPTS

#: 瞬时故障 → retry_wait 的退避基数（毫秒）
RETRY_BACKOFF_MS = 1000


# ================================================================== 入队


def enqueue(spec: JobSpec, ctx: Optional[CallContext] = None) -> JobRecord:
    """入队一个任务。幂等键命中返回既有 job（不重复建）。

    - ``review_ids`` 非空只允许 ``kind=reprocess``，且必须来自相同旧 scope；
    - 模型快照在此**固定**，之后 runtime 切换不影响进行中的 job。
    """
    if not isinstance(spec, JobSpec):
        raise invalid_input("spec 必须为 JobSpec", field="spec")
    if spec.review_ids and spec.kind != "reprocess":
        raise invalid_input("review_ids 非空时 kind 必须是 reprocess", field="review_ids")

    snapshot = spec.model_snapshot or _snapshot_from_runtime()
    budget = spec.budget or _default_budget()

    with session_scope() as db:
        if spec.idempotency_key:
            existing = repo.find_by_idempotency(db, spec.idempotency_key)
            if existing is not None:
                return repo.job_dto(existing)

        from app.modules.papers import repository as papers_repo

        papers_repo.require_paper(db, spec.paper_id)

        revision_id = spec.revision_id
        if not revision_id:
            revision_id = _resolve_revision(db, spec.paper_id)

        spec_payload = _spec_payload(spec, revision_id)
        row = repo.insert_job(
            db,
            paper_id=spec.paper_id,
            revision_id=revision_id,
            kind=spec.kind,
            spec=spec_payload,
            budget=budget.model_dump(),
            model_snapshot=snapshot.model_dump(mode="json") if snapshot else {},
            idempotency_key=spec.idempotency_key,
        )
        job_id = row.id
        _emit(db, job_id, "stage_started", stage="acquire", progress=0.0,
              message="任务已入队")
        db.flush()
    return get_job(job_id)


def _spec_payload(spec: JobSpec, revision_id: Optional[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "kind": spec.kind,
        "review_ids": list(spec.review_ids or []),
        "revision_id": revision_id,
    }
    if spec.source is not None:
        payload["source"] = spec.source.model_dump(mode="json")
    return payload


def _snapshot_from_runtime() -> Optional[ModelSnapshot]:
    try:
        from app.modules.ai import get_snapshot

        return get_snapshot()
    except Exception:  # noqa: BLE001 - 快照不可得不得阻断入队
        return None


def _default_budget() -> Budget:
    return Budget(
        max_calls=settings.ingest_budget_calls,
        max_input_tokens=settings.ingest_budget_input_tokens,
        max_output_tokens=settings.ingest_budget_output_tokens,
        max_wall_ms=settings.ingest_budget_wall_ms,
        max_repair_rounds=2,
    )


def _resolve_revision(db, paper_id: int) -> Optional[str]:
    from app.models.models import Paper
    from app.models.source import RevisionORM
    from sqlalchemy import select

    row = db.get(Paper, paper_id)
    if row is not None:
        if row.readable_revision_id:
            return row.readable_revision_id
        if row.published_revision_id:
            return row.published_revision_id
    found = db.execute(
        select(RevisionORM.id)
        .where(RevisionORM.paper_id == paper_id)
        .order_by(RevisionORM.created_at.desc())
        .limit(1)
    ).first()
    return found[0] if found else None


# ================================================================== 读取


def get_job(job_id: int) -> JobRecord:
    with session_scope() as db:
        return repo.job_dto(repo.require_job(db, job_id))


def legacy_status(job: JobRecord) -> str:
    """Job 外部状态兼容映射（§5.8）：queued→pending 等。"""
    return STATE_TO_LEGACY.get(job.state, "pending")


def _current_stage(job_id: int) -> Optional[str]:
    """当前应执行的阶段；已终态返回 None。供内联/worker 循环使用。"""
    with session_scope() as db:
        row = repo.get_job_row(db, job_id)
        if row is None or row.state in ("succeeded", "partial", "failed", "cancelled"):
            return None
        return row.stage


# ================================================================== 领取 / 心跳


def claim_next(worker_id: str, ctx: Optional[CallContext] = None) -> Optional[JobLease]:
    """领取下一个可执行 job；无工作返回 None。"""
    if not worker_id:
        raise invalid_input("worker_id 不能为空", field="worker_id")
    with session_scope() as db:
        row = repo.claim_next(db, worker_id, settings.job_lease_seconds)
        if row is None:
            return None
        _emit(db, row.id, "stage_started", stage=row.stage,
              progress=float(row.progress or 0.0),
              message=f"worker={worker_id} 已领取")
        db.flush()
        return JobLease(
            job_id=row.id, worker_id=worker_id, fence=int(row.fence or 0),
            expires_at=_as_utc(row.lease_until) or (utc_now() + timedelta(seconds=settings.job_lease_seconds)),
        )


def heartbeat(lease: JobLease, ctx: Optional[CallContext] = None) -> JobLease:
    """延长租约；fence 过期抛 CONFLICT（stale worker 不得续租）。"""
    if not isinstance(lease, JobLease):
        raise invalid_input("lease 必须为 JobLease", field="lease")
    with session_scope() as db:
        row = repo.heartbeat(
            db, lease.job_id, lease.fence, lease.worker_id, settings.job_lease_seconds
        )
        if row is None:
            raise conflict("租约已失效（fence 过期或已被他人接管）")
        return JobLease(
            job_id=row.id, worker_id=lease.worker_id, fence=int(row.fence or 0),
            expires_at=_as_utc(row.lease_until) or lease.expires_at,
        )


# ================================================================== 阶段执行


def run_stage(
    lease: JobLease,
    stage: Stage,
    ctx: Optional[CallContext] = None,
) -> StageResult:
    """执行一个阶段并短事务提交结果。

    幂等：若 ``(revision_id, stage, input_digest, algorithm_version)`` 已成功，
    直接复用产物 digest 返回 skipped（不重复生成、不重复发布）。
    """
    if not isinstance(lease, JobLease):
        raise invalid_input("lease 必须为 JobLease", field="lease")

    with session_scope() as db:
        row = repo.require_job(db, lease.job_id)
        if not repo.cas_publish_guard(db, lease.job_id, lease.fence):
            if bool(row.cancel_requested):
                raise DomainError(ErrorCode.CANCELLED, "任务已请求取消")
            raise conflict("fence 已过期，拒绝写入（stale worker）")
        scope = Scope(paper_id=row.paper_id, revision_id=row.revision_id or "")
        spec = dict(row.spec or {})
        snapshot = repo._snapshot_from(row.model_snapshot)
        budget = _budget_from(row.budget)
        current_stage = row.stage
        cancelled = bool(row.cancel_requested)

    if cancelled:
        raise DomainError(ErrorCode.CANCELLED, "任务已请求取消，未完成产物不发布")

    # 只有 acquire 阶段允许 revision 为空（它负责获取源文件并建立 revision）
    if not scope.revision_id and stage != "acquire":
        result = StageResult(
            stage=stage, status="failed",
            error={"code": ErrorCode.CONFLICT.value, "message": "任务尚无 revision，无法执行阶段"},
        )
        _commit(result, lease, stage, state="failed")
        return result

    stage_ctx = ctx or new_ctx(scope)
    stage_ctx = _with_snapshot_budget(stage_ctx, scope, snapshot, budget)

    # 幂等键：输入 digest 由 scope + 阶段 + 算法版本决定。
    # acquire 阶段 revision 尚未建立，用 paper 级标识占位（revision 建立后不用此键）。
    input_digest = stages_mod._digest(
        scope.revision_id or f"paper:{scope.paper_id}", stage, stages_mod.ALGORITHM_VERSION
    )
    if scope.revision_id:
        with session_scope() as db:
            prior = repo.find_stage_key(
                db, scope.revision_id, stage, input_digest, stages_mod.ALGORITHM_VERSION
            )
            if prior is not None and prior.status == "succeeded":
                result = StageResult(
                    stage=stage, status="skipped", artifact_digest=prior.artifact_digest,
                    warnings=[Warning(
                        code="stage_idempotent_replay",
                        message="该阶段已成功执行过（幂等键命中），复用产物",
                        stage=stage,
                    )],
                )
                # 幂等命中也要推进 stage（否则 worker 会无限循环在同一阶段）
                _commit_result(result, lease, stage, scope, input_digest)
                return result

    # ---- 阶段执行：云 I/O，无写事务 ----
    result = stages_mod.run_stage_impl(stage, scope, spec, stage_ctx)

    # ---- acquire 后：把新建的 revision 写回 job，并更新 scope / input_digest ----
    if stage == "acquire" and result.status in ("succeeded", "partial"):
        new_revision = result.artifact_ids[0] if result.artifact_ids else None
        if new_revision and new_revision != scope.revision_id:
            with session_scope() as db:
                repo.set_job_revision(db, lease.job_id, new_revision, lease.fence)
            scope = Scope(paper_id=scope.paper_id, revision_id=new_revision)
            input_digest = stages_mod._digest(new_revision, stage, stages_mod.ALGORITHM_VERSION)

    # ---- 短事务提交产物 / 幂等键 / 事件 ----
    _commit_result(result, lease, stage, scope, input_digest)
    return result


def _commit_result(
    result: StageResult, lease: JobLease, stage: Stage, scope: Scope, input_digest: str
) -> None:
    with session_scope() as db:
        row = repo.require_job(db, lease.job_id)
        if int(row.fence or 0) != int(lease.fence):
            raise conflict("fence 已过期，拒绝提交阶段产物")

        if result.status in ("succeeded", "partial", "skipped"):
            repo.put_stage_key(
                db, revision_id=scope.revision_id, stage=stage,
                input_digest=input_digest, algorithm_version=stages_mod.ALGORITHM_VERSION,
                status="succeeded" if result.status != "partial" else "partial",
                artifact_digest=result.artifact_digest,
                detail=";".join(w.message for w in (result.warnings or []))[:1000],
            )

        next_stage = stages_mod.next_stage_of(stage)
        effective = "skipped" if result.status == "skipped" else result.status

        if effective == "failed":
            _commit_failure(db, row, lease, stage, result)
            return

        if next_stage is None:
            # 末阶段（publish）：根据整体是否有 partial 决定终态
            final_state = _final_state(db, row)
            repo.record_stage(
                db, job_id=row.id, fence=lease.fence, result=result, stage=stage,
                progress=1.0, next_stage=stage, state=final_state,
            )
            event_type = {
                "succeeded": "completed", "partial": "completed",
                "failed": "failed", "cancelled": "cancelled",
            }.get(final_state, "completed")
            _emit(db, row.id, event_type, stage=stage, progress=1.0,
                  message=f"任务结束：{final_state}",
                  artifact_ids=result.artifact_ids, usage=result.usage)
        else:
            repo.record_stage(
                db, job_id=row.id, fence=lease.fence, result=result, stage=stage,
                progress=_progress_for(stage), next_stage=next_stage, state="running",
            )
            _emit(db, row.id, "stage_finished", stage=stage,
                  progress=_progress_for(stage), message=f"{stage} 完成",
                  artifact_ids=result.artifact_ids, usage=result.usage)
            if result.status == "partial":
                _emit(db, row.id, "degraded", stage=stage,
                      progress=_progress_for(stage),
                      message="阶段部分完成，保留可用产物")
            _emit(db, row.id, "stage_started", stage=next_stage,
                  progress=_progress_for(stage), message=f"开始 {next_stage}")
        db.flush()


def _commit_failure(db, row, lease: JobLease, stage: Stage, result: StageResult) -> None:
    """失败：可重试且未超尝试上限 → retry_wait；否则 failed。"""
    error = result.error or {}
    retryable = bool(error.get("retryable", False))
    attempt = int(row.attempt or 0)
    if retryable and attempt < MAX_ATTEMPTS:
        repo.record_stage(
            db, job_id=row.id, fence=lease.fence, result=result, stage=stage,
            progress=float(row.progress or 0.0), next_stage=stage, state="retry_wait",
        )
        _emit(db, row.id, "retry_scheduled", stage=stage,
              progress=float(row.progress or 0.0),
              message=f"瞬时故障，第 {attempt} 次尝试后重排（最多 {MAX_ATTEMPTS} 次）",
              error=error)
        db.flush()
        return

    reason = "尝试次数耗尽" if retryable and attempt >= MAX_ATTEMPTS else "非可重试错误"
    repo.record_stage(
        db, job_id=row.id, fence=lease.fence, result=result, stage=stage,
        progress=float(row.progress or 0.0), next_stage=stage, state="failed",
    )
    _emit(db, row.id, "failed", stage=stage, progress=float(row.progress or 0.0),
          message=f"任务失败：{reason}", error=error)
    db.flush()


def _commit(result: StageResult, lease: JobLease, stage: Stage, state: str) -> None:
    with session_scope() as db:
        repo.record_stage(
            db, job_id=lease.job_id, fence=lease.fence, result=result, stage=stage,
            progress=0.0, next_stage=stage, state=state,
        )
        db.flush()


def _final_state(db, row) -> str:
    results = list(row.stage_results or [])
    if any(r.get("status") in ("partial", "failed") for r in results):
        return "partial"
    return "succeeded"


def _progress_for(stage: str) -> float:
    return stages_mod._cumulative_progress(stage)


def _budget_from(raw: Any) -> Budget:
    try:
        return Budget.model_validate(raw or {})
    except Exception:  # noqa: BLE001
        return _default_budget()


def _with_snapshot_budget(
    ctx: CallContext, scope: Scope, snapshot: Optional[ModelSnapshot], budget: Budget
) -> CallContext:
    # 每个阶段执行时重新计算 deadline（now + budget.max_wall_ms），
    # 而不是沿用 new_ctx 的默认 120 秒——否则 embedding 重试等会耗尽
    # deadline，导致后续 claims 阶段 LLM 被「超过全局 deadline」拒绝。
    deadline_at = utc_now().timestamp() + max(1, budget.max_wall_ms) / 1000.0
    updates: Dict[str, Any] = {
        "scope": scope,
        "budget": budget,
        "deadline_at": datetime.fromtimestamp(deadline_at, tz=timezone.utc),
    }
    if snapshot is not None:
        updates["model_snapshot"] = snapshot
    return ctx.model_copy(update=updates)


# ================================================================== 取消 / 重试


def cancel(job_id: int, actor: Any, ctx: Optional[CallContext] = None) -> JobRecord:
    """请求取消。**重复取消幂等**；已完成返回原终态，不撤销发布。"""
    with session_scope() as db:
        row = repo.require_job(db, job_id)
        if row.state in ("succeeded", "partial", "failed", "cancelled"):
            # 终态不可逆；已完成/部分完成**不撤销发布**
            return repo.job_dto(row)

        repo.set_cancel_requested(db, job_id)
        if row.lease_owner is None:
            # 没有 worker 持有租约：直接进入 cancelled
            repo.mark_state(db, job_id, state="cancelled")
        _emit(db, job_id, "cancelled", stage=row.stage,
              progress=float(row.progress or 0.0),
              message="已请求取消；未完成产物不发布")
        db.flush()
        return repo.job_dto(repo.require_job(db, job_id))


def retry(job_id: int, actor: Any, ctx: Optional[CallContext] = None) -> JobRecord:
    """重试：**创建新任务**（引用可复用产物），不改旧终态。"""
    with session_scope() as db:
        row = repo.require_job(db, job_id)
        if row.state not in ("failed", "partial", "cancelled"):
            raise conflict("只有 failed/partial/cancelled 任务可以重试")
        if row.state in ("running", "queued", "retry_wait"):
            raise conflict("存在活动任务，拒绝重试")

        new_row = repo.insert_job(
            db,
            paper_id=row.paper_id,
            revision_id=row.revision_id,
            kind=row.kind,
            spec=dict(row.spec or {}),
            budget=dict(row.budget or {}),
            model_snapshot=dict(row.model_snapshot or {}),
            idempotency_key=None,
        )
        new_id = new_row.id
        _emit(db, new_id, "stage_started", stage="acquire", progress=0.0,
              message=f"由 job {job_id} 重试创建")
        db.flush()
    return get_job(new_id)


# ================================================================== 事件流


async def events(job_id: int, after: int = 0) -> AsyncIterator[JobEvent]:
    """按序重放 + 监听新事件（at-least-once，客户端去重）。

    - cursor 早于保留范围 → DomainError(CONFLICT)，客户端重新 GET job；
    - 重放到终态后关闭连接。
    """
    with session_scope() as db:
        repo.require_job(db, job_id)
        minimum = repo.min_event_id(db, job_id)

    if after and minimum and after < minimum - 1:
        raise DomainError(
            ErrorCode.CONFLICT,
            f"游标 {after} 早于保留范围（最小可用 {maximum_cursor(minimum)}）；请重新 GET job",
            retryable=False,
        )

    cursor = int(after or 0)
    terminal = {"completed", "failed", "cancelled"}
    idle_ticks = 0
    while True:
        batch = _read_events(job_id, cursor)
        if batch:
            idle_ticks = 0
            for event in batch:
                cursor = event.event_id
                yield event
                if event.type in terminal:
                    return
            continue

        terminal_state = _job_terminal_state(job_id)
        if terminal_state is not None:
            # 任务已终态但无新事件：补一条终态事件后关闭
            return

        idle_ticks += 1
        if idle_ticks >= 2:
            idle_ticks = 0
        await asyncio.sleep(0.5)


def maximum_cursor(min_event_id: int) -> int:
    """保留范围的最小可用游标（客户端可从这里重新订阅）。"""
    return max(0, int(min_event_id) - 1)


def _read_events(job_id: int, after: int) -> List[JobEvent]:
    with session_scope() as db:
        rows = repo.events_after(db, job_id, after)
        return [repo.event_dto(r) for r in rows]


def _job_terminal_state(job_id: int) -> Optional[str]:
    with session_scope() as db:
        row = repo.get_job_row(db, job_id)
        if row is None:
            return "failed"
        if row.state in ("succeeded", "partial", "failed", "cancelled"):
            return row.state
        return None


# ================================================================== Agent 工具 / 决策


def dispatch(call: ToolCall, ctx: CallContext) -> ToolResult:
    from . import tools as tools_mod

    return tools_mod.dispatch(call, ctx)


def decide(
    reports: List[ValidationReport], ctx: Optional[CallContext] = None
) -> List[SupervisorDecision]:
    from . import supervisor as supervisor_mod

    return supervisor_mod.decide(reports, ctx)


# ================================================================== 事件写入


def _emit(
    db,
    job_id: int,
    type: str,
    *,
    stage: str,
    progress: float,
    message: str = "",
    artifact_ids: Optional[List[str]] = None,
    usage: Optional[Usage] = None,
    error: Optional[dict] = None,
) -> None:
    # M12：抑制**连续重复**的 stage_started。
    # 实测 job 7 的 acquire / claims 各出现两次"开始"：一次来自入队（create_job），
    # 一次来自领取/阶段推进（claim_next / 上一阶段完成）。两处语义不同却共用同一事件类型，
    # 时间线上就像 bug。这里只抑制"上一条已经是同 stage 的 started"的情况，
    # 阶段跑完再重跑时上一条是 finished，不会被误伤。
    if type == "stage_started":
        last = repo.last_event(db, job_id)
        if (
            last is not None
            and last.type == "stage_started"
            and (last.data or {}).get("stage") == stage
        ):
            return
    data = JobEventData(
        stage=stage, progress=float(progress), message=message,
        tool=None, artifact_ids=list(artifact_ids or []),
        elapsed_ms=None, usage=usage, error=error,
    )
    repo.append_event(db, job_id=job_id, type=type, data=data)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


__all__ = [
    "enqueue",
    "get_job",
    "legacy_status",
    "claim_next",
    "heartbeat",
    "run_stage",
    "cancel",
    "retry",
    "events",
    "dispatch",
    "decide",
    "maximum_cursor",
    "_current_stage",
]
