"""M04 — 语义支持判定（Evidence Gate 第 ⑤ 步的真实执行者）。

## 为什么需要这个模块

``gate.assess`` 的语义判定顺序是：

1. ``gate.semantic_model_verdict`` 命中 → 直接用模型判定（``"模型语义判定"``）；
2. 否则规则放行：去套话后主张几乎全部出现在引用片段中 **且** bigram 重合度达线；
3. 仍不满足且 ``gate.llm_available`` → ``unreviewed``（"语义未判定（模型未返回结论）"）；
4. 无 LLM → ``insufficient``。

第 1 条的输入来自 ``evidence.service.validate`` 里的
``getattr(ctx, "_semantic_verdict", None)`` —— 但**全代码库没有任何地方写入过它**。
于是真实中文论文走的是第 3 条：``semantic_status="unreviewed"`` →
``decision="unverified"`` → 被 ``claims.get_verified_statements`` 过滤掉 →
图谱/讲解/问答全部为空（"该 revision 暂无媒体绑定"、"未通过验证，不进入讲解正文"）。

本模块补齐第 1 条的**生产者**：用 M05 的受控 JSON 调用，对
「陈述 + 已定位证据原文」做支持/反驳/不足三分类，把结果交给 gate。

## 契约纪律（REFACTOR_SPEC §6.6 / §6.8）

- **无 LLM 时绝不自动通过**：返回 ``unreviewed`` 而不是 ``supports``；
- 模型只说三态之一，**不产生**页码/坐标/引用 —— 那些仍由服务端从原文切片；
- 调用失败（超时/预算/解析错）**降级为 unreviewed**，不把异常泄漏为 500；
- 受控 SchemaRef：``output_schema`` 由 M05 做严格校验，非法 JSON 视为失败降级。
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from pydantic import BaseModel, Field

log = logging.getLogger("researchlens.evidence.semantic")

#: 送入模型的证据原文上限（超出截断，避免超预算；不改变判定所需的最小上下文）
MAX_EVIDENCE_CHARS = 2400
#: 送入模型的陈述上限
MAX_STATEMENT_CHARS = 1200

SEMANTIC_ASSESSOR_VERSION = "rl.semantic/1"


class _Verdict(BaseModel):
    """受控三分类输出（严格 JSON schema）。

    三个字段都**不给默认值**：实测 qwen-plus 在 strict json_schema 下只会填
    "它确信的字段"，给了默认值就会静默留空（reason=''、confidence=0.0），
    让 confidence 看起来像真实评分却其实是缺失。设为必填可强制模型逐项输出。
    """

    verdict: str = Field(
        description="supports|contradicts|insufficient —— 证据是否支持该陈述",
    )
    confidence: float = Field(
        description="判定强度 0~1 的小数（不是概率校准，仅表示校验强度）",
    )
    reason: str = Field(description="一句中文理由，说明为何给出该判定")


SEMANTIC_JUDGE_PROMPT = (
    "你是科研事实核验引擎。给定一条**研究陈述**和一段**原文证据**，"
    "判断原文证据对陈述的支持关系。\n"
    "三个可选判定（verdict 字段只能填其中一个单词，不要加引号、标点或解释）：\n"
    "- supports —— 证据明确表达了陈述的内容（允许同义改写、数值单位换算），"
    "且陈述没有超出证据的适用范围。\n"
    "- contradicts —— 证据与陈述相互矛盾（结论相反、数值相反、适用条件冲突）。\n"
    "- insufficient —— 证据相关但不足以支持陈述（缺少关键数字、比较对象不同、"
    "证据只谈到相邻概念、陈述放大了证据的适用范围）。\n"
    "严格纪律：\n"
    "1. 证据里没有的数字、比较对象、条件，绝不能算 supports —— 那是 insufficient。\n"
    "2. 不要因为「同页」或「主题相近」就判 supports。\n"
    "3. verdict 只填 supports / contradicts / insufficient 三个单词之一。\n"
    "4. confidence 填 0 到 1 之间的小数；reason 用一句中文说明理由。\n"
    "输出 JSON 对象，包含 verdict、confidence、reason 三个字段。\n"
)


def judge(
    statement: str,
    evidence_text: str,
    ctx,
) -> Tuple[Optional[str], Optional[float], str]:
    """调用模型做支持判定。

    返回值 ``(verdict, confidence, message)``：

    - ``verdict`` ∈ ``{"supports","contradicts","insufficient"}`` 或 ``None``；
    - ``None`` 表示"未判定"（无 LLM / 调用失败 / 输出非法），
      由 ``gate`` 决定降级为 ``unreviewed``；

    **绝不返回 ``supports`` 之外的成功默认值**——无结论就是无结论。
    """
    stmt = (statement or "").strip()
    ev = (evidence_text or "").strip()
    if not stmt or not ev:
        return None, None, "陈述或证据为空，无法判定"

    from app.core.config import settings

    if not getattr(settings, "has_llm", False):
        return None, None, "未配置 LLM，语义未判定"

    try:
        from app.contracts.ai import ChatMessage, CompletionRequest
        from app.modules import ai as ai_module

        user = (
            f"【陈述】\n{stmt[:MAX_STATEMENT_CHARS]}\n\n"
            f"【原文证据】\n{ev[:MAX_EVIDENCE_CHARS]}"
        )
        result = ai_module.complete(
            CompletionRequest(
                messages=[
                    ChatMessage(role="system", content=SEMANTIC_JUDGE_PROMPT),
                    ChatMessage(role="user", content=user),
                ],
                output_schema=_Verdict,
                max_output_tokens=512,
            ),
            ctx,
        )
    except Exception as exc:  # noqa: BLE001 - 云调用失败必须降级，不得中断 gate
        log.info("semantic judge 调用失败，降级为未判定：%s", exc)
        return None, None, f"语义判定调用失败：{type(exc).__name__}"

    value = getattr(result, "value", None)
    if value is None:
        return None, None, "语义判定未返回结果"

    verdict = str(getattr(value, "verdict", "") or "").strip().lower()
    if verdict not in ("supports", "contradicts", "insufficient"):
        # 受控集合之外：不猜测、不放行
        return None, None, f"语义判定输出非法：{verdict!r}"

    conf = getattr(value, "confidence", None)
    try:
        conf = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf = None
    return verdict, conf, "模型语义判定"


BATCH_JUDGE_PROMPT = (
    "你是科研事实核验引擎。下面给出**多条**「陈述 + 原文证据」，逐条判断证据对陈述的支持关系。\n"
    "每条只能填一个判定：\n"
    "- supports —— 证据明确表达了陈述的内容（允许同义改写、数值单位换算），"
    "且陈述没有超出证据的适用范围。\n"
    "- contradicts —— 证据与陈述相互矛盾。\n"
    "- insufficient —— 证据相关但不足以支持（缺关键数字、比较对象不同、放大了适用范围）。\n"
    "纪律：证据里没有的数字/比较对象/条件，绝不能算 supports；"
    "不要因为主题相近就判 supports。\n"
    "输出 JSON：{\"items\": [{\"index\": 0, \"verdict\": \"supports\", \"confidence\": 0.8}, ...]}，"
    "**每条都要有**，index 与输入序号一致。\n"
)


def batch_judge(
    items: "list[tuple[str, str]]",
    ctx,
) -> dict:
    """**一次调用**判定多条「陈述 + 引用原文」的支持关系（ADR-0063）。

    为什么要批量：问答的一条回答里有 3–5 句，逐句判定就要 3–5 次 LLM 调用
    （实测每句 ~20s），用户看到"一直在转"。批量把这段压成一次调用。

    返回 ``{陈述文本: (verdict, confidence)}``；**任何失败都返回空 dict**
    （调用方逐句回退到原来的单句判定，不改变正确性，只影响速度）。
    """
    pairs = [(str(s or "").strip(), str(e or "").strip()) for s, e in (items or [])]
    pairs = [(s, e) for s, e in pairs if s and e]
    if not pairs:
        return {}

    from app.core.config import settings

    if not getattr(settings, "has_llm", False):
        return {}

    class _Item(BaseModel):
        index: int = Field(description="第几条（从 0 开始，与输入顺序一致）")
        verdict: str = Field(description="supports|contradicts|insufficient")
        confidence: float = Field(description="判定强度 0~1 的小数")

    class _Batch(BaseModel):
        items: list[_Item] = Field(default_factory=list)

    blocks = []
    for idx, (stmt, ev) in enumerate(pairs):
        blocks.append(
            f"[{idx}] 陈述：{stmt[:MAX_STATEMENT_CHARS]}\n"
            f"    原文证据：{ev[:MAX_EVIDENCE_CHARS]}"
        )
    try:
        from app.contracts.ai import ChatMessage, CompletionRequest
        from app.modules import ai as ai_module

        result = ai_module.complete(
            CompletionRequest(
                messages=[
                    ChatMessage(role="system", content=BATCH_JUDGE_PROMPT),
                    ChatMessage(role="user", content="\n\n".join(blocks)),
                ],
                output_schema=_Batch,
                max_output_tokens=2048,
            ),
            ctx,
        )
    except Exception as exc:  # noqa: BLE001  批量失败 → 调用方逐句回退
        log.info("批量语义判定失败，回退逐句判定：%s", exc)
        return {}

    value = getattr(result, "value", None)
    out: dict = {}
    for item in (getattr(value, "items", None) or []):
        try:
            idx = int(getattr(item, "index", -1))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(pairs)):
            continue
        verdict = str(getattr(item, "verdict", "") or "").strip().lower()
        if verdict not in ("supports", "contradicts", "insufficient"):
            continue
        conf = getattr(item, "confidence", None)
        try:
            conf = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf = None
        out[pairs[idx][0]] = (verdict, conf)
    return out


__all__ = [
    "SEMANTIC_ASSESSOR_VERSION",
    "SEMANTIC_JUDGE_PROMPT",
    "BATCH_JUDGE_PROMPT",
    "MAX_EVIDENCE_CHARS",
    "MAX_STATEMENT_CHARS",
    "judge",
    "batch_judge",
]
