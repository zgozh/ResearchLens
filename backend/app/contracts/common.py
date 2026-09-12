"""M00 — 全局基础类型（REFACTOR_SPEC §5.1）。"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Generic, List, Literal, Optional, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")

# --------------------------------------------------------------- 标量类型

#: canonical UUID 字符串（后端可用 UUID 或 String(36)），不从图号/下标生成
Id = str
#: 保留原有 int 身份，不改成 UUID 响应
PaperId = int
JobId = int
LegacyEvidenceId = int

RevisionId = str
AssetId = str
AnchorId = str
BlockId = str
MediaId = str
StatementId = str

#: 小写 SHA256 十六进制 64 位
Hash = str

#: 有限 float，0..1；NaN/Infinity 拒绝
Score = float

Origin = Literal["source_extraction", "generated", "synthetic"]

Point = List[float]      # [x, y]
Rect = List[float]       # [x0, y0, x1, y1]
Quad = List[List[float]]  # 四点数组


class ContractModel(BaseModel):
    """契约基类：禁止未声明字段（新增输入字段拒绝），忽略历史多余字段由适配层处理。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, validate_assignment=False)


def _finite(v: float) -> float:
    if v is None:
        return v
    if not math.isfinite(float(v)):
        raise ValueError("必须为有限数")
    return float(v)


class Score01(float):
    """语义标记；实际校验见 ``validate_score``。"""


def validate_score(value: Any, *, field: str = "score") -> Optional[float]:
    """Score 校验：有限 float 0..1；None 合法（表示未评估）。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须为数值") from exc
    if not math.isfinite(f):
        raise ValueError(f"{field} 必须为有限数")
    if f < 0.0 or f > 1.0:
        raise ValueError(f"{field} 必须在 0..1 之间")
    return f


def validate_rect(rect: Any, *, field: str = "rect", allow_none: bool = True) -> Optional[List[float]]:
    """Rect 校验：归一化 0..1、有限数、x0<x1、y0<y1。"""
    if rect is None:
        if allow_none:
            return None
        raise ValueError(f"{field} 不可为空")
    if len(rect) != 4:
        raise ValueError(f"{field} 必须为 [x0,y0,x1,y1]")
    vals = [_finite(v) for v in rect]
    for v in vals:
        if v < -0.001 or v > 1.001:
            raise ValueError(f"{field} 必须归一化到 0..1")
    if not (vals[0] < vals[2] and vals[1] < vals[3]):
        raise ValueError(f"{field} 必须满足 x0<x1 且 y0<y1")
    return vals


def validate_quad(quad: Any, *, field: str = "quad") -> List[List[float]]:
    if not quad:
        return []
    if len(quad) != 4:
        raise ValueError(f"{field} 必须为四点数组")
    out: List[List[float]] = []
    for pt in quad:
        if len(pt) != 2:
            raise ValueError(f"{field} 每点必须为 [x,y]")
        out.append([_finite(pt[0]), _finite(pt[1])])
    return out


def validate_hash(value: str, *, field: str = "sha256") -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} 必须为 64 位十六进制")
    lowered = value.lower()
    if any(c not in "0123456789abcdef" for c in lowered):
        raise ValueError(f"{field} 必须为小写十六进制")
    return lowered


# --------------------------------------------------------------- 结构类型


class Scope(ContractModel):
    """请求/产物的作用域。HTTP 未指定 revision 时在请求开始固定当前 published/readable revision。"""

    paper_id: PaperId
    revision_id: RevisionId


class ArtifactRef(ContractModel):
    """产物引用；注册表验证类型、scope、存在性。"""

    kind: Literal[
        "claim", "statement", "section", "method_step",
        "scene", "graph_node", "graph_edge", "answer",
    ]
    id: str


class SourceRef(ContractModel):
    """多态源引用；目标必须存在、同 scope，禁止任意字符串链接。"""

    kind: Literal["evidence", "media", "anchor", "block"]
    id: str


class Warning(ContractModel):
    code: str
    message: str
    stage: Optional[str] = None


class PageResult(ContractModel, Generic[T]):
    """分页信封；limit 默认 50、最大 200；cursor 不透明且绑定 scope/筛选。"""

    items: List[T] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    total: int = 0


class Budget(ContractModel):
    max_calls: int = Field(ge=0)
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_wall_ms: int = Field(ge=0)
    max_repair_rounds: int = Field(default=2, ge=0, le=2)


class CancelToken(Protocol):
    """仅进程内的取消端口，不序列化。"""

    def is_cancelled(self) -> bool:  # pragma: no cover - 协议
        ...


class NullCancelToken:
    def is_cancelled(self) -> bool:
        return False


class NeverCancelled:
    """默认取消令牌（永不取消）。"""

    def is_cancelled(self) -> bool:
        return False


ProgressCallback = Callable[[str, float, str], None]


class CallContext(ContractModel):
    """调用上下文。``cancel_token`` 不参与序列化。"""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request_id: Id
    scope: Optional[Scope] = None
    deadline_at: datetime
    cancel_token: Any = Field(default_factory=NeverCancelled)
    #: 必须是 ``contracts.ai.ModelSnapshot`` 的**实例**（``new_ctx`` 负责归一化）。
    #:
    #: 这里**不能**声明成 ``ModelSnapshotLike``：那样 pydantic 会把传入的完整快照
    #: 强制降级成 Like 视图，而下游 ``CompletionRequest.model_snapshot`` /
    #: 重排请求声明的是完整 ``ModelSnapshot`` → 校验失败 →
    #: ``qa/service._llm_draft`` 抛异常 → 降级成"抽取式" → 抽取也为空 → **拒答**。
    #: 真实后果（实测）：``/papers/{id}/qa/stream`` 恒返回空气泡 + ``rerank_failed``。
    #: 之所以此前没被发现，是因为 pipeline 走 ``ctx.model_copy(update=...)``
    #: 而 ``model_copy`` **不做校验**，只有 ``new_ctx`` 这条路会踩到。
    model_snapshot: Optional[Any] = None
    budget: Budget = Field(
        default_factory=lambda: Budget(
            max_calls=8, max_input_tokens=60000, max_output_tokens=8000, max_wall_ms=120000
        )
    )

    def is_cancelled(self) -> bool:
        token = self.cancel_token
        try:
            return bool(token.is_cancelled()) if token is not None else False
        except Exception:  # noqa: BLE001
            return False


class ModelSnapshotLike(BaseModel):
    """避免循环导入的宽松快照视图；完整定义见 ``contracts.ai.ModelSnapshot``。"""

    model_config = ConfigDict(extra="allow")

    chat_model: str = ""
    provider: str = "dashscope"


def _normalize_snapshot(value: Any) -> Optional[Any]:
    """把 ``ModelSnapshotLike`` / dict / ``ModelSnapshot`` 统一成完整 ``ModelSnapshot``。

    为什么要归一化（真实缺陷）：``CallContext.model_snapshot`` 曾被声明为
    ``ModelSnapshotLike``，于是 pydantic 把完整快照**降级**成 Like 视图；而下游
    ``CompletionRequest`` / 重排请求要求完整 ``ModelSnapshot`` → ValidationError →
    QA 生成失败并降级成"抽取式"，抽取再为空就**拒答**（用户看到空气泡）。
    ``ModelSnapshotLike`` 只该是"避免循环导入"的读取视图，不该跨进请求契约。
    """
    if value is None:
        return None
    from .ai import ModelSnapshot  # 延迟导入：ai 依赖 common，模块级导入会成环

    if isinstance(value, ModelSnapshot):
        return value
    if isinstance(value, dict):
        try:
            return ModelSnapshot.model_validate(value)
        except Exception:  # noqa: BLE001 - 脏快照不得阻断请求，交给下游降级
            return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return ModelSnapshot.model_validate(value.model_dump())
        except Exception:  # noqa: BLE001
            return None
    return None


def new_ctx(
    scope: Optional[Scope] = None,
    *,
    request_id: str = "",
    deadline_ms: int = 120_000,
    budget: Optional[Budget] = None,
    snapshot: Any = None,
    cancel_token: Any = None,
) -> CallContext:
    """构造 CallContext 的便捷函数。"""
    import uuid

    from ..core.clock import utc_now

    return CallContext(
        request_id=request_id or str(uuid.uuid4()),
        scope=scope,
        deadline_at=datetime.fromtimestamp(
            utc_now().timestamp() + deadline_ms / 1000.0, tz=timezone.utc
        ),
        cancel_token=cancel_token if cancel_token is not None else NeverCancelled(),
        model_snapshot=_normalize_snapshot(snapshot),
        budget=budget
        or Budget(max_calls=8, max_input_tokens=60000, max_output_tokens=8000,
                  max_wall_ms=deadline_ms),
    )


CallContext.model_rebuild()

__all__ = [
    "Id", "PaperId", "JobId", "LegacyEvidenceId",
    "RevisionId", "AssetId", "AnchorId", "BlockId", "MediaId", "StatementId",
    "Hash", "Score", "Origin", "Point", "Rect", "Quad",
    "ContractModel", "Scope", "ArtifactRef", "SourceRef", "Warning",
    "PageResult", "Budget", "CancelToken", "NeverCancelled", "CallContext",
    "ProgressCallback", "new_ctx",
    "validate_score", "validate_rect", "validate_quad", "validate_hash",
]
