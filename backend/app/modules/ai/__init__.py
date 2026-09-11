"""M05 — AI 调用与模型治理（REFACTOR_SPEC §6.7）。

在现有 DashScope OpenAI 兼容 ``AIClient`` 之上封装：类型验证、预算、取消与模型
快照，**不替换供应商**。公共 API 见 ``service``。
"""
from .capabilities import (  # noqa: F401
    capabilities_for,
    get_snapshot,
    is_embedding_only,
    list_capabilities,
)
from .service import (  # noqa: F401
    complete,
    embed,
    get_capabilities,
    is_ready,
    set_chat_model,
)
from .transport import build_providers, close_clients  # noqa: F401

__all__ = [
    "complete",
    "embed",
    "get_capabilities",
    "set_chat_model",
    "is_ready",
    "get_snapshot",
    "is_embedding_only",
    "capabilities_for",
    "list_capabilities",
    "build_providers",
    "close_clients",
]
