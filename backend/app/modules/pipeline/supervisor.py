"""M11 — Supervisor 有界决策器（REFACTOR_SPEC §3.5、§5.8、§6.13）。

允许的决策**只有** ``accept / retrieve_more / repair / abstain``；
不允许自由生成工具名、URL、SQL 或命令。**最多两轮**（``max_repair_rounds`` ≤ 2），
达到预算即降级为待核验（abstain），不让模型决定绕过 gate。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.contracts.common import CallContext
from app.contracts.evidence import ValidationReport
from app.contracts.jobs import SupervisorDecision

#: 受控原因码（复用 ValidationReason.code）
_BUDGET_CODES = {"budget_exhausted", "external_unavailable"}
_RETRIEVE_CODES = {"missing_source", "quote_mismatch", "ambiguous_page", "coordinate_missing"}
_REPAIR_CODES = {"unsupported_entailment", "numeric_mismatch", "qualifier_missing", "wrong_scope"}
_ABSTAIN_CODES = {"contradiction"}


def decide(
    reports: List[ValidationReport],
    ctx: Optional[CallContext] = None,
) -> List[SupervisorDecision]:
    """逐条产出决策。**最多两轮**：round 计数超过预算即 abstain。"""
    max_rounds = 2
    if ctx is not None and ctx.budget is not None:
        max_rounds = min(2, max(0, int(ctx.budget.max_repair_rounds)))

    decisions: List[SupervisorDecision] = []
    for report in reports:
        decisions.append(_decide_one(report, max_rounds))
    return decisions


def _decide_one(report: ValidationReport, max_rounds: int) -> SupervisorDecision:
    code = _primary_reason(report)

    if report.decision == "verified" and report.passed:
        return SupervisorDecision(
            action="accept", statement_id=report.statement_id, reason_code="passed",
        )

    if code in _ABSTAIN_CODES:
        return SupervisorDecision(
            action="abstain", statement_id=report.statement_id, reason_code=code or "contradiction",
        )

    if code in _BUDGET_CODES:
        # 预算/依赖耗尽：降级为待核验，不再补检索，也不让模型绕过 gate
        return SupervisorDecision(
            action="abstain", statement_id=report.statement_id, reason_code=code,
        )

    if max_rounds <= 0:
        return SupervisorDecision(
            action="abstain", statement_id=report.statement_id,
            reason_code="budget_exhausted",
        )

    if code in _RETRIEVE_CODES:
        return SupervisorDecision(
            action="retrieve_more", statement_id=report.statement_id,
            reason_code=code, next_query=_next_query(report, code),
        )

    if code in _REPAIR_CODES:
        return SupervisorDecision(
            action="repair", statement_id=report.statement_id, reason_code=code,
        )

    # 未指定原因：保守 abstain，不擅自扩大检索范围
    return SupervisorDecision(
        action="abstain", statement_id=report.statement_id,
        reason_code=code or "unsupported_entailment",
    )


def _primary_reason(report: ValidationReport) -> str:
    """取首个非 passed 的原因码；无原因时按 decision 推断。"""
    for reason in report.reasons or []:
        if reason.code and reason.code != "passed":
            return reason.code
    if not report.locator_valid:
        return "missing_source"
    if not report.quote_valid:
        return "quote_mismatch"
    if not report.scope_valid:
        return "wrong_scope"
    if report.numeric_status == "fail":
        return "numeric_mismatch"
    if report.qualifier_status == "fail":
        return "qualifier_missing"
    if report.semantic_status == "contradicts":
        return "contradiction"
    return ""


def _next_query(report: ValidationReport, code: str) -> Optional[str]:
    """补检索查询词：只从受控原因生成，不接受模型任意构造的检索范围。"""
    if code == "missing_source":
        return "原文证据"
    if code == "quote_mismatch":
        return "原文引用"
    if code == "ambiguous_page":
        return "页码"
    if code == "coordinate_missing":
        return "图表位置"
    return None


__all__ = ["decide"]
