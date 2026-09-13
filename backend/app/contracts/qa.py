"""M00 — 问答与流式协议契约（REFACTOR_SPEC §5.7）。

`grounded=true` 仅当答案有实质内容、所有事实句都有验证通过的证据、且无未支持推断混入；
纯拒答一律 false，绝不按「未出现拒答词」判定。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional, Union

from pydantic import Field

from .ai import Usage
from .common import ContractModel, Id, RevisionId, Scope, Warning
from .evidence import ArtifactText, EvidenceRecord, VerifiedStatement

Confidence = Literal["High", "Medium", "Low"]

#: 回答形态（R4-M3，ADR D-104）：**没有"拒答"这一档**——所有问题都有回答，靠 `confidence` 表达可靠度。
#:
#: - ``generated``     有证据作答（是否 grounded 由 Evidence Gate 判，见 `answer_gate`）
#: - ``extractive``    抽取式作答（逐字原文块 / 逐字原文片段）
#: - ``general``       通用回答（**未使用论文证据**，note 必须写明）
#: - ``not_mentioned`` 论文未提及所问对象（如实说明，属"有信息的回答"而非拒答）
#: - ``cached``        缓存命中
#: - ``unavailable``   模型不可用（如实说明 + 已知信息，可重试）
#:
#: ``abstained`` 已从产品语义删除（决策 1）。历史行由 `qa.service._row_to_answer` 在读取处映射，
#: 新代码**不可能**再产出该取值。
AnswerMode = Literal[
    "generated", "extractive", "cached", "general", "not_mentioned", "unavailable",
]
StreamEventType = Literal["meta", "status", "citation", "sentence", "final", "error"]
StreamStage = Literal["retrieving", "reranking", "drafting", "verifying", "degraded"]


class QARequest(ContractModel):
    """旧请求 top_k 越界时由服务层 clamp 到 1..20 并记 warning，不直接 422。"""

    question: str = Field(min_length=1, max_length=2000)
    top_k: int = 5
    revision_id: Optional[RevisionId] = None


class AnswerRecord(ContractModel):
    scope: Scope
    id: Id
    question: str
    text: ArtifactText
    statements: List[VerifiedStatement] = Field(default_factory=list)
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    grounded: bool = False
    confidence: Confidence = "Low"
    note: str = ""
    mode: AnswerMode = "generated"
    model_snapshot_id: Optional[Id] = None
    usage: Usage = Field(default_factory=Usage)
    warnings: List[Warning] = Field(default_factory=list)


class QAMeta(ContractModel):
    scope: Scope
    answer_id: Id
    deadline_at: Optional[datetime] = None


class QAStatus(ContractModel):
    """只展示工作状态，不含未验证答案或思维链。"""

    stage: StreamStage = "retrieving"
    message: str = ""


class QACitation(ContractModel):
    evidence: EvidenceRecord


class QASentence(ContractModel):
    statement: VerifiedStatement


class QAFinal(ContractModel):
    legacy: Any = None      # AskResponse（避免 api schema 循环导入）
    answer: AnswerRecord


class QAError(ContractModel):
    error: Any = None       # DomainError
    partial: bool = False


QAEventData = Union[QAMeta, QAStatus, QACitation, QASentence, QAFinal, QAError]


class QAStreamEvent(ContractModel):
    event_id: int = Field(ge=1)
    request_id: Id
    type: StreamEventType
    data: Optional[Any] = None


__all__ = [
    "Confidence",
    "AnswerMode",
    "StreamEventType",
    "StreamStage",
    "QARequest",
    "AnswerRecord",
    "QAMeta",
    "QAStatus",
    "QACitation",
    "QASentence",
    "QAFinal",
    "QAError",
    "QAEventData",
    "QAStreamEvent",
]
