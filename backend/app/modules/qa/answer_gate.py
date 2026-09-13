"""M10 — 答案级闸门（REFACTOR_SPEC §5.4、§5.7）。

判定规则（**唯一权威，禁止按措辞猜**）：

``grounded = True`` 仅当同时满足：
1. 答案有**实质内容**（去空白后非空，且不是纯拒答语）；
2. 所有事实句（``display_class ∈ {verified_fact, attributed_quote}``）都有
   验证通过的证据（``evidence_ids`` 非空且对应记录存在）；
3. **无未支持推断混入**：inference 类句子必须显式标注（保留在答案里但会让
   grounded=False，除非全部句子都是 inference 且都有依据 → 仍为 False）；
4. 没有任何 unverified 草稿被当作答案发出。

反面红线：
- 纯拒答（abstained）= **False**，不管文本里有没有「无法回答」；
- **绝不按「未出现拒答词」判 grounded**（旧实现的核心缺陷）；
- 绝不只凭 evidence 非空或模型自报 confidence 判 grounded。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from app.contracts.evidence import VerifiedStatement

#: 视为「已验证事实」的展示类
FACT_CLASSES = {"verified_fact", "attributed_quote"}
#: 允许出现但会打断 grounded 的展示类
INFERENCE_CLASS = "inference"
#: 不承载事实的衔接语
TRANSITION_CLASS = "transition"


@dataclass
class GateDecision:
    grounded: bool
    reason: str
    confidence: str = "Low"
    fact_count: int = 0
    supported_facts: int = 0
    inference_count: int = 0
    unverified_count: int = 0
    unsupported: List[str] = field(default_factory=list)


def is_abstention(note: str, mode: str, sentences: Sequence[VerifiedStatement]) -> bool:
    """拒答 = 显式 abstained/not_mentioned 模式，或没有任何可发布的句子。"""
    if mode in ("abstained", "not_mentioned"):
        return True
    return not _publishable(sentences)


def assess(
    text: str,
    sentences: Sequence[VerifiedStatement],
    *,
    mode: str = "generated",
) -> GateDecision:
    """对完整答案做逐句 gate，给出 grounded 判定与可解释原因。"""
    body = (text or "").strip()

    verified = _safe_evidence_ids(sentences)
    facts: List[VerifiedStatement] = []
    inferences: List[VerifiedStatement] = []
    unverified: List[VerifiedStatement] = []

    for st in sentences:
        display = getattr(st, "display_class", "unverified")
        if display in FACT_CLASSES:
            facts.append(st)
        elif display == INFERENCE_CLASS:
            inferences.append(st)
        elif display == TRANSITION_CLASS:
            continue
        else:
            unverified.append(st)

    unsupported = [
        st.id for st in facts
        if not _has_evidence(st, verified)
    ]

    decision = GateDecision(
        grounded=False, reason="",
        fact_count=len(facts),
        supported_facts=len(facts) - len(unsupported),
        inference_count=len(inferences),
        unverified_count=len(unverified),
        unsupported=unsupported,
    )

    # 1) 纯拒答 / 空答案
    if mode == "abstained":
        decision.reason = "abstained：无可用证据，按拒答返回"
        return decision
    if not body and not facts:
        decision.reason = "答案无实质内容"
        return decision
    if not facts and not inferences:
        decision.reason = "没有任何通过 gate 的句子"
        return decision

    # 2) 事实句必须有验证通过的证据
    if unsupported:
        decision.reason = f"{len(unsupported)} 个事实句缺少通过验证的证据"
        return decision
    if facts and not verified:
        decision.reason = "事实句引用的证据记录不存在或未验证"
        return decision

    # 3) 未支持推断混入 → 不 grounded
    if inferences:
        bad = [st.id for st in inferences if not _has_evidence(st, verified)]
        if bad:
            decision.reason = f"存在无依据推断（{len(bad)} 条）"
            return decision
        decision.reason = "答案包含显式标注的推断，非纯事实回答"
        return decision

    # 4) unverified 草稿绝不能算 grounded
    if unverified:
        decision.reason = f"存在未验证草稿（{len(unverified)} 条），不予发布"
        return decision

    if not body:
        decision.reason = "答案文本为空"
        return decision

    decision.grounded = True
    decision.reason = "所有事实句均有通过验证的证据，且无未支持推断"
    decision.confidence = _confidence(decision, mode)
    return decision


def publishable_sentences(
    sentences: Sequence[VerifiedStatement],
) -> List[VerifiedStatement]:
    """可对外发送的句子：verified_fact / attributed_quote / inference（显式标注）。

    **unverified 草稿不发送为答案**。
    """
    return [
        st for st in sentences
        if getattr(st, "display_class", "unverified") in (
            FACT_CLASSES | {INFERENCE_CLASS, TRANSITION_CLASS}
        )
    ]


def _publishable(sentences: Sequence[VerifiedStatement]) -> List[VerifiedStatement]:
    return publishable_sentences(sentences)


def _safe_evidence_ids(
    sentences: Sequence[VerifiedStatement],
) -> dict:
    """以 evidence_id → True 表示「引用存在」；上层会再与库核对。"""
    known: dict = {}
    for st in sentences:
        for eid in (getattr(st, "evidence_ids", []) or []):
            if eid:
                known[eid] = True
    return known


def _has_evidence(st: VerifiedStatement, known: dict) -> bool:
    """句子至少引用一个存在的证据 ID；**不采信模型自报 confidence**。"""
    ids = [e for e in (getattr(st, "evidence_ids", []) or []) if e]
    if not ids:
        return False
    return all(eid in known for eid in ids)


def _confidence(decision: GateDecision, mode: str = "generated") -> str:
    """置信度三档（R4-M3，ADR D-104）——**判据确定，不靠感觉**。

    为什么改：此前 `grounded=False` 一律 ``Low``，而"不 grounded"过去等价于"拒答"。
    决策 1 之后不再有拒答，低置信度回答会真的交付给用户，所以必须能区分
    "逐字原文但未过整句校验"（``extractive``，Medium）与"通用回答"（``general``，Low）。

    判据（自上而下）：

    - ``High``：grounded **且** ≥2 条事实句 **且** 无推断混入；
    - ``Medium``：grounded 的其余情形；或 ``mode=extractive`` 且事实句**全部**有证据
      （逐字原文、无编造空间，但未整体通过 gate）；
    - ``Low``：其余一切（``general`` / ``unavailable`` / 无据可依）。

    **红线**：本函数只决定"多可信"，绝不放宽 `assess` 的 grounded 判据。
    """
    if decision.grounded:
        if decision.fact_count >= 2 and decision.inference_count == 0:
            return "High"
        return "Medium"
    if (
        mode == "extractive"
        and decision.fact_count > 0
        and decision.supported_facts == decision.fact_count
    ):
        return "Medium"
    return "Low"


__all__ = [
    "FACT_CLASSES",
    "INFERENCE_CLASS",
    "TRANSITION_CLASS",
    "GateDecision",
    "assess",
    "is_abstention",
    "publishable_sentences",
]
