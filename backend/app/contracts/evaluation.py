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
    #: `status=not_evaluated` 时的**机器可读原因码**（小写蛇形，如
    #: `usage_missing_in_answer_rows` / `source_pdf_has_no_coordinate_rects`）。
    #: 为什么需要（REFACTOR_PLAN §5.3）：只有 `method` 那一句中文时，界面与离线分析
    #: 都只能笼统说"未评测"，说不清"为什么测不了"。
    reason: Optional[str] = None


class MetricEntry(ContractModel):
    name: str
    value: MetricValue


class NavigationCheck(ContractModel):
    anchor_id: AnchorId
    page_correct: bool = False
    region_iou: Optional[Score] = None
    latency_ms: int = 0
    # R4-M6 / ADR D-107（expand-first，全部可空）：把区域比对的两个矩形**显式留存**。
    # 为什么要留：`region_iou` 现在恒为 None（原因见 `region.region_iou_or_none`），
    # 但没有这两个字段的话，"为什么算不了"就只能靠读代码。留住它们，排查时能直接看到
    # 是"没有矩形"还是"两个矩形同源"。
    expected_rect: Optional[Rect] = None
    actual_rect: Optional[Rect] = None
    #: 两个矩形所在的空间。当前装配产出 `unit_0_1`（本项目 Rect 契约）。
    rect_units: str = ""


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


class AiJudgeResult(ContractModel):
    """AI 裁判（LLM 语义判等）的结论 —— 用于在**没有人工真值**时也能出分。

    纪律：它只提供"哪些预测断言与参考断言是同一事实"，分数仍由评测层算，
    并且算出来的 support_precision/recall 标 ``proxy``（**不是 measured**）。
    """

    matches: List[List[int]] = Field(default_factory=list)
    #: **真阳性条数**（命中且预测本身有证据支持）。缓存复用时直接用它，
    #: 不能靠 ``matches`` 重算——持久化时不回写配对，重算会得到 0（真实踩过的坑）。
    true_positive: int = Field(default=0, ge=0)
    total_predicted: int = Field(default=0, ge=0)
    total_golden: int = Field(default=0, ge=0)
    model: str = ""
    #: 输入摘要：与当前输入不一致的缓存必须被忽略（ADR-0056）
    digest: str = ""
    judge_version: str = ""


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
    # R4-M5（ADR D-105）：`golden_is_tuning`（调参集 vs 人工确认集）**已删除** ——
    # 产品里不再有人工确认环节，金标集只剩一种形态：AI 从原文构造。
    #: **已缓存的 AI 裁判结果**（摘要匹配时复用，避免每次打开评测页都调用模型）。
    ai_judge: Optional[AiJudgeResult] = None


class EvaluationReport(ContractModel):
    scope: Scope
    id: Id
    version: str = "rl.eval/1"
    #: **主分 = AI 质量评分（自动）**（R4-M5 / ADR D-105）：用 AI 口径公式算，
    #: 四项核心指标"可用"（measured 或 AI 裁判 proxy）即可。核心指标缺失时为
    #: ``None`` + 原因告警，**绝不填 0**。
    overall_score: Optional[float] = None
    #: 分数的**来源**：``"ai_generated"`` = AI 裁判 + 程序测量自动得出（非人工评审）。
    #: 用户拍板取消人工真值维度，但"AI 判定 ≠ 客观测量"这条标注纪律必须保留。
    overall_score_basis: Optional[str] = None
    #: **已废弃**（R4-M5）：与 ``overall_score`` 同值，保留一个版本周期供旧消费方过渡。
    ai_overall_score: Optional[float] = None
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
    # R4-M3 / ADR D-106：`unanswerable_refusal_rate` 更名（产品里不再有"拒答"动作，
    # 口径改为"对不可答题是否如实说明没有依据"）；`answerable_false_refusal_rate` 删除
    # （它测的"可答题被误拒"行为已不存在，留着就是恒 0 的假指标）。
    "unanswerable_honesty_rate",
    "qa_first_verified_ms",
    "qa_total_ms",
    "ingest_ms",
    "input_tokens",
    "output_tokens",
    "recovery_success_rate",
]


#: 现有调用点里 `method`（人读文案）→ `reason`（机器码）的映射。
#: 为什么要这张表而不是逐个改 21 个调用点：先把**已有的**语义固化成稳定码，
#: 新增调用点请直接传 `reason=`（显式优先）。未知文案一律回落 `unspecified`，
#: 保证"任何未评测都带原因码"这条不变量不会被新代码破坏。
_REASON_BY_METHOD = {
    "无 GoldenClaim 真值": "no_golden_truth",
    "无预测样本": "no_prediction_samples",
    "需要 GoldenClaim 真值": "no_golden_truth",
    "无引文跨度": "no_quote_spans",
    "无导航校验样本": "no_navigation_checks",
    "无区域 IoU 样本": "source_pdf_has_no_coordinate_rects",
    "无 usage 记录": "usage_missing_in_answer_rows",
    "无媒体样本": "no_media_samples",
    "无降级事件": "no_degradation_events",
    "尚无评测报告": "no_evaluation_report",
    "报告未包含该指标": "metric_absent_in_report",
    "指标条目不可解析": "metric_entry_unparsable",
    "本次输入未提供该指标数据": "metric_input_missing",
}

UNSPECIFIED_REASON = "unspecified"


def not_evaluated(name: str, *, method: str = "", sample_size: int = 0,
                  unit: str = "ratio", reason: str = "") -> MetricEntry:
    code = (reason or "").strip() or _REASON_BY_METHOD.get(method, UNSPECIFIED_REASON)
    return MetricEntry(
        name=name,
        value=MetricValue(value=None, unit=unit, method=method,
                          status="not_evaluated", sample_size=sample_size,
                          reason=code),
    )


__all__ = [
    "MetricValue", "MetricEntry", "NavigationCheck", "GoldenClaim", "GoldenQuestion",
    "GoldenAnchor", "GoldenSet", "EvaluationInput", "EvaluationReport", "AiJudgeResult",
    "METRIC_NAMES", "not_evaluated",
]
