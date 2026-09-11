"""M00 — 持久任务、Agent 工具与事件契约（REFACTOR_SPEC §5.8）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import Field

from .ai import ModelSnapshot, Usage
from .common import (
    Budget,
    ContractModel,
    Id,
    JobId,
    PaperId,
    RevisionId,
    Scope,
    StatementId,
    Warning,
)
from .documents import SourceInput
from .evidence import StatementDraft
from .retrieval import RetrievalRequest

#: 错误 DTO（避免此处循环导入 core.errors）
DomainErrorLike = Any

Stage = Literal[
    "acquire", "parse", "normalize", "media", "index", "claims",
    "verify", "exhibits", "qa_bank", "evaluate", "publish",
]
JobState = Literal[
    "queued", "running", "retry_wait", "succeeded", "partial", "failed", "cancelled",
]
StageStatus = Literal["succeeded", "partial", "failed", "skipped"]
ToolName = Literal[
    "retrieve_blocks", "get_blocks", "get_media", "validate_statement", "submit_candidate"
]


class JobSpec(ContractModel):
    """review_ids 默认空，非空只允许 reprocess，必须来自相同旧 scope。"""

    paper_id: PaperId
    revision_id: Optional[RevisionId] = None
    kind: Literal["ingest", "reprocess", "evaluate"] = "ingest"
    source: Optional[SourceInput] = None
    review_ids: List[Id] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    model_snapshot: Optional[ModelSnapshot] = None
    budget: Optional[Budget] = None


class JobRecord(ContractModel):
    id: JobId
    paper_id: PaperId
    revision_id: Optional[RevisionId] = None
    state: JobState = "queued"
    stage: Stage = "acquire"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    attempt: int = Field(default=0, ge=0)
    lease_owner: Optional[str] = None
    lease_until: Optional[datetime] = None
    fence: int = 0
    cancel_requested: bool = False
    error: Optional[Any] = None
    model_snapshot: Optional[ModelSnapshot] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StageResult(ContractModel):
    stage: Stage
    status: StageStatus = "succeeded"
    artifact_ids: List[Id] = Field(default_factory=list)
    artifact_digest: Optional[str] = None
    usage: Usage = Field(default_factory=Usage)
    warnings: List[Warning] = Field(default_factory=list)
    error: Optional[Any] = None


class JobLease(ContractModel):
    job_id: JobId
    worker_id: str
    fence: int = Field(ge=0)
    expires_at: datetime


class JobEventData(ContractModel):
    """字段完整但不适用时为 null/[]。"""

    stage: Stage
    progress: float = 0.0
    message: str = ""
    tool: Optional[ToolName] = None
    artifact_ids: List[Id] = Field(default_factory=list)
    elapsed_ms: Optional[int] = None
    usage: Optional[Usage] = None
    error: Optional[Any] = None


class JobEvent(ContractModel):
    event_id: int = Field(ge=1)
    job_id: JobId
    occurred_at: datetime
    type: Literal[
        "stage_started", "stage_finished", "tool_started", "tool_finished",
        "retry_scheduled", "degraded", "completed", "failed", "cancelled",
    ]
    data: JobEventData


class ToolArgs(ContractModel):
    """按工具名使用不同字段；未使用字段留空。"""

    scope: Optional[Scope] = None
    retrieval: Optional[RetrievalRequest] = None
    block_ids: List[str] = Field(default_factory=list)
    media_ids: List[str] = Field(default_factory=list)
    statement: Optional[StatementDraft] = None


class ToolCall(ContractModel):
    id: Id
    role: Literal["analyst", "verifier", "presenter"]
    name: ToolName
    args: ToolArgs = Field(default_factory=ToolArgs)


class ToolResult(ContractModel):
    """由工具名唯一确定 payload 类型。"""

    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}

    call_id: Id
    status: Literal["ok", "rejected", "error"] = "ok"
    payload: Optional[Any] = None
    error: Optional[Any] = None


class SupervisorDecision(ContractModel):
    """reason_code 为受控原因枚举，复用 ValidationReason.code。"""

    action: Literal["accept", "retrieve_more", "repair", "abstain"]
    statement_id: StatementId
    reason_code: str = "passed"
    next_query: Optional[str] = None


# 工具权限（§5.8）
TOOL_PERMISSIONS: dict[str, set[str]] = {
    "retrieve_blocks": {"analyst"},
    "get_blocks": {"analyst", "verifier"},
    "get_media": {"presenter", "analyst"},
    "validate_statement": {"verifier"},
    "submit_candidate": {"analyst"},
}

# 阶段权重（用于 progress 展示）
STAGE_ORDER: List[str] = [
    "acquire", "parse", "normalize", "media", "index", "claims",
    "verify", "exhibits", "qa_bank", "evaluate", "publish",
]

# Job 外部状态兼容映射（§5.8）
STATE_TO_LEGACY: dict[str, str] = {
    "queued": "pending",
    "running": "running",
    "retry_wait": "running",
    "succeeded": "done",
    "partial": "done",
    "failed": "failed",
    "cancelled": "failed",
}


__all__ = [
    "Stage", "JobState", "StageStatus", "ToolName",
    "JobSpec", "JobRecord", "StageResult", "JobLease", "JobEventData", "JobEvent",
    "ToolArgs", "ToolCall", "ToolResult", "SupervisorDecision",
    "TOOL_PERMISSIONS", "STAGE_ORDER", "STATE_TO_LEGACY",
]
