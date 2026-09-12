"""M12 — **AI 评测裁判**：用 LLM 按语义判等，让 support_precision 出得来。

## 为什么需要（真实卡点）

规格要求 `support_precision/recall` 必须有标注集才叫 measured，所以金标集是机器草案时
它们只能是 `not_evaluated` —— 四个核心指标缺一个，`overall_score` 就一直 null，
用户看到的是"未评测"。

而卡住的**技术原因**是文本相似度：预测断言与参考断言常常是"同一事实、不同措辞"，
实测最高相似度只有 **0.21**（阈值 0.42），所以文本匹配法给出的是 0 或测不出来
（ADR-0052 已实测"事实级匹配"通道无增益，因为它仍在比字面）。

## 本模块的定位（纪律）

- 裁判只做**一件事**：判断"预测断言 i"与"参考断言 j"是否表达**同一事实**；
- 它**不产生**分数以外的东西，也**不碰** measured/proxy 的判定 —— 由评测层决定；
- 调用失败 / 无模型 / 输出非法 → 返回 ``None``（未判定），**绝不返回 0 分**；
- 结果按**输入摘要**缓存（``judge_digest``），避免每次打开评测页都花一次云调用。
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from app.contracts.evaluation import AiJudgeResult

log = logging.getLogger("researchlens.evaluation.ai_grader")

AI_JUDGE_VERSION = "rl.ai_judge/3"

#: 送入裁判的断言条数上限（超出截断，避免超预算；评测用的论文断言远少于此）
MAX_CLAIMS = 40
#: 单条断言送入模型的字符上限
MAX_CLAIM_CHARS = 400


class _Match(BaseModel):
    predicted: int = Field(description="预测断言的下标（从 0 开始）")
    golden: int = Field(description="与之表达同一事实的参考断言下标；没有就是 -1")


class _JudgeOut(BaseModel):
    """受控输出：只允许给出下标配对。"""

    matches: List[_Match] = Field(
        default_factory=list,
        description="所有能配上对的 (predicted, golden) 下标；配不上的不要出现",
    )


AI_JUDGE_PROMPT = (
    "你是学术论文评测裁判。给定两组编号断言：\n"
    "- 「预测断言」：某个系统从论文中抽取出来的断言；\n"
    "- 「参考断言」：独立从同一篇论文整理出的参考要点。\n"
    "任务：找出每一条预测断言是否与某条参考断言表达**同一件事**。\n"
    "判定纪律：\n"
    "1. **语义判等，不是比对文字**。措辞不同、语言不同（中英互译）、"
    "详细程度不同，只要**对象/结论/数值一致**就算同一件事。\n"
    "2. 数值必须一致（12% 与 12% 一致；12% 与 8% 不一致）；"
    "结论方向必须一致（下降与上升不一致）。\n"
    "3. 只是主题相近、或参考断言的范围明显更大/更小，**不算**同一件事。\n"
    "4. 每条预测断言最多配一条参考断言，每条参考断言最多被配一次。\n"
    "5. 配不上的不要输出。\n"
    "输出 JSON 对象：{\"matches\": [{\"predicted\": 0, \"golden\": 2}, ...]}，下标从 0 开始。\n"
)


@dataclass
class JudgeResult:
    """裁判结论：只含配对与计数，分数由评测层算。"""

    matches: List[Tuple[int, int]] = field(default_factory=list)
    #: 命中且预测本身有证据支持的条数（真阳性）。**缓存复用时以此为准**。
    true_positive: int = 0
    total_predicted: int = 0
    total_golden: int = 0
    model: str = ""
    digest: str = ""

    def as_contract(self) -> AiJudgeResult:
        return AiJudgeResult(
            matches=[[int(p), int(g)] for p, g in self.matches],
            true_positive=int(self.true_positive),
            total_predicted=int(self.total_predicted),
            total_golden=int(self.total_golden),
            model=self.model,
            digest=self.digest,
            judge_version=AI_JUDGE_VERSION,
        )


def judge_digest(predicted: Sequence[str], golden: Sequence[str]) -> str:
    """输入摘要：断言内容或裁判版本一变就失效（缓存用）。"""
    payload = {
        "judge": AI_JUDGE_VERSION,
        "predicted": [str(x or "") for x in list(predicted)[:MAX_CLAIMS]],
        "golden": [str(x or "") for x in list(golden)[:MAX_CLAIMS]],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _clean_matches(raw: object, n_pred: int, n_gold: int) -> List[Tuple[int, int]]:
    """校验下标：越界丢弃、一对一约束（每条预测/参考最多用一次）。"""
    out: List[Tuple[int, int]] = []
    used_p: set = set()
    used_g: set = set()
    for item in list(raw or []):
        try:
            pi = int(getattr(item, "predicted", -1))
            gi = int(getattr(item, "golden", -1))
        except (TypeError, ValueError):
            continue
        if not (0 <= pi < n_pred) or not (0 <= gi < n_gold):
            continue
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        out.append((pi, gi))
    return out


def judge_support(
    predicted: Sequence[str],
    golden: Sequence[str],
    ctx,
) -> Optional[JudgeResult]:
    """LLM 语义判等。

    返回 ``None`` 表示**未判定**（无模型 / 调用失败 / 输出非法）——
    调用方必须降级为 ``not_evaluated``，不得当成 0 分。
    """
    pred = [str(x or "").strip() for x in list(predicted)][:MAX_CLAIMS]
    gold = [str(x or "").strip() for x in list(golden)][:MAX_CLAIMS]
    if not pred or not gold:
        return None

    from app.core.config import settings

    if not getattr(settings, "has_llm", False):
        return None

    def _block(title: str, items: Sequence[str]) -> str:
        lines = [f"{title}"]
        for idx, text in enumerate(items):
            lines.append(f"[{idx}] {text[:MAX_CLAIM_CHARS]}")
        return "\n".join(lines)

    user = _block("【预测断言】", pred) + "\n\n" + _block("【参考断言】", gold)
    try:
        from app.contracts.ai import ChatMessage, CompletionRequest
        from app.modules import ai as ai_module

        result = ai_module.complete(
            CompletionRequest(
                messages=[
                    ChatMessage(role="system", content=AI_JUDGE_PROMPT),
                    ChatMessage(role="user", content=user),
                ],
                output_schema=_JudgeOut,
                max_output_tokens=1024,
            ),
            ctx,
        )
    except Exception as exc:  # noqa: BLE001  云调用失败必须降级，不得中断评测
        log.info("AI 裁判调用失败，本次不出 AI 分数：%s", exc)
        return None

    value = getattr(result, "value", None)
    if value is None:
        return None
    matches = _clean_matches(getattr(value, "matches", None), len(pred), len(gold))
    return JudgeResult(
        matches=matches,
        total_predicted=len(pred),
        total_golden=len(gold),
        model=str(getattr(result, "model", "") or ""),
        digest=judge_digest(pred, gold),
    )


__all__ = [
    "AI_JUDGE_VERSION",
    "AI_JUDGE_PROMPT",
    "MAX_CLAIMS",
    "MAX_CLAIM_CHARS",
    "JudgeResult",
    "judge_digest",
    "judge_support",
]
