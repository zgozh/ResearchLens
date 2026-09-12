"""M00 — 评测、复核与导出契约（REFACTOR_SPEC §5.9）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import Field

from .artifacts import Media
from .common import (
    AnchorId,
    BlockId,
    ContractModel,
    Hash,
    Id,
    Rect,
    Scope,
    Score,
    Warning,
)
from .evidence import Binding, ClaimRecord, StatementDraft, VerifiedStatement


class MetricValue(ContractModel):
    """value=null 的未评估不可冒充 0/100。"""

    value: Optional[float] = None
    unit: Literal["ratio", "percent", "count", "ms", "tokens"] = "ratio"
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    sample_size: int = Field(default=0, ge=0)
    method: str = ""
    status: Literal["measured", "proxy", "not_evaluated"] = "not_evaluated"


class MetricEntry(ContractModel):
    name: str
    value: MetricValue


class NavigationCheck(ContractModel):
    anchor_id: AnchorId
    page_correct: bool = False
    region_iou: Optional[Score] = None
    latency_ms: int = 0


class GoldenClaim(ContractModel):
    id: str
    scope: Scope
    text: str
    expected_support: Literal["supports", "contradicts", "insufficient"]
    acceptable_block_ids: List[BlockId] = Field(default_factory=list)


class GoldenQuestion(ContractModel):
    id: str
    scope: Scope
    question: str
    answerable: bool = True
    required_points: List[str] = Field(default_factory=list)
    acceptable_block_ids: List[BlockId] = Field(default_factory=list)


class GoldenAnchor(ContractModel):
    id: str
    scope: Scope
    expected_page_index: int = Field(ge=0)
    expected_rect: Optional[Rect] = None
    source_label: str = ""


class GoldenSet(ContractModel):
    id: str
    version: str
    source_hashes: List[Hash] = Field(default_factory=list)
    claims: List[GoldenClaim] = Field(default_factory=list)
    questions: List[GoldenQuestion] = Field(default_factory=list)
    anchors: List[GoldenAnchor] = Field(default_factory=list)


class EvaluationInput(ContractModel):
    """M12 接收 DTO，不调用 pipeline，不触发生成。"""

    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}

    scope: Scope
    statements: List[VerifiedStatement] = Field(default_factory=list)
    media: List[Media] = Field(default_factory=list)
    bindings: List[Binding] = Field(default_factory=list)
    answers: List[Any] = Field(default_factory=list)     # AnswerRecord（避免循环导入）
    navigation_checks: List[NavigationCheck] = Field(default_factory=list)
    golden: Optional[GoldenSet] = None
    #: ``golden`` 是否为**调参集**（机器自动构造、未经人工确认）。
    #: 规格要求：``support_precision/recall`` 必须有**标注集**才叫 measured，
    #: 且 ``overall_score`` 只在"包含人工真值的核心指标均可测"时才计算；
    #: 调参集**不用于对外报告**（``golden.py`` 的既有约定）。
    golden_is_tuning: bool = False


class EvaluationReport(ContractModel):
    scope: Scope
    id: Id
    version: str = "rl.eval/1"
    overall_score: Optional[float] = None
    metrics: List[MetricEntry] = Field(default_factory=list)
    golden_id: Optional[str] = None
    computed_at: Optional[datetime] = None
    warnings: List[Warning] = Field(default_factory=list)

    def metric(self, name: str) -> Optional[MetricValue]:
        for m in self.metrics:
            if m.name == name:
                return m.value
        return None


#: 固定指标集合（§5.9）
METRIC_NAMES: List[str] = [
    "source_asset_coverage",
    "anchor_page_accuracy",
    "anchor_region_hit_rate",
    "quote_exact_rate",
    "support_precision",
    "support_recall",
    "unsupported_fact_escape_rate",
    "unanswerable_refusal_rate",
    "answerable_false_refusal_rate",
    "qa_first_verified_ms",
    "qa_total_ms",
    "ingest_ms",
    "input_tokens",
    "output_tokens",
    "recovery_success_rate",
]


def not_evaluated(name: str, *, method: str = "", sample_size: int = 0,
                  unit: str = "ratio") -> MetricEntry:
    return MetricEntry(
        name=name,
        value=MetricValue(value=None, unit=unit, method=method,
                          status="not_evaluated", sample_size=sample_size),
    )


__all__ = [
    "MetricValue", "MetricEntry", "NavigationCheck", "GoldenClaim", "GoldenQuestion",
    "GoldenAnchor", "GoldenSet", "EvaluationInput", "EvaluationReport",
    "METRIC_NAMES", "not_evaluated",
]
