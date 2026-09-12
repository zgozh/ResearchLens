"""M06 — claims 抽取/结构概览的提示词与受控 SchemaRef（REFACTOR_SPEC §6.8）。

纪律：
- LLM **只能**从给定的 block_id 候选里挑引用，不能自造页码/坐标；
- 每个输出条目必须带 ``block_id`` + ``quote``；服务端负责补页与校验；
- 抽取到的疑似事实**先当候选**，绝不因为"模型说了"就 SUPPORTED。
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

#: **单节**的原文预算。``_build_corpus`` 按章节公平分配，保证每节都有内容
#: （不只读头部），节内超份额时均匀取样。
PER_SECTION_CHAR_BUDGET = 6000
#: **单次调用**的原文总预算。
#:
#: 为什么是 16000 而不是更大（ADR-0022 实测，2026-09-12）：
#:
#: | 总预算 | 语料字符 | 产出 claim | 带 quote | quote 真正匹配原文 | 耗时 |
#: |---|---|---|---|---|---|
#: | 16000 | 16070 | 7 | 7 | **7（100%）** | 31.7s |
#: | 48000 | 48243 | 5 | 5 | **1（20%）** | 112.5s |
#:
#: 48000 下模型**仍然给 quote**，但绝大多数是**改写/幻觉**，无法在原文块中逐字命中，
#: 被 ``_draft_batch_from_raw`` 的 ``quote_not_in_block`` 丢弃 → citations 空 →
#: gate 全拒。即"长上下文让引用不可靠"，而不是早期注释猜测的"省略 quotes 字段"
#: （那一项已由 ``_Quote`` 的 ``min_length=1`` 修掉）。同时耗时是 3.5 倍。
#:
#: 因此**不靠加大预算来覆盖全文**，而是把这 16000 字符**按章节公平分配**
#: （见 ``TOTAL_CHAR_BUDGET`` 的使用点 ``service._build_corpus``）。
#: 若要进一步覆盖到"每节完整"，需要改成分块多次调用（尚未实现）。
TOTAL_CHAR_BUDGET = 16000
#: 展项规模上限（超出保留候选、不发布，并在 warnings 报告覆盖范围）
MAX_EXHIBIT_CLAIMS = 40
MAX_SCENE_COUNT = 12
MAX_METHOD_STEPS = 30


class _Quote(BaseModel):
    block_id: str = Field(description="正文块的短编号，如 B1、B2，必须来自给定正文")
    quote: str = Field(description="该 block 中的原文片段，用于服务端定位")


class _ClaimItem(BaseModel):
    claim_id: str = Field(description="短标识，≤32 字符，同 revision 内唯一")
    statement: str = Field(description="可验证的研究陈述，不得是套话")
    type: str = Field(default="RESULT", description="RESULT|METHOD|LIMITATION|CONTEXT")
    # 必填且至少 1 条引用：否则 qwen 的 strict json_schema 会省略 quotes 字段，
    # 导致 citations 为空、所有 claim 被 gate 拒绝。
    quotes: List[_Quote] = Field(min_length=1, description="至少 1 条原文引用")
    qualifiers: List[str] = Field(default_factory=list, description="适用条件，如'仅在单卡 A100'")
    rationale: str = ""


class _ClaimExtraction(BaseModel):
    claims: List[_ClaimItem] = Field(default_factory=list)


class _MapItemDraft(BaseModel):
    kind: str = Field(description="problem|method|result|limitation")
    claim_ids: List[str] = Field(default_factory=list)
    text: str = ""


class _SectionDraft(BaseModel):
    heading: str
    kind: str = "body"
    source_block_ids: List[str] = Field(default_factory=list)
    claim_ids: List[str] = Field(default_factory=list)
    summary: str = ""


class _MethodStepDraft(BaseModel):
    label: str
    detail: str = ""
    phase: str | None = None
    claim_ids: List[str] = Field(default_factory=list)


class _StructureDraft(BaseModel):
    sections: List[_SectionDraft] = Field(default_factory=list)
    map_items: List[_MapItemDraft] = Field(default_factory=list)
    method_steps: List[_MethodStepDraft] = Field(default_factory=list)


CLAIM_EXTRACTION_PROMPT = (
    "你是科研内容分析引擎。下面的正文块每块有 [B编号] 前缀（如 [B1]）。\n"
    "请提取**彼此独立的可验证研究陈述**（claim）：\n"
    "1. 每条 claim 必须带 1~2 个 quotes；每个 quote 的 block_id 必须填对应块的编号"
    "（如 \"B1\"，只填编号，不要填原文），quote 必须是该块**原文中真实存在的片段**，"
    "不得改写、不得编造。没有原文依据的 claim 不要输出。\n"
    "2. 保留数据集、指标、数字、适用条件（仅在…/假设…）与局限；不得把它们省略成「效果好」。\n"
    "3. 找不到原文依据的结论**不要输出**；不要为了凑数捏造 claim。\n"
    "4. claim_id 用简短英文/数字标识（≤32 字符）。\n"
    "5. 只返回 JSON，quotes 字段必须非空。\n"
)

STRUCTURE_PROMPT = (
    "你是科研内容编辑。基于**已验证**的断言与原文块，生成结构概览：\n"
    "1. sections：按原文块组织章节概览；summary 的每个事实都必须来自已给出的 claim/原文块，"
    "不得引入新事实，也不得篡改原文结论。\n"
    "2. map_items：problem/method/result/limitation 四类，用 claim_ids 关联，不要编造。\n"
    "3. method_steps：方法步骤按顺序，每一步用 claim_ids 关联依据。\n"
    "4. 只返回 JSON。\n"
)

__all__ = [
    "PER_SECTION_CHAR_BUDGET",
    "TOTAL_CHAR_BUDGET",
    "MAX_EXHIBIT_CLAIMS",
    "MAX_SCENE_COUNT",
    "MAX_METHOD_STEPS",
    "CLAIM_EXTRACTION_PROMPT",
    "STRUCTURE_PROMPT",
]
