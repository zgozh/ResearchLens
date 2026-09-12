"""M04 — Evidence Gate 决策逻辑（REFACTOR_SPEC §5.4、§6.6）。

**Gate 顺序固定，不可调换**：

    范围/身份 → 原文精确或可回溯规范化匹配 → 页/区域
    → 数字/单位/条件 → 语义支持 → decision

硬规则（违反即视为重构失败）：

1. ``source_text`` 由服务端从原文 Block 拼接，**绝不用 LLM 给出的 quote 当原文**；
2. 同页 / 正则 / 图号字符串只能产生 **candidate**，不能直接 certified；
3. **定位成功 ≠ 支持成立**：``locator_valid`` 与 ``semantic_status`` 完全独立判定；
4. ``locator_status`` 只能是 ``exact`` 或 ``page_only``；page-only 必须
   ``rect=None`` / ``quads=[]``；
5. 无 LLM 时语义 gate **不自动通过**（只允许确定性规则强放行，否则 insufficient）；
6. 不得只以"evidence 非空"或"模型自报 confidence"判 verified；
7. assessment 是**纯函数**：不写库、不调云调用。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from app.contracts.common import Id, Scope, Warning
from app.contracts.documents import Anchor, AnchorSegment, Block, QuoteSpan
from app.contracts.evidence import (
    CitationCandidate,
    EvidenceRecord,
    ReviewRecord,
    StatementDraft,
    ValidationReason,
    ValidationReport,
)

from . import locator
from .locator import QuoteMatch

#: 规则评估器版本（进入 ValidationReport.assessor_version）
RULE_ASSESSOR_VERSION = "rl.gate/1"

#: 区域级判断：segment 有 rect 才算 region precision
DEFAULT_RULE_CONFIDENCE = 0.6


@dataclass
class GateInput:
    """Gate 的纯输入：已解析好的原文世界（不携带 Session）。"""

    scope: Scope
    #: block_id -> Block
    blocks: Dict[str, Block]
    #: block_id -> (page_id, pdf_page_index, page_label)
    page_of_block: Dict[str, locator.PageRef] = field(default_factory=dict)
    #: block_id -> anchor_id（解析模块落库时写入）
    anchor_of_block: Dict[str, str] = field(default_factory=dict)
    #: media_id -> 该 media 关联的 (page_index, anchor_ids)
    media_pages: Dict[str, int] = field(default_factory=dict)
    media_anchors: Dict[str, List[str]] = field(default_factory=dict)
    #: 允许的 media 白名单（本 scope 内存在的 media_id）
    allowed_media: set = field(default_factory=set)
    source_document_id: str = ""
    #: LLM 是否可用（决定语义 gate 能否走模型；无 LLM 不自动通过）
    llm_available: bool = False
    #: 模型对"是否支持"的判定（None=未评估/不可用）
    semantic_model_verdict: Optional[str] = None
    semantic_model_confidence: Optional[float] = None
    #: 模型给出的**理由**（M5：界面上的"未支持"必须能解释为什么，不能只有结论）
    semantic_model_reason: str = ""
    warnings: List[Warning] = field(default_factory=list)


@dataclass
class CandidateEvidence:
    """候选证据：定位已解出，但**支持关系尚未成立**。"""

    block_id: str
    quote_span: Optional[QuoteSpan]
    locator_status: str          # exact | page_only
    match_kind: str              # exact | normalized | fuzzy
    page_id: str
    pdf_page_index: int
    page_label: Optional[str]
    source_text: str
    anchor_id: str
    media_ids: List[str] = field(default_factory=list)
    rect: Optional[List[float]] = None
    quads: List[List[List[float]]] = field(default_factory=list)
    page_only: bool = False      # 未定位到具体引用块，仅知道页
    candidate_only: bool = False  # 同页/正则/模糊，只能作候选
    reason: str = ""


# --------------------------------------------------------------- reason 工具


def _reason(code: str, message: str, block_ids: Optional[Sequence[str]] = None) -> ValidationReason:
    return ValidationReason(code=code, message=message, block_ids=list(block_ids or []))


def _has_contradiction_marker(text: str) -> bool:
    """检测**明确表达相反结论**的措辞（用于无模型的保守降级判定）。

    纪律：只保留"断言了相反关系"的短语。
    原先还包含 "并未/并非/无法/然而/但是/不同/不支持" 等中文常用词，实测在
    真实中文论文上把 11/35 条正常陈述误判成 ``contradicts``（decision=contested），
    因为它们大量出现在**方法陈述本身**中（例如"但仅建模局部线性邻域关系"、
    "统计不稳定"、"与 LV 等线性指标不同"）。
    误判"矛盾"比"无法判定"更有害——它主动断言了相反关系，会污染图谱与讲解。
    因此这里收紧为**结论级**的相反表述；语义归属交给 M05 模型判定
    （``evidence.semantic.judge``）。

    注意：本条只在**模型未给出判定**时生效；模型判定优先级更高。
    """
    lowered = (text or "").lower()
    markers = (
        "no evidence", "contradicts", "on the contrary", "fails to",
        "与上述结论相反", "结果相反", "结论相反", "恰恰相反", "与此相反",
        "无法复现", "不能复现", "并不支持该结论",
    )
    return any(m in lowered for m in markers)


# --------------------------------------------------------------- 候选构造


def build_candidates(
    citation: CitationCandidate, gate: GateInput
) -> Tuple[List[CandidateEvidence], List[ValidationReason]]:
    """把一条 CitationCandidate 解成候选证据（定位层，不含支持判定）。"""
    reasons: List[ValidationReason] = []
    block = gate.blocks.get(citation.block_id)
    if block is None:
        reasons.append(
            _reason("missing_source", "引用指向的 block 不在本 revision 原文中",
                    [citation.block_id])
        )
        return [], reasons

    match: QuoteMatch = locator.match_quote(block, citation.proposed_quote)
    page_ref = gate.page_of_block.get(block.id)
    if page_ref is None:
        reasons.append(_reason("ambiguous_page", "该 block 没有确定的物理页", [block.id]))
        return [], reasons

    if match.is_precise and match.span is not None:
        span = match.span
        cand = CandidateEvidence(
            block_id=block.id,
            quote_span=span,
            locator_status="exact",
            match_kind=match.kind,
            page_id=page_ref.page_id,
            pdf_page_index=page_ref.pdf_page_index,
            page_label=page_ref.page_label,
            # 服务端从原文切片，绝不使用 LLM 的 proposed_quote
            source_text=span.source_text,
            anchor_id=gate.anchor_of_block.get(block.id, ""),
            media_ids=([citation.media_id] if citation.media_id in gate.allowed_media else []),
            rect=None,
            quads=[],
        )
        if candidate_media_is_untrusted(citation, gate):
            reasons.append(
                _reason("coordinate_missing", "引用的 media 不在本 scope 内，已忽略", [block.id])
            )
        return [cand], reasons

    if match.kind == "fuzzy":
        # 模糊只产生候选：locator 不成立，不能成为 certified 证据
        reasons.append(
            _reason("quote_mismatch", "引用与原文仅字面相似，只能作为候选", [block.id])
        )
        return [], reasons

    reasons.append(
        _reason("quote_mismatch", "引用的原文片段在该 block 中找不到", [block.id])
    )
    return [], reasons


def candidate_media_is_untrusted(citation: CitationCandidate, gate: GateInput) -> bool:
    return bool(citation.media_id) and citation.media_id not in gate.allowed_media


def page_only_candidate(page_ref: locator.PageRef, *, anchor_id: str = "") -> CandidateEvidence:
    """页级候选：只知道物理页，没有引用块。

    page-only 必须 rect=None / quads=[]（契约硬约束），且不得声称精准定位。
    """
    return CandidateEvidence(
        block_id="",
        quote_span=None,
        locator_status="page_only",
        match_kind="page_only",
        page_id=page_ref.page_id,
        pdf_page_index=page_ref.pdf_page_index,
        page_label=page_ref.page_label,
        source_text="",
        anchor_id=anchor_id,
        rect=None,
        quads=[],
        page_only=True,
        candidate_only=True,
        reason="仅同页/页级依据，不构成精准定位",
    )


# --------------------------------------------------------------- 语义 gate


def semantic_verdict(
    draft: StatementDraft, evidence_text: str, gate: GateInput
) -> Tuple[str, Optional[float], str]:
    """语义支持判定（**绝不因"有证据"就自动通过**）。

    返回 ``(status, confidence, reason_message)``，status 取自
    ``supports / contradicts / insufficient / unreviewed``。
    """
    statement = (draft.text or "").strip()
    evidence = (evidence_text or "").strip()
    if not statement:
        return "insufficient", None, "陈述为空"
    if not evidence:
        return "insufficient", None, "证据原文为空"

    # 陈述本身声明为推断：不进入事实层，语义标 inference 由 decision 处理
    if draft.kind == "transition":
        return "insufficient", None, "衔接语不承载实质主张"

    # 模型判定优先（若编排器提供了受控判定）
    if gate.semantic_model_verdict in ("supports", "contradicts", "insufficient"):
        conf = gate.semantic_model_confidence
        reason = (gate.semantic_model_reason or "").strip()
        return gate.semantic_model_verdict, conf, (reason or "模型语义判定")

    # 无模型：仅允许确定性规则强放行，否则 insufficient（不自动通过）
    if _has_contradiction_marker(evidence) and not _has_contradiction_marker(statement):
        return "contradicts", None, "证据含否定/相反表述，与陈述不一致"

    # 规则放行**必须**同时满足：
    #   (a) 去掉指代套话后的主张几乎全部出现在**已定位的引用片段**中（覆盖率）；
    #   (b) 整体 bigram 重合度达到最低线。
    # 二者缺一即 insufficient —— 不允许"引用能定位"就自动当支持。
    stmt_core = locator.strip_boilerplate(statement)
    ev_core = locator.strip_boilerplate(evidence)
    coverage = locator.containment(stmt_core, ev_core)
    overlap = max(locator.lexical_overlap(statement, evidence),
                  locator.containment(stmt_core, ev_core))
    if coverage >= locator.RULE_SUPPORT_THRESHOLD and overlap >= locator.RULE_SUPPORT_THRESHOLD:
        return "supports", DEFAULT_RULE_CONFIDENCE, "字面高度重合（规则判定，非模型）"
    if gate.llm_available:
        # LLM 可用但未给出判定：不能凭"有原文"就当支持
        return "unreviewed", None, "语义未判定（模型未返回结论）"
    return "insufficient", None, "无 LLM，无法确认语义支持（规则重合度不足）"


# --------------------------------------------------------------- 主流程


def assess(
    draft: StatementDraft, gate: GateInput, *, review: Optional[ReviewRecord] = None
) -> Tuple[ValidationReport, List[CandidateEvidence]]:
    """执行固定顺序的 gate，返回报告与候选（**纯函数，不写库**）。"""
    scope = draft.scope
    reasons: List[ValidationReason] = []
    warnings: List[Warning] = list(gate.warnings)

    locator_valid = False
    quote_valid = False

    # ---------- ① 范围 / 身份 ----------
    scope_valid = (
        scope.paper_id == gate.scope.paper_id
        and scope.revision_id == gate.scope.revision_id
    )
    if not scope_valid:
        reasons.append(_reason("wrong_scope", "陈述 scope 与请求 scope 不一致"))

    if review is not None:
        # 人工复核只能作用于**同源派生版且陈述未变**；不跳过身份/原文检查
        same_source = (
            review.request.scope.paper_id == scope.paper_id
            and review.request.scope.revision_id == scope.revision_id
        )
        if not same_source:
            warnings.append(
                Warning(code="review_scope_mismatch",
                        message="复核记录 scope 与陈述不一致，已忽略该复核",
                        stage="evidence")
            )

    # ---------- ② 原文精确 / 可回溯规范化匹配 ----------
    candidates: List[CandidateEvidence] = []
    for citation in draft.citations:
        found, cite_reasons = build_candidates(citation, gate)
        reasons.extend(cite_reasons)
        candidates.extend(found)

    if candidates:
        quote_valid = True
        locator_valid = True
    elif draft.citations:
        reasons.append(
            _reason("coordinate_missing", "所有候选引用都未能在原文中定位",
                    [c.block_id for c in draft.citations])
        )

    # ---------- ③ 页 / 区域 ----------
    # 关键区分：**引用块级**定位（有真实 QuoteSpan）已经足够"精准"，
    # 不需要 bounding rect；rect 只是可选的区域坐标。
    # 只有"仅知道在哪一页、没有引用块/引用片段"的候选才算 page_only。
    page_only = False
    if candidates:
        for cand in candidates:
            cand.page_only = bool(cand.page_only or not cand.block_id)
        if all(c.page_only for c in candidates):
            page_only = True
            warnings.append(
                Warning(code="page_level_evidence",
                        message="仅有页级依据，已降级为 page_only（不声称精准定位）",
                        stage="evidence")
            )

    # ---------- ④ 数字 / 单位 / 条件 ----------
    evidence_text = _evidence_text_for(candidates, gate.blocks)

    numeric_status = "unreviewed"
    qualifier_status = "unreviewed"
    if candidates and evidence_text:
        numeric_status = locator.numeric_consistency(draft.text, evidence_text)
        qualifier_status = _qualifier_status(locator.qualifier_consistency(draft.text, evidence_text))
        if numeric_status == "fail":
            reasons.append(_reason("numeric_mismatch", "陈述中的数字/单位在证据中缺失或不一致"))
        if qualifier_status == "fail":
            reasons.append(_reason("qualifier_missing", "陈述的适用条件（仅在…/假设…）在证据中缺失"))
    elif draft.kind == "transition":
        # 过渡句不承载可核查断言：numeric 允许 not_applicable，qualifier 契约无此值 → pass
        numeric_status = "not_applicable"
        qualifier_status = "pass"
    else:
        if draft.qualifiers:
            qualifier_status = "fail"
            reasons.append(_reason("qualifier_missing", "有适用条件但无任何证据"))
        if locator.numbers_in(draft.text):
            numeric_status = "fail"
            reasons.append(_reason("numeric_mismatch", "陈述含数字但无任何证据"))

    # ---------- ⑤ 语义支持 ----------
    semantic_status, confidence, semantic_msg = semantic_verdict(draft, evidence_text, gate)
    # ValidationReason.code 是受控字面量集合，语义状态需映射到合法 code：
    #   supports   -> passed（"语义已确认支持"由 decision=verified 表达）
    #   contradicts-> contradiction
    #   insufficient -> unsupported_entailment
    #   unreviewed -> external_unavailable
    if semantic_status == "supports":
        reasons.append(_reason("passed", semantic_msg,
                               [c.block_id for c in candidates if c.block_id]))
    elif semantic_status == "contradicts":
        reasons.append(_reason("contradiction", semantic_msg,
                               [c.block_id for c in candidates if c.block_id]))
    elif semantic_status == "insufficient":
        reasons.append(_reason("unsupported_entailment", semantic_msg,
                               [c.block_id for c in candidates if c.block_id]))
    else:
        reasons.append(_reason("external_unavailable", semantic_msg,
                               [c.block_id for c in candidates if c.block_id]))

    # ---------- ⑥ decision ----------
    decision = decide(
        draft, scope_valid=scope_valid, locator_valid=locator_valid,
        quote_valid=quote_valid, semantic_status=semantic_status,
        numeric_status=numeric_status, qualifier_status=qualifier_status,
        has_evidence=bool(candidates),
    )

    if decision == "verified":
        reasons.append(_reason("passed", "通过范围/原文/页/数字/条件/语义全部检查"))
    if decision == "rejected" and not any(r.code == "unsupported_entailment" for r in reasons):
        reasons.append(_reason("unsupported_entailment", "证据不支持该陈述，已拒绝"))

    report = ValidationReport(
        scope=scope,
        id=_stable_id("val", scope.revision_id, draft.id),
        statement_id=draft.id,
        # quote_valid = 引用在原文中找到了（精确或可回溯规范化）
        # locator_valid = 定位成功（有真实 quote span）
        # 二者**独立于语义支持**：定位成功 ≠ 支持成立（本模块最核心的区分）
        locator_valid=bool(locator_valid),
        quote_valid=bool(quote_valid),
        scope_valid=scope_valid,
        semantic_status=semantic_status,
        numeric_status=numeric_status,
        qualifier_status=qualifier_status,
        decision=decision,
        evidence=[],   # 由 save_report/service 层填充（需要持久化 ID）
        reasons=reasons,
        assessor="human" if review is not None else "rule",
        assessor_version=RULE_ASSESSOR_VERSION,
        confidence=confidence if decision in ("verified", "inference") else None,
    )
    return report, candidates


def _evidence_text_for(
    candidates: Sequence[CandidateEvidence],
    blocks: Optional[Dict[str, Block]] = None,
) -> str:
    """从候选证据拼出**用于语义判定的证据原文**。

    与 ``assess`` 第 ④ 步构造 evidence_text 的口径**逐字一致**，供 service 层在
    **不跑完整 gate** 的情况下先拿到证据文本交给语义判定模型：

    1. 优先取候选引用块（``blocks[block_id]``）的**整块原文**——这是 gate 的既定口径，
       比窄引用片段提供更完整的上下文（数字/条件往往落在片段之外）；
    2. 无块对象时退回候选自带的 ``source_text``。

    注意 ``QuoteSpan`` 的原文在 ``source_text`` 字段（contracts/documents.py:209），
    但本函数**不使用**它——保持与 gate 一致比"更精确"更重要，否则 numeric gate
    会因上下文变窄而误判 fail。
    """
    if blocks:
        ctx_text = locator.join_source_text(
            [blocks[c.block_id] for c in candidates if c.block_id in blocks]
        )
        if ctx_text:
            return ctx_text
    return "\n".join(c.source_text for c in candidates if c.source_text)


def _qualifier_status(raw: str) -> str:
    """``ValidationReport.qualifier_status`` 契约只接受 pass/fail/unreviewed。

    locator 在"没有适用条件"时返回 ``not_applicable``，此处映射为 ``pass``
    （没有条件需要满足 ≈ 条件检查通过），避免契约非法值。
    """
    if raw == "not_applicable":
        return "pass"
    if raw in ("pass", "fail", "unreviewed"):
        return raw
    return "unreviewed"


def decide(
    draft: StatementDraft,
    *,
    scope_valid: bool,
    locator_valid: bool,
    quote_valid: bool,
    semantic_status: str,
    numeric_status: str,
    qualifier_status: str,
    has_evidence: bool,
) -> str:
    """decision 决策表（REFACTOR_SPEC §5.4）。

    - 任何范围/引文/数字/条件硬失败 → ``rejected``；
    - 明确矛盾 → ``contested``；
    - ``kind=inference`` 且引用正确 → ``inference``（**不是事实**）；
    - 只有全部检查通过且语义 supports 才 ``verified``；
    - 其余 → ``unverified``（待核验）。
    """
    if not scope_valid:
        return "rejected"
    if draft.kind == "transition":
        # 衔接语不承载事实；允许无证据，但绝不进入事实层
        return "unverified" if not has_evidence else "inference"
    if quote_valid is False and draft.citations:
        return "rejected"
    if numeric_status == "fail" or qualifier_status == "fail":
        return "rejected"
    if semantic_status == "contradicts":
        return "contested"
    if draft.kind == "inference":
        return "inference" if (locator_valid and has_evidence) else "unverified"
    if locator_valid and has_evidence and semantic_status == "supports":
        return "verified"
    if not has_evidence and draft.kind == "fact":
        return "unverified"
    return "unverified"


def _stable_id(prefix: str, *parts: str) -> str:
    """稳定 ID：同 scope/陈述重复 validate 得到同一个 id（幂等覆盖）。"""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"


def candidate_to_segment(cand: CandidateEvidence) -> AnchorSegment:
    """候选 → AnchorSegment（page-only 强制 rect=None / quads=[]）。"""
    if cand.page_only or cand.rect is None:
        return AnchorSegment(
            page_id=cand.page_id,
            pdf_page_index=cand.pdf_page_index,
            page_label=cand.page_label,
            rect=None,
            quads=[],
            block_ids=[cand.block_id] if cand.block_id else [],
            quote_spans=[cand.quote_span] if cand.quote_span else [],
        )
    return AnchorSegment(
        page_id=cand.page_id,
        pdf_page_index=cand.pdf_page_index,
        page_label=cand.page_label,
        rect=cand.rect,
        quads=list(cand.quads or []),
        block_ids=[cand.block_id] if cand.block_id else [],
        quote_spans=[cand.quote_span] if cand.quote_span else [],
    )


def build_evidence_record(
    draft: StatementDraft,
    cand: CandidateEvidence,
    *,
    evidence_id: str,
    anchor_id: str,
    source_document_id: str,
    validation_id: Optional[str] = None,
    support_status: str = "unreviewed",
    confidence: Optional[float] = None,
    confidence_method: Optional[str] = None,
) -> EvidenceRecord:
    """由**服务端候选**构造 EvidenceRecord（source_text 已来自原文切片）。"""
    return EvidenceRecord(
        scope=draft.scope,
        id=evidence_id,
        legacy_id=None,
        claim_id=draft.claim_id,
        source_document_id=source_document_id,
        anchor_id=anchor_id,
        source_page=cand.pdf_page_index + 1,
        source_region=[candidate_to_segment(cand)],
        source_text=cand.source_text,
        quote_spans=[cand.quote_span] if cand.quote_span else [],
        media_ids=list(cand.media_ids or []),
        confidence=confidence,
        confidence_method=confidence_method,
        locator_status="exact" if not cand.page_only else "page_only",
        support_status=support_status,
        validation_id=validation_id,
    )


def build_anchor(
    scope: Scope, cand: CandidateEvidence, *, anchor_id: str, source_document_id: str
) -> Anchor:
    """由候选构造 Anchor（region 才算 region，否则 page）。"""
    segment = candidate_to_segment(cand)
    precision = "region" if segment.rect is not None else "page"
    return Anchor(
        scope=scope,
        id=anchor_id,
        source_document_id=source_document_id,
        precision=precision,
        segments=[segment],
    )


__all__ = [
    "RULE_ASSESSOR_VERSION",
    "GateInput",
    "CandidateEvidence",
    "build_candidates",
    "page_only_candidate",
    "semantic_verdict",
    "assess",
    "decide",
    "candidate_to_segment",
    "build_evidence_record",
    "build_anchor",
]
