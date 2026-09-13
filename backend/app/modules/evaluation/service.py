"""M12 — 自动评测模块公共入口（REFACTOR_SPEC §5.9、§5.10、§6.14）。

公共函数：
- ``compute(input: EvaluationInput, ctx) -> EvaluationReport``
- ``get(scope) -> EvaluationReport``
- ``run_golden(input: EvaluationInput, ctx) -> EvaluationReport``

硬约束：
1. **M12 不调用 pipeline**，只接收 ``EvaluationInput``（数据由调用方备好）；
2. 固定 15 个指标名；``value=null`` 的 ``not_evaluated`` **不可冒充 0/100**；
3. ``overall_score`` **仅在核心人工真值指标均可测时计算**，否则 canonical null；
4. ``get`` **不计算、不写库**；不存在论文 → 404。
"""
from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional, Sequence, Tuple

from app.contracts.common import CallContext, Scope, Warning
from app.contracts.evaluation import (
    METRIC_NAMES,
    EvaluationInput,
    EvaluationReport,
    GoldenClaim,
    GoldenSet,
    MetricEntry,
    MetricValue,
    NavigationCheck,
    not_evaluated,
)
from app.core.db import session_scope
from app.core.errors import invalid_input, not_found, revision_mismatch

from . import golden as golden_mod
from . import metrics as M
from . import repository as repo

log = logging.getLogger("researchlens.evaluation")

#: 评测算法版本（进入评测版本）
ALGORITHM_VERSION = "rl.eval/2"


# =============================================================== compute


def compute(
    input: EvaluationInput,
    ctx: Optional[CallContext] = None,
) -> EvaluationReport:
    """计算 15 项指标并持久化报告。**不调用 pipeline、不触发生成。**"""
    scope = input.scope
    _require_scope(scope)
    warnings: List[Warning] = []

    golden_set = input.golden
    if golden_set is not None and not golden_mod.golden_scope_ok(
        golden_set, scope.paper_id, scope.revision_id
    ):
        warnings.append(Warning(
            code="golden_scope_mismatch",
            message="真值集与当前 scope 不同源，本次不用于精确率/召回率计算",
            stage="evaluation",
        ))
        golden_set = None

    entries = _compute_entries(input, golden_set, warnings, ctx)

    report = EvaluationReport(
        scope=scope,
        id=_report_id(scope.revision_id, getattr(golden_set, "id", None)),
        # **必须显式盖章**：不写这一行就会用契约默认值 `rl.eval/1`，
        # 于是报告永远自称旧版本（实测：算法已到 rl.eval/2，落库仍是 rl.eval/1），
        # 任何"按版本判断报告是否过期"的逻辑都会失效。
        version=ALGORITHM_VERSION,
        overall_score=None,
        metrics=entries,
        golden_id=getattr(golden_set, "id", None),
        computed_at=None,
        warnings=warnings,
    )

    # R4-M5（ADR D-105）：`overall_score` 就是**主分「AI 质量评分（自动）」**，
    # 用 AI 口径算（四项核心指标"可用"即可，support_precision 允许 AI 裁判 proxy 参与）。
    # 人工口径函数 `compute_overall` / `core_metric_missing` 已随决策 3 删除。
    ai_score = M.compute_ai_overall(report)
    report = report.model_copy(update={
        "overall_score": ai_score,
        # 来源标注（决策底线 2）：AI 判定 ≠ 客观测量，必须写明。
        "overall_score_basis": "ai_generated" if ai_score is not None else None,
        # 已废弃字段：与主分同值，保留一个版本周期供旧消费方过渡。
        "ai_overall_score": ai_score,
    })

    missing_core = M.ai_core_metric_missing(report)
    if missing_core:
        report = report.model_copy(update={
            "warnings": report.warnings + [Warning(
                code="ai_overall_not_evaluated",
                message=(
                    "AI 质量评分暂不可用（核心指标缺失，**不以 0 冒充**）："
                    + ", ".join(missing_core)
                ),
                stage="evaluation",
            )]
        })

    from app.core.clock import utc_now

    report = report.model_copy(update={"computed_at": utc_now()})
    _persist(report)
    return report


def run_golden(
    input: EvaluationInput,
    ctx: Optional[CallContext] = None,
) -> EvaluationReport:
    """在 golden 真值下运行评测：核心指标从 proxy 升级为 measured。"""
    if input.golden is None:
        raise invalid_input("run_golden 需要提供 golden 真值集", field="golden")
    return compute(input, ctx)


def _ingest_ms(scope: Scope) -> Optional[float]:
    """入库时延：该 revision 最近一次**成功作业**的 ``created_at→updated_at``。

    真实数据（作业表），不是估算；拿不到就返回 ``None``，由 ``ms_entry`` 降级为
    ``not_evaluated``——**绝不用 0 冒充**（ADR-0046 的同一纪律）。
    """
    try:
        from sqlalchemy import select

        from app.core.db import session_scope
        from app.models.jobs import JobORM

        with session_scope() as db:
            row = db.execute(
                select(JobORM)
                .where(
                    JobORM.revision_id == scope.revision_id,
                    JobORM.state.in_(("succeeded", "partial")),
                )
                .order_by(JobORM.updated_at.desc())
                .limit(1)
            ).scalars().first()
            if row is None or row.created_at is None or row.updated_at is None:
                return None
            return max(0.0, (row.updated_at - row.created_at).total_seconds() * 1000.0)
    except Exception:  # noqa: BLE001 - 作业表不可读不得让评测 500
        return None


def _compute_entries(
    input: EvaluationInput,
    golden_set: Optional[GoldenSet],
    warnings: List[Warning],
    ctx: Optional[CallContext] = None,
) -> List[MetricEntry]:
    """按固定 15 项构建指标；**missing 一律 not_evaluated，不填 0**。"""
    entries: Dict[str, MetricEntry] = {}

    # ---- 证据与断言（可能来自 golden 的精确率/召回率）
    statements = list(input.statements or [])
    predicted_texts = _predicted_texts(input)
    predicted_ok = [
        bool(getattr(s, "evidence_ids", []) or [])
        for s in statements
        if getattr(s, "display_class", "unverified") in ("verified_fact", "attributed_quote")
    ]

    if golden_set is not None and golden_set.claims:
        precision, recall = golden_mod.support_precision_recall(
            predicted_texts, list(golden_set.claims), predicted_ok=predicted_ok,
        )
        # R4-M5（ADR D-105）：**"调参集 vs 人工确认集"的分叉已删除** ——
        # 产品里不再有人工确认环节，金标集只剩一种形态：AI 从原文构造。
        # 因此支持度一律走 **AI 裁判按语义判等**（数值可见，状态仍是 proxy，不是 measured）。
        #
        # 背景（保留，因为解释了"为什么必须让 AI 判"）："未评测"的技术卡点是文本相似度
        # —— 预测与参考常是"同一事实不同措辞"，实测最高相似度 0.21（不是阈值问题，ADR-0052）。
        judged = _ai_judged_support(
            input, predicted_texts, predicted_ok, list(golden_set.claims), ctx, warnings,
        )
        if judged is not None:
            entries["support_precision"], entries["support_recall"] = judged
        else:
            proxy = ""
            for entry in (precision, recall):
                if entry.value.value is not None:
                    proxy += f"{entry.name}={entry.value.value:.3f} "
            # 纯**说明性**告警（不含任何"待人工确认"语义）：AI 裁判这次没给出结论。
            warnings.append(Warning(
                code="golden_ai_constructed",
                message=(
                    "金标集由 AI 从原文构造，评分为 **AI 口径**（非人工评审）；"
                    "AI 裁判本次未给出结论，support_precision/recall 标为未评测，"
                    f"主分保持 null（文本相似度参考：{proxy.strip() or 'n/a'}）"
                ),
                stage="evaluation",
            ))
            entries["support_precision"] = not_evaluated(
                "support_precision",
                method="AI 裁判未出结论（不以 0 冒充）", unit="ratio",
            )
            entries["support_recall"] = not_evaluated(
                "support_recall",
                method="AI 裁判未出结论（不以 0 冒充）", unit="ratio",
            )
    else:
        precision, recall, escape = M.support_metrics(statements)
        entries["support_precision"] = precision
        entries["support_recall"] = recall
        entries["unsupported_fact_escape_rate"] = escape

    if "unsupported_fact_escape_rate" not in entries:
        _, _, escape = M.support_metrics(statements)
        entries["unsupported_fact_escape_rate"] = escape

    # ---- 引文与锚点
    entries["quote_exact_rate"] = M.quote_exact_rate(_all_evidence(input))
    checks = list(input.navigation_checks or [])
    entries["anchor_page_accuracy"] = M.anchor_page_accuracy(checks)
    entries["anchor_region_hit_rate"] = M.anchor_region_hit_rate(checks)

    # ---- 不可答题的**诚实率**（R4-M3 / ADR D-106；旧 `*_refusal_*` 指标已删除）
    golden_questions = list(golden_set.questions) if golden_set is not None else []
    entries["unanswerable_honesty_rate"] = M.honesty_metrics(
        list(input.answers or []), golden_questions
    )

    # ---- 资产覆盖
    entries["source_asset_coverage"] = M.source_asset_coverage(list(input.media or []))

    # ---- 时延 / token
    # ``timing_metrics`` 不再收 navigation_checks：那是**页面跳转**的时延，
    # 此前被当成"首个经验证答案句耗时"，口径不对（详情见 metrics.timing_metrics）。
    for entry in M.timing_metrics(
        list(input.answers or []), ingest_ms=_ingest_ms(input.scope)
    ):
        entries[entry.name] = entry
    for entry in M.token_metrics(list(input.answers or [])):
        entries[entry.name] = entry

    # ---- 恢复率：按**答案粒度**统计"降级后仍交付"（旧实现只传 warnings，判不了交付）
    entries["recovery_success_rate"] = M.recovery_success_rate(list(input.answers or []))

    # ---- 严格按 METRIC_NAMES 顺序输出，缺失项显式 not_evaluated
    out: List[MetricEntry] = []
    for name in METRIC_NAMES:
        out.append(entries.get(name) or not_evaluated(name, method="本次输入未提供该指标数据"))
    return out


def _all_evidence(input: EvaluationInput) -> List:
    """从 statements 关联的证据与 bindings 中收集证据对象（用于引文精确率）。"""
    from app.contracts.evidence import EvidenceRecord

    out: List = []
    seen: set = set()
    for answer in (input.answers or []):
        for ev in (getattr(answer, "evidence", []) or []):
            eid = getattr(ev, "id", None)
            if eid and eid not in seen and isinstance(ev, EvidenceRecord):
                seen.add(eid)
                out.append(ev)
    return out


def _persist(report: EvaluationReport) -> None:
    payload = report.model_dump(mode="json")
    try:
        with session_scope() as db:
            repo.insert_report(
                db,
                report_id=report.id,
                paper_id=report.scope.paper_id,
                revision_id=report.scope.revision_id,
                version=report.version,
                overall_score=report.overall_score,
                metrics=payload.get("metrics", []),
                golden_id=report.golden_id,
                warnings=payload.get("warnings", []),
            )
    except Exception as exc:  # noqa: BLE001  落库失败不回滚已算好的报告
        # **不许静默**：旧实现这里是裸 `pass`，把"重复主键 → 报告永远停在第一次"
        # 藏了整整一天（界面显示过期的 0、两个数据源不一致）。现在至少留下痕迹。
        log.warning(
            "评测报告落库失败（本次结果仍返回，但下次读到的还是旧报告）：%s: %s",
            type(exc).__name__, exc,
        )


# =============================================================== get


def get(scope: Scope) -> EvaluationReport:
    """读取最近一次持久化报告。**不计算、不写库**；无报告返回全 not_evaluated。"""
    _require_scope(scope)

    with session_scope() as db:
        row = repo.latest_report(db, scope.revision_id)

    if row is None:
        return EvaluationReport(
            scope=scope,
            id=_report_id(scope.revision_id, None),
            version=ALGORITHM_VERSION,
            overall_score=None,
            metrics=[not_evaluated(n, method="尚无评测报告") for n in METRIC_NAMES],
            golden_id=None,
            computed_at=None,
            warnings=[Warning(
                code="evaluation_absent",
                message="该 revision 尚无评测报告；指标一律为 not_evaluated",
                stage="evaluation",
            )],
        )

    entries: List[MetricEntry] = []
    stored = {m.get("name"): m for m in (row.metrics or []) if isinstance(m, dict)}
    for name in METRIC_NAMES:
        raw = stored.get(name)
        if raw is None:
            entries.append(not_evaluated(name, method="报告未包含该指标"))
            continue
        try:
            entries.append(MetricEntry.model_validate(raw))
        except Exception:  # noqa: BLE001  脏条目降级为 not_evaluated
            entries.append(not_evaluated(name, method="指标条目不可解析"))

    return EvaluationReport(
        scope=scope,
        id=row.id,
        version=row.version or "rl.eval/1",
        overall_score=row.overall_score,     # None 就是 None，绝不写成 0
        metrics=entries,
        golden_id=row.golden_id,
        computed_at=row.computed_at,
        warnings=_warnings_from(row.warnings),
    )


def _is_current(report: EvaluationReport) -> bool:
    """报告是否"当前"：版本一致 **且** 15 个指标名一个不缺。

    为什么两条都要：版本换代时旧数字不可比；而**新增指标**（如
    `recovery_success_rate` / 改名后的 `unanswerable_honesty_rate`）在旧报告里
    根本没有 —— 那种报告读出来就是"报告未包含该指标"，正是界面显示的
    「未评测：报告未包含该指标」。
    """
    if (report.version or "") != ALGORITHM_VERSION:
        return False
    have = {e.name for e in report.metrics}
    return all(name in have for name in METRIC_NAMES)


def get_current(scope: Scope) -> EvaluationReport:
    """**读评测报告的唯一入口**：读到过期就地重算，绝不把旧数字当权威。

    为什么要它（实测事故 2026-09-13）：`/exhibits` 走 `get()`（读持久化），
    `/evaluation` 走重算 —— 两个入口给出两套数（canonical: support_precision **0.0**、
    报告停在 `rl.eval/1`；现算: 0.8571）。两个请求还是**并行**发出的，
    于是首屏必然打架：前端报"两个数据源不一致"，用户看到过期的 0。

    重算沿用 legacy 的输入装配（AI 裁判按 digest 复用缓存，正常不产生新的云调用），
    与 `/evaluation` 完全同源。
    """
    stored = get(scope)
    if _is_current(stored):
        return stored

    from app.core.db import session_scope

    from . import legacy as legacy_mod

    try:
        with session_scope() as db:
            cached = legacy_mod._cached_ai_judge(legacy_mod._latest_row(db, scope.paper_id))
        inp = legacy_mod._input_for(scope, ai_judge=cached)
        fresh = compute(inp, legacy_mod._judge_ctx(scope))
        log.info(
            "评测报告过期（stored=%s / 期望 %s），已就地重算：paper=%s revision=%s",
            stored.version, ALGORITHM_VERSION, scope.paper_id, scope.revision_id,
        )
        return fresh
    except Exception as exc:  # noqa: BLE001
        # 重算失败宁可如实返回旧报告（带 warning），也不许静默当成"没问题"
        log.warning("评测报告重算失败，暂返回旧报告：%s: %s", type(exc).__name__, exc)
        return stored.model_copy(update={
            "warnings": list(stored.warnings) + [Warning(
                code="evaluation_stale",
                message=(
                    f"持久化报告版本为 {stored.version}（当前 {ALGORITHM_VERSION}）"
                    f"且重算失败，以下数字可能过期：{type(exc).__name__}"
                ),
                stage="evaluation",
            )]
        })


def _warnings_from(raw) -> List[Warning]:
    out: List[Warning] = []
    for item in (raw or []):
        if isinstance(item, dict):
            try:
                out.append(Warning.model_validate(item))
            except Exception:  # noqa: BLE001
                continue
    return out


# =============================================================== 辅助


def _predicted_texts(input: EvaluationInput) -> List[str]:
    """进入精确率/召回率的预测断言文本（只看对外展示的展示类）。"""
    return [
        getattr(s, "text", "") for s in list(input.statements or [])
        if getattr(s, "display_class", "unverified") in ("verified_fact", "attributed_quote")
    ]


def ai_judge_digest_for(input: EvaluationInput) -> Optional[str]:
    """当前输入的 AI 裁判摘要（无 golden 时为 ``None``）。

    供 **缓存层**（``legacy.compute_evaluation``）判断"这次能不能复用上次的裁判结论"，
    用的抽取口径必须与 ``_compute_entries`` 完全一致，否则会出现"永远缓存不命中"
    或更糟的"用旧结论套新断言"。
    """
    golden = input.golden
    if golden is None or not golden.claims:
        return None
    from . import ai_grader

    return ai_grader.judge_digest(_predicted_texts(input), [c.text for c in golden.claims])


def _ai_judged_support(
    input: EvaluationInput,
    predicted_texts: List[str],
    predicted_ok: List[bool],
    golden_claims: List[GoldenClaim],
    ctx: Optional[CallContext],
    warnings: List[Warning],
) -> Optional[Tuple[MetricEntry, MetricEntry]]:
    """用 AI 裁判给出 support_precision/recall（``proxy``）—— 可能返回 ``None``。

    取数顺序（ADR-0056）：
    1. ``input.ai_judge`` 且**摘要匹配** → 直接用（不花云调用）；
    2. 否则 ``ctx`` 可用且配置了模型 → 调 LLM 裁判；
    3. 都不行 → ``None``，调用方如实降级为 ``not_evaluated``（**不用 0 冒充**）。
    """
    from . import ai_grader

    golden_texts = [c.text for c in golden_claims]
    digest = ai_grader.judge_digest(predicted_texts, golden_texts)

    cached = input.ai_judge
    if cached is not None and cached.digest and cached.digest == digest:
        # **缓存复用时必须直接用持久化的真阳性计数**：持久化时不回写配对，
        # 用 ``matches`` 重算会得到 0，把好数据写坏（这是真实踩过的坑，见 ADR-0056）。
        tp = int(cached.true_positive or 0)
        total_predicted = cached.total_predicted or len(predicted_texts)
        total_golden = cached.total_golden or len(golden_texts)
        method_suffix = "cached"
    else:
        if ctx is None:
            return None
        result = ai_grader.judge_support(predicted_texts, golden_texts, ctx)
        if result is None:
            return None
        result.digest = digest
        matched = {p for p, _ in result.matches}
        tp = sum(1 for idx in matched if idx < len(predicted_ok) and predicted_ok[idx])
        result.true_positive = tp
        total_predicted = len(predicted_texts)
        total_golden = len(golden_texts)
        method_suffix = result.model or "llm"

    method = f"ai_judge_semantic_match（{ai_grader.AI_JUDGE_VERSION} / {method_suffix}）"
    precision = M.ratio_entry(
        "support_precision", tp, total_predicted, method=method, status="proxy",
    )
    recall = M.ratio_entry(
        "support_recall", tp, total_golden, method=method, status="proxy",
    )
    warnings.append(Warning(
        code="support_metrics_ai_judged",
        message=(
            f"金标集为机器调参集，support_precision/recall 由 **LLM 语义裁判**判等得出"
            f"（proxy，非人工真值；命中 {tp}/{total_predicted} 条预测，"
            f"参考 {total_golden} 条）。综合评分请区分两种口径："
            f"``overall_score`` 仍要求人工真值，``ai_overall_score`` 是 AI 口径。"
        ),
        stage="evaluation",
    ))
    return precision, recall


def _report_id(revision_id: str, golden_id: Optional[str]) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"researchlens:eval:{revision_id}:{golden_id or 'none'}:{ALGORITHM_VERSION}",
    ))


def _require_scope(scope: Scope) -> None:
    from app.models.source import RevisionORM

    if scope.paper_id <= 0 or not scope.revision_id:
        raise invalid_input("scope 非法")
    with session_scope() as db:
        row = db.get(RevisionORM, scope.revision_id)
        if row is None:
            raise not_found("revision 不存在")
        if row.paper_id != scope.paper_id:
            raise revision_mismatch("revision 不属于该 paper")


__all__ = ["compute", "get", "run_golden", "ALGORITHM_VERSION"]
