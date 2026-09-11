"""M05 — 模型能力治理（REFACTOR_SPEC §5.6、§6.7）。

**核心纪律：null = 未知，不凭模型名猜能力开关。**

本模块只声明"我们能从配置/实际探测确定的事实"：
- 用途（chat / embedding）来自配置中的模型角色；
- ``json_schema`` / ``json_object`` / ``streaming`` 在未实际探测前保持 ``None``；
- ``embedding_dimension`` 只有从实际响应中得到才写值。

``set_chat_model`` 拒绝 embedding-only 模型（§5.10 M05）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.contracts.ai import ModelCapabilities, ModelSnapshot
from app.core import runtime
from app.core.config import settings
from app.core.errors import invalid_input
from app.core.logging import get_logger

log = get_logger(__name__)

#: 已确定的 embedding-only 模型（来自公开命名约定，仅用于拒绝，不用于猜测正向能力）
EMBEDDING_PREFIXES = ("text-embedding", "embedding-")


@dataclass
class _Observed:
    """运行时观测到的能力事实（进程内，来自真实响应）。"""

    json_schema: Optional[bool] = None
    json_object: Optional[bool] = None
    streaming: Optional[bool] = None
    embedding_dimension: Optional[int] = None


_OBSERVED: dict = {}


def is_embedding_only(model: str) -> bool:
    name = (model or "").strip().lower()
    if not name:
        return False
    return name.startswith(EMBEDDING_PREFIXES)


def observe(
    model: str,
    *,
    json_schema: Optional[bool] = None,
    json_object: Optional[bool] = None,
    streaming: Optional[bool] = None,
    embedding_dimension: Optional[int] = None,
) -> None:
    """记录一次真实调用得到的可核实事实；只覆盖显式传入的字段。"""
    if not model:
        return
    slot = _OBSERVED.setdefault(model, _Observed())
    if json_schema is not None:
        slot.json_schema = bool(json_schema)
    if json_object is not None:
        slot.json_object = bool(json_object)
    if streaming is not None:
        slot.streaming = bool(streaming)
    if embedding_dimension is not None:
        slot.embedding_dimension = int(embedding_dimension)


def reset_observed() -> None:
    _OBSERVED.clear()


def capabilities_for(model: str) -> ModelCapabilities:
    """单个模型的能力视图；未探测项一律 ``None``。"""
    name = (model or "").strip()
    slot = _OBSERVED.get(name, _Observed())
    purposes: List[str] = ["embedding"] if is_embedding_only(name) else ["chat"]
    return ModelCapabilities(
        model=name,
        purposes=purposes,
        json_schema=slot.json_schema,
        json_object=slot.json_object,
        streaming=slot.streaming,
        embedding_dimension=slot.embedding_dimension,
    )


def list_capabilities() -> List[ModelCapabilities]:
    """当前配置涉及的模型能力列表（含 chat 与 embedding 两个角色）。"""
    models: List[str] = []
    for name in (runtime.get_active_model(), settings.llm_model, runtime.get_embedding_model(),
                 settings.embedding_model):
        if name and name not in models:
            models.append(name)
    return [capabilities_for(m) for m in models]


def get_snapshot() -> ModelSnapshot:
    """当前模型快照（不含密钥）。"""
    data = runtime.get_model_snapshot()
    return ModelSnapshot(**data)


def set_chat_model(model: str, actor=None, ctx=None) -> ModelSnapshot:
    """切换 chat 模型；embedding-only 模型拒绝；写运行时配置（原子）。"""
    name = (model or "").strip()
    if not name:
        raise invalid_input("模型名不能为空", field="model")
    if is_embedding_only(name):
        raise invalid_input(f"模型 {name} 仅支持 embedding，不能设为 chat 模型", field="model")
    runtime.set_active_model(name)
    return get_snapshot()


def capability_version() -> str:
    return runtime.get_model_snapshot().get("capability_version", "rl.capabilities/1")


__all__ = [
    "EMBEDDING_PREFIXES",
    "is_embedding_only",
    "observe",
    "reset_observed",
    "capabilities_for",
    "list_capabilities",
    "get_snapshot",
    "set_chat_model",
    "capability_version",
]
