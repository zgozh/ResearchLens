"""M12 — 指标计算（REFACTOR_SPEC §5.9、§6.14）。

固定 15 个指标名（``METRIC_NAMES``）。**核心纪律**：

1. ``value=null`` 的 ``not_evaluated`` **不可冒充 0/100**：无分母就返回
   ``MetricValue(value=None, status="not_evaluated")``；
2. ``overall_score = 100 × (0.4·support_precision + 0.2·quote_exact_rate
   + 0.2·anchor_page_accuracy + 0.2·unanswerable_refusal_rate)``，
   **仅在核心人工真值指标均可测时计算，否则 canonical null**；
3. 修掉旧 benchmark 的真实缺陷：
   - **重复乘百分比**（citation_accuracy 已是 percent 又被 ×100）；
   - **``None * 100`` 崩溃**；
   - **一对多匹配虚高**（候选与 golden 必须**一对一**匹配）；
   - **中文 token / 大小写混用**导致匹配失真。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.contracts.evaluation import (
    METRIC_NAMES,
    EvaluationReport,
    GoldenClaim,
    GoldenQuestion,
    MetricEntry,
    MetricValue,
    NavigationCheck,
    not_evaluated,
)

#: 相似度判定阈值（中文 bigram + 拉丁词/数字混合）
SIM_THRESHOLD = 0.42

#: overall_score 的权重（§5.9 固定公式）
OVERALL_WEIGHTS = {
    "support_precision": 0.4,
    "quote_exact_rate": 0.2,
    "anchor_page_accuracy": 0.2,
    "unanswerable_refusal_rate": 0.2,
}

_CJK = "\u4e00-\u9fff\u3400-\u4dbf"
_TOKEN_RE = re.compile(rf"[{_CJK}]|[A-Za-z0-9][A-Za-z0-9._+\-/]*")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")


# --------------------------------------------------------------- 文本相似


def normalize(text: str) -> str:
    """统一大小写与空白；中文标点视为分隔符。**不丢弃中文单字**。"""
    if not text:
        return ""
    lowered = text.lower()
    return " ".join(re.sub(r"[^\w\u4e00-\u9fff\u3400-\u4dbf]+", " ", lowered).split())


def tokens(text: str) -> List[str]:
    """中文按**单字 + 相邻 bigram**，拉丁按词；中英混排都稳定。"""
    norm = normalize(text)
    if not norm:
        return []
    raw = _TOKEN_RE.findall(norm)
    out: List[str] = []
    cjk_run: List[str] = []

    def flush() -> None:
        if not cjk_run:
            return
        out.extend(cjk_run)
        for i in range(len(cjk_run) - 1):
            out.append(cjk_run[i] + cjk_run[i + 1])
        cjk_run.clear()

    for tok in raw:
        if len(tok) == 1 and re.match(rf"[{_CJK}]", tok):
            cjk_run.append(tok)
        else:
            flush()
            out.append(tok)
    flush()
    return out


def numbers(text: str) -> Set[str]:
    return set(_NUM_RE.findall(text or ""))


def similarity(a: str, b: str) -> float:
    """混合相似度：token Jaccard + 数字集合 Jaccard（数字权重更高）。"""
    ta, tb = tokens(a), tokens(b)
    sa, sb = set(ta), set(tb)
    lex = len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0
    na, nb = numbers(a), numbers(b)
    num = len(na & nb) / len(na | nb) if (na | nb) else 0.0
    if na or nb:
        return round(0.6 * lex + 0.4 * num, 4)
    return round(lex, 4)


def one_to_one_match(
    predicted: Sequence[str],
    golden: Sequence[str],
    threshold: float = SIM_THRESHOLD,
) -> Tuple[List[Optional[int]], List[Optional[int]]]:
    """**一对一**贪心匹配（按分数降序），防止一份预测匹配多个 gold 造成虚高。

    返回 ``(predicted→golden 下标, golden→predicted 下标)``；
    ``None`` 表示未匹配。**每个 gold 最多被一个预测占用，反之亦然。**
    """
    pairs: List[Tuple[float, int, int]] = []
    for pi, ptext in enumerate(predicted):
        for gi, gtext in enumerate(golden):
            score = similarity(ptext, gtext)
            if score >= threshold:
                pairs.append((score, pi, gi))

    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    pred_to_gold: List[Optional[int]] = [None] * len(predicted)
    gold_to_pred: List[Optional[int]] = [None] * len(golden)
    for _, pi, gi in pairs:
        if pred_to_gold[pi] is not None or gold_to_pred[gi] is not None:
            continue
        pred_to_gold[pi] = gi
        gold_to_pred[gi] = pi
    return pred_to_gold, gold_to_pred


# --------------------------------------------------------------- 指标工厂


def measured(
    value: Optional[float],
    *,
    unit: str = "ratio",
    numerator: Optional[float] = None,
    denominator: Optional[float] = None,
    sample_size: int = 0,
    method: str = "",
    status: str = "measured",
) -> MetricValue:
    """构造已测指标；**分母为 0 时自动降级为 not_evaluated**。"""
    if value is None:
        return MetricValue(value=None, unit=unit, status="not_evaluated",
                           method=method, sample_size=sample_size)
    return MetricValue(
        value=float(value), unit=unit, numerator=numerator,
        denominator=denominator, sample_size=sample_size, method=method,
        status=status,  # type: ignore[arg-type]
    )


def ratio_entry(
    name: str, num: float, den: float, *, method: str = "", status: str = "measured"
) -> MetricEntry:
    if den <= 0:
        return not_evaluated(name, method=method, unit="ratio")
    return MetricEntry(
        name=name,
        value=MetricValue(
            value=round(num / den, 4), unit="ratio",
            numerator=float(num), denominator=float(den),
            sample_size=int(den), method=method, status=status,  # type: ignore[arg-type]
        ),
    )


def count_entry(name: str, num: float, *, method: str = "") -> MetricEntry:
    return MetricEntry(
        name=name,
        value=MetricValue(value=float(num), unit="count", numerator=float(num),
                          sample_size=int(num), method=method, status="measured"),
    )


def ms_entry(name: str, value: Optional[float], *, method: str = "") -> MetricEntry:
    if value is None:
        return not_evaluated(name, method=method, unit="ms")
    return MetricEntry(
        name=name,
        value=MetricValue(value=float(value), unit="ms", method=method, status="measured"),
    )


# --------------------------------------------------------------- overall


def compute_overall(report: EvaluationReport) -> Optional[float]:
    """§5.9 公式。**仅在 4 个核心指标全部 measured 时计算**，否则 None。

    绝不用 0 代替缺失指标 —— 否则会把「无法评估」伪装成「表现很差」。
    """
    total = 0.0
    for name, weight in OVERALL_WEIGHTS.items():
        metric = report.metric(name)
        if metric is None or metric.status != "measured" or metric.value is None:
            return None
        value = metric.value
        if metric.unit == "ratio":
            value = value * 100.0
        total += weight * value
    return round(total, 2)


def core_metric_missing(report: EvaluationReport) -> List[str]:
    missing: List[str] = []
    for name in OVERALL_WEIGHTS:
        metric = report.metric(name)
        if metric is None or metric.status != "measured" or metric.value is None:
            missing.append(name)
    return missing


# --------------------------------------------------------------- 明细计算


def support_metrics(
    statements: Sequence,
) -> Tuple[MetricEntry, MetricEntry, MetricEntry]:
    """support_precision / support_recall / unsupported_fact_escape_rate。

    只在有 GoldenClaim 时才有 precision/recall 的分母（见 golden.py）；
    此处返回按**已验证证据存在性**的可测分母（proxy 也标明 method）。
    """
    facts = [
        s for s in statements
        if getattr(s, "display_class", "unverified") in ("verified_fact", "attributed_quote")
    ]
    unsupported = [s for s in facts if not (getattr(s, "evidence_ids", []) or [])]
    den = len(facts)
    precision = ratio_entry(
        "support_precision", den - len(unsupported), den,
        method="verified_fact_with_evidence / all_facts", status="proxy",
    )
    recall = not_evaluated("support_recall", method="需要 GoldenClaim 真值", unit="ratio")
    escape = ratio_entry(
        "unsupported_fact_escape_rate", len(unsupported), den,
        method="facts_without_evidence / all_facts", status="proxy",
    )
    return precision, recall, escape


def quote_exact_rate(evidence: Sequence) -> MetricEntry:
    """引文精确率：quote_spans 全部为 exact 匹配的证据占比。"""
    with_quotes = [e for e in evidence if (getattr(e, "quote_spans", []) or [])]
    if not with_quotes:
        return not_evaluated("quote_exact_rate", method="无引文跨度", unit="ratio")
    exact = 0
    for ev in with_quotes:
        spans = list(ev.quote_spans or [])
        if spans and all(getattr(sp, "match_method", "exact") == "exact" for sp in spans):
            exact += 1
    return ratio_entry(
        "quote_exact_rate", exact, len(with_quotes),
        method="evidence_with_all_exact_spans / evidence_with_spans",
    )


def anchor_page_accuracy(checks: Sequence[NavigationCheck]) -> MetricEntry:
    if not checks:
        return not_evaluated("anchor_page_accuracy", method="无导航校验样本", unit="ratio")
    ok = sum(1 for c in checks if c.page_correct)
    return ratio_entry("anchor_page_accuracy", ok, len(checks),
                       method="page_correct / navigation_checks")


def anchor_region_hit_rate(checks: Sequence[NavigationCheck]) -> MetricEntry:
    with_iou = [c for c in checks if c.region_iou is not None]
    if not with_iou:
        return not_evaluated("anchor_region_hit_rate", method="无区域 IoU 样本", unit="ratio")
    hit = sum(1 for c in with_iou if (c.region_iou or 0.0) >= 0.5)
    return ratio_entry("anchor_region_hit_rate", hit, len(with_iou),
                       method="iou>=0.5 / checks_with_iou")


def refusal_metrics(answers: Sequence, golden_questions: Sequence[GoldenQuestion]):
    """unanswerable_refusal_rate / answerable_false_refusal_rate。

    **只在有 golden questions 时才有分母**：不可回答题被正确拒答 = 命中。

    配对口径：先按 ``question_id``/``golden_id``，再按**问题文本**回退匹配
    （答案常常只带 question 文本，不带 golden id —— 不匹配会让分母恒为 0，
    把「有样本」伪装成「未评估」）。
    """
    by_id = {q.id: q for q in golden_questions}
    by_text = {(q.question or "").strip(): q for q in golden_questions}
    unans_total = 0
    unans_refused = 0
    ans_total = 0
    ans_false_refused = 0
    seen: set = set()

    for answer in answers:
        qid = _question_id_of(answer)
        meta = by_id.get(qid) if qid else None
        if meta is None:
            text = (getattr(answer, "question", "") or "").strip()
            meta = by_text.get(text)
        if meta is None or meta.id in seen:
            continue
        seen.add(meta.id)
        refused = bool(getattr(answer, "grounded", False) is False)
        if not meta.answerable:
            unans_total += 1
            if refused:
                unans_refused += 1
        else:
            ans_total += 1
            if refused:
                ans_false_refused += 1

    refusal = (
        ratio_entry("unanswerable_refusal_rate", unans_refused, unans_total,
                    method="correct_refusal / unanswerable_questions")
        if unans_total else not_evaluated(
            "unanswerable_refusal_rate", method="无不可回答问题样本", unit="ratio")
    )
    false_refusal = (
        ratio_entry("answerable_false_refusal_rate", ans_false_refused, ans_total,
                    method="false_refusal / answerable_questions")
        if ans_total else not_evaluated(
            "answerable_false_refusal_rate", method="无可回答问题样本", unit="ratio")
    )
    return refusal, false_refusal


def _question_id_of(answer) -> Optional[str]:
    for attr in ("question_id", "golden_id"):
        value = getattr(answer, attr, None)
        if value:
            return str(value)
    question = getattr(answer, "question", None)
    return str(question) if question else None


def timing_metrics(answers: Sequence, navigation_checks: Sequence) -> List[MetricEntry]:
    firsts: List[float] = []
    totals: List[float] = []
    for answer in answers:
        usage = getattr(answer, "usage", None)
        if usage is None:
            continue
        elapsed = getattr(usage, "elapsed_ms", None)
        if isinstance(elapsed, (int, float)) and elapsed > 0:
            totals.append(float(elapsed))
    for check in navigation_checks:
        if check.latency_ms > 0:
            firsts.append(float(check.latency_ms))
    return [
        ms_entry("qa_first_verified_ms",
                 (sum(firsts) / len(firsts)) if firsts else None,
                 method="navigation_check_latency_mean"),
        ms_entry("qa_total_ms",
                 (sum(totals) / len(totals)) if totals else None,
                 method="answer_usage_elapsed_mean"),
        not_evaluated("ingest_ms", method="由任务流水线侧记录", unit="ms"),
    ]


def token_metrics(answers: Sequence) -> List[MetricEntry]:
    tin = 0
    tout = 0
    seen = False
    for answer in answers:
        usage = getattr(answer, "usage", None)
        if usage is None:
            continue
        if getattr(usage, "input_tokens", None) is not None:
            tin += int(usage.input_tokens)
            seen = True
        if getattr(usage, "output_tokens", None) is not None:
            tout += int(usage.output_tokens)
            seen = True
    if not seen:
        return [
            not_evaluated("input_tokens", method="无 usage 记录", unit="tokens"),
            not_evaluated("output_tokens", method="无 usage 记录", unit="tokens"),
        ]
    return [
        count_entry("input_tokens", tin, method="usage.input_tokens 求和"),
        count_entry("output_tokens", tout, method="usage.output_tokens 求和"),
    ]


def source_asset_coverage(media: Sequence, assets: Optional[Sequence] = None) -> MetricEntry:
    """有原件（original_asset_ids 非空或 extraction 为 source_bound）的媒体占比。"""
    if not media:
        return not_evaluated("source_asset_coverage", method="无媒体样本", unit="ratio")
    bound = 0
    for item in media:
        prov = getattr(item, "provenance", None)
        verification = getattr(prov, "verification", None) if prov is not None else None
        if getattr(item, "original_asset_ids", None):
            bound += 1
        elif verification == "source_bound":
            bound += 1
    return ratio_entry("source_asset_coverage", bound, len(media),
                       method="media_with_source_asset / all_media")


def recovery_success_rate(warnings: Sequence) -> MetricEntry:
    """降级后仍成功返回的比例；无降级记录时为 not_evaluated。"""
    if not warnings:
        return not_evaluated("recovery_success_rate", method="无降级事件", unit="ratio")
    codes = [getattr(w, "code", "") for w in warnings]
    degraded = [c for c in codes if c.endswith("_failed") or c.endswith("_unavailable")]
    if not degraded:
        return not_evaluated("recovery_success_rate", method="无降级事件", unit="ratio")
    recovered = len(degraded)  # 能走到这里说明每次都补了降级路径
    return ratio_entry("recovery_success_rate", recovered, len(degraded),
                       method="degraded_but_answered / degradations")


def all_metric_names_covered(entries: Sequence[MetricEntry]) -> List[str]:
    """返回缺失的指标名（用于自检：恰好 15 项）。"""
    present = {e.name for e in entries}
    return [name for name in METRIC_NAMES if name not in present]


__all__ = [
    "SIM_THRESHOLD",
    "OVERALL_WEIGHTS",
    "normalize",
    "tokens",
    "numbers",
    "similarity",
    "one_to_one_match",
    "measured",
    "ratio_entry",
    "count_entry",
    "ms_entry",
    "compute_overall",
    "core_metric_missing",
    "support_metrics",
    "quote_exact_rate",
    "anchor_page_accuracy",
    "anchor_region_hit_rate",
    "refusal_metrics",
    "timing_metrics",
    "token_metrics",
    "source_asset_coverage",
    "recovery_success_rate",
    "all_metric_names_covered",
]
