"""M00 — AI 与模型治理契约（REFACTOR_SPEC §5.6）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, List, Literal, Optional, TypeVar

from pydantic import Field, field_validator

from .common import ContractModel, Hash, Id, Warning

T = TypeVar("T")


class ModelSnapshot(ContractModel):
    """不含密钥；密钥服务端即时解析。"""

    id: Optional[Id] = None
    provider: Literal["dashscope"] = "dashscope"
    base_url: str = ""
    chat_model: str
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    capability_version: str = "rl.capabilities/1"
    temperature: float = 0.2
    created_at: Optional[datetime] = None


class ModelCapabilities(ContractModel):
    """null 是未知，不凭模型名猜支持。"""

    model: str
    purposes: List[Literal["chat", "embedding"]] = Field(default_factory=lambda: ["chat"])
    json_schema: Optional[bool] = None
    json_object: Optional[bool] = None
    streaming: Optional[bool] = None
    embedding_dimension: Optional[int] = None


class ChatMessage(ContractModel):
    """论文内容总在不可信资料边界，不当 system 指令。"""

    role: Literal["system", "user", "assistant"]
    content: str


class SchemaRef(ContractModel, Generic[T]):
    """版本化受控 Pydantic 类型名，不接受用户任意 schema。"""

    name: str
    version: str = "1"


class CompletionRequest(ContractModel, Generic[T]):
    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}

    messages: List[ChatMessage]
    output_schema: Optional[Any] = None    # SchemaRef[T] 或 Pydantic 模型类
    max_output_tokens: int = Field(default=2048, gt=0)
    temperature: float = 0.2
    model_snapshot: Optional[ModelSnapshot] = None


class Usage(ContractModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    elapsed_ms: int = 0


class CompletionResult(ContractModel, Generic[T]):
    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}

    value: Any = None
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    mode: Literal["json_schema", "json_object", "text", "none"] = "none"
    attempts: int = 1
    warnings: List[Warning] = Field(default_factory=list)


class EmbeddingBatch(ContractModel):
    """数量/顺序与输入一致，每项长度相同、有限。"""

    model: str
    dimension: int = Field(gt=0)
    vectors: List[List[float]] = Field(default_factory=list)
    input_hashes: List[Hash] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    normalization_version: str = "l2/1"

    @field_validator("vectors")
    @classmethod
    def _finite(cls, v: List[List[float]]) -> List[List[float]]:
        for vec in v:
            for x in vec:
                if x != x or x in (float("inf"), float("-inf")):
                    raise ValueError("向量必须为有限数")
        return v


__all__ = [
    "ModelSnapshot", "ModelCapabilities", "ChatMessage", "SchemaRef",
    "CompletionRequest", "CompletionResult", "Usage", "EmbeddingBatch",
]
