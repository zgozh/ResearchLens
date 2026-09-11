"""M04 — 引用定位与原文匹配（REFACTOR_SPEC §5.4、§6.6）。

职责边界（硬约束）：
- ``source_text`` **永远由服务端从原文 Block 拼接**，绝不采用 LLM 提供的
  ``proposed_quote`` 直接当原文；
- 规范化匹配（空白折叠、连字统一、全角/半角、大小写）必须带回**原始 offset map**，
  保证 ``QuoteSpan.start_cp/end_cp/source_text`` 指向原始字符串的真实切片；
- 模糊相似（跨字符改写）**只产生候选**，不得伪造精确 quote；
- 同页 / 正则 / 图号字符串**只产生候选**，不构成 certified；
- **定位成功 ≠ 支持成立**：本模块只回答"引用是否落在原文里"，语义另判。
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from app.contracts.common import AnchorId, BlockId, Scope
from app.contracts.documents import Block, QuoteSpan

#: 规范化算法版本；进入 QuoteSpan.normalizer_version 与评测版本
NORMALIZER_VERSION = "rl.norm/1"

#: 模糊相似进入候选的下限（低于该值视为无关）
FUZZY_CANDIDATE_THRESHOLD = 0.72

#: 语义（未走 LLM 时）允许规则放行的最低字面重合度。
#: 低于该值一律 insufficient —— 不允许"无 LLM 自动通过语义 gate"。
RULE_SUPPORT_THRESHOLD = 0.90

#: 数字 / 单位 / 条件限定词模式（用于 numeric/qualifier gate）
_NUMBER_RE = re.compile(
    r"\d+(?:[.,]\d+)*(?:\s*%)?|"
    r"[一二三四五六七八九十百千万亿零]+(?:个|万|亿|千|百|十)?"
)
_UNIT_RE = re.compile(
    r"%|‰|ms|s|min|h|Hz|kHz|MHz|GHz|MB|GB|KB|TB|mm|cm|m|km|nm|um|μm|"
    r"kg|g|mg|L|mL|Pa|kPa|MPa|dB|bit|bps|W|kW|°|℃|倍|人|篇|次|轮|层|维|×|x",
    re.IGNORECASE,
)
#: "仅在 / 只有在 / 限于 / 前提 / 前提是 / 假设 / 假设在" 等适用条件限定语
_QUALIFIER_RE = re.compile(
    r"仅在|只有在|只在|仅限于|限于|前提是?|假设在|假设|假定|条件下|"
    r"\bonly\s+(?:when|if|in)\b|\bunder\s+the\s+condition\b|\bassum(?:e|ing)\b",
    re.IGNORECASE,
)


@dataclass
class NormalizedText:
    """规范化结果 + 原始 offset map。

    ``norm[i]`` 对应原文 ``origin[i]`` 位置的 code point；
    因此 ``原始 start = origin[i_start]``，``原始 end = origin[i_end-1] + 1``。
    """

    raw: str
    norm: str
    origin: List[int] = field(default_factory=list)

    def to_raw_span(self, start_norm: int, end_norm: int) -> Optional[Tuple[int, int]]:
        if start_norm < 0 or end_norm <= start_norm or end_norm > len(self.origin):
            return None
        return self.origin[start_norm], self.origin[end_norm - 1] + 1


#: 连字 / 常见排版变体的确定性映射（不是模糊相似）
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2010": "-", "\u2011": "-",
    "\u00a0": " ",
}


def normalize_with_map(text: str, *, fold_case: bool = False) -> NormalizedText:
    """规范化文本并保留原始 offset map。

    转换集合（已定义、可回溯）：
    1. NFKC 兼容分解（全角→半角、上标数字等）；
    2. 连字与排版破折号映射；
    3. 空白字符折叠为单个半角空格，并去除首尾空白；
    4. （可选）大小写折叠。

    每个输出码位记录其来源原文码位，因此任何规范匹配都能映射回原始切片。
    """
    out_chars: List[str] = []
    origin: List[int] = []
    pending_space = False
    for idx, ch in enumerate(text):
        mapped = _LIGATURES.get(ch, ch)
        # NFKC 可能把一个字符扩成多个（如 ① → 1）；逐字符展开并复用同一 origin
        decomposed = unicodedata.normalize("NFKC", mapped) or mapped
        if fold_case:
            decomposed = decomposed.casefold()
        if decomposed.strip() == "":
            # 空白：折叠为单个空格（延迟写入，避免尾部空格）
            pending_space = bool(out_chars)
            continue
        if pending_space:
            out_chars.append(" ")
            origin.append(idx)
            pending_space = False
        for sub in decomposed:
            if sub.strip() == "":
                continue
            out_chars.append(sub)
            origin.append(idx)
    return NormalizedText(raw=text, norm="".join(out_chars), origin=origin)


def char_bigrams(text: str) -> List[str]:
    """字符 bigram（中文无空格也能召回）；长度 1 时退化为单字。"""
    cleaned = re.sub(r"\s+", "", text)
    if len(cleaned) < 2:
        return [cleaned] if cleaned else []
    return [cleaned[i:i + 2] for i in range(len(cleaned) - 1)]


def lexical_overlap(a: str, b: str) -> float:
    """bigram 集合的 Jaccard 相似度（0..1）；只用于**候选/规则**判断。"""
    ga, gb = set(char_bigrams(a)), set(char_bigrams(b))
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def containment(needle: str, haystack: str) -> float:
    """needle 的 bigram 有多大比例出现在 haystack 中（0..1）。

    与 :func:`lexical_overlap`（对称 Jaccard）不同，这是**非对称覆盖率**：
    陈述是证据的子集时应当接近 1，即使证据本身很长。
    """
    gn, gh = set(char_bigrams(needle)), set(char_bigrams(haystack))
    if not gn:
        return 0.0
    if not gh:
        return 0.0
    return len(gn & gh) / len(gn)


def strip_boilerplate(text: str) -> str:
    """去掉"本文/该方法/作者"等指代性套话与标点，只留下主张的实词。

    仅用于**规则层**的字面重合度估计；不改变任何持久化文本。
    """
    cleaned = text or ""
    for token in ("本文提出的", "本文", "该方法", "该模型", "该方案", "本方法",
                  "作者", "我们", "研究表明", "实验表明"):
        cleaned = cleaned.replace(token, "")
    return re.sub(r"[\s，。、；：,.;:!?！？（）()\[\]“”\"'‘’]", "", cleaned)


def ratio(a: str, b: str) -> float:
    """difflib 序列相似度；只用于候选打分，不冒充精确 quote。"""
    if not a or not b:
        return 0.0
    return float(difflib.SequenceMatcher(None, a, b).ratio())


# --------------------------------------------------------------- 匹配结果


@dataclass
class QuoteMatch:
    """一次引用匹配的结果。

    ``kind``：
    - ``exact``：proposed_quote 是原文的**精确子串**；
    - ``normalized``：规范化后可回溯到原始切片（match_method=normalized）；
    - ``fuzzy``：只相似，**仅候选**，不产生 QuoteSpan；
    - ``missing``：完全找不到。
    """

    kind: str
    block_id: BlockId
    span: Optional[QuoteSpan] = None
    score: float = 0.0
    reason: str = ""

    @property
    def is_precise(self) -> bool:
        return self.kind in ("exact", "normalized")


def match_quote(block: Block, proposed_quote: str) -> QuoteMatch:
    """在**单个 Block 的原文**中匹配候选引用。"""

    quote = (proposed_quote or "").strip()
    if not quote:
        return QuoteMatch(kind="missing", block_id=block.id, reason="引用为空")

    raw = block.text or ""
    # 1) 精确子串（最高优先；大小写/空白都算不同）
    pos = raw.find(quote)
    if pos >= 0:
        span = QuoteSpan(
            block_id=block.id, start_cp=pos, end_cp=pos + len(quote),
            source_text=raw[pos:pos + len(quote)], match_method="exact",
        )
        return QuoteMatch(kind="exact", block_id=block.id, span=span, score=1.0)

    # 2) 规范化匹配（带回原始 offset map）
    if not raw:
        return QuoteMatch(kind="missing", block_id=block.id, reason="原文为空")
    norm_block = normalize_with_map(raw)
    norm_quote = normalize_with_map(quote, fold_case=True)
    if norm_quote.norm and norm_block.norm:
        npos = norm_block.norm.casefold().find(norm_quote.norm)
        if npos >= 0:
            mapped = norm_block.to_raw_span(npos, npos + len(norm_quote.norm))
            if mapped is not None:
                start, end = mapped
                span = QuoteSpan(
                    block_id=block.id, start_cp=start, end_cp=end,
                    source_text=raw[start:end], match_method="normalized",
                    normalizer_version=NORMALIZER_VERSION,
                )
                return QuoteMatch(
                    kind="normalized", block_id=block.id, span=span, score=0.99,
                    reason="规范化可回溯匹配",
                )

    # 3) 模糊：只产生候选，绝不伪造精确 quote
    score = max(lexical_overlap(raw, quote), ratio(raw, quote))
    if score >= FUZZY_CANDIDATE_THRESHOLD:
        return QuoteMatch(
            kind="fuzzy", block_id=block.id, score=round(score, 4),
            reason="仅字面相似，需人工/模型复核，不作为精确 quote",
        )
    return QuoteMatch(kind="missing", block_id=block.id, score=round(score, 4),
                      reason="原文中找不到该引用")


def locate_in_blocks(
    blocks: Sequence[Block], block_id: BlockId, proposed_quote: str
) -> QuoteMatch:
    """按 LLM **指定的 block_id** 定位；不接受 LLM 自报页码/坐标。"""
    for block in blocks:
        if block.id == block_id:
            return match_quote(block, proposed_quote)
    return QuoteMatch(kind="missing", block_id=block_id, reason="引用的 block 不在本 scope 原文中")


def locate_anywhere(
    blocks: Sequence[Block], proposed_quote: str, *, preferred_page: Optional[int] = None
) -> List[Tuple[Block, QuoteMatch]]:
    """在**给定块集合内**搜索引用（用于候选发现，不用于认证）。

    这只是"可能出现在哪儿"的候选发现；即使命中精确子串也不直接 certified，
    仍需通过 block 身份/是否 LLM 指定过的判定。
    """
    hits: List[Tuple[Block, QuoteMatch]] = []
    for block in blocks:
        m = match_quote(block, proposed_quote)
        if m.kind == "missing":
            continue
        if preferred_page is not None:
            # 同页优先排序用，不排除其它页
            pass
        hits.append((block, m))
    hits.sort(key=lambda item: (item[1].kind != "exact", -item[1].score))
    return hits


def join_source_text(blocks: Sequence[Block]) -> str:
    """服务端从**原文 Block** 拼接 source_text，保留分段边界。

    使用换行保留段落边界，不使用模型给出的任何文本。
    """
    parts = [(b.text or "").strip() for b in blocks]
    return "\n".join(p for p in parts if p)


# --------------------------------------------------------------- 内容检查


def numbers_in(text: str) -> List[str]:
    """抽取数字（含中文数词），用于 numeric gate。"""
    return [m.group(0).strip() for m in _NUMBER_RE.finditer(text or "") if m.group(0).strip()]


def units_in(text: str) -> List[str]:
    return [m.group(0).strip().lower() for m in _UNIT_RE.finditer(text or "")]


def has_qualifier(text: str) -> bool:
    return bool(_QUALIFIER_RE.search(text or ""))


def qualifiers_in(text: str) -> List[str]:
    return [m.group(0).strip() for m in _QUALIFIER_RE.finditer(text or "")]


def numeric_consistency(statement: str, evidence_text: str) -> str:
    """数字/单位一致性检查。

    返回 ``pass`` / ``fail`` / ``not_applicable``：
    - 陈述里出现的数字若在证据里毫无踪迹 → ``fail``（不许凭"证据非空"过关）；
    - 陈述出现单位而证据没有任何单位 → ``fail``；
    - 陈述不含数字/单位 → ``not_applicable``。
    """
    stmt_nums = numbers_in(statement)
    ev_nums = numbers_in(evidence_text)
    if stmt_nums:
        ev_set = {n for n in ev_nums}
        # 陈述里**任一**数字在证据中不见踪迹 → fail。
        # 这是为了抓住"数字被改写/删除"（91.2% 改成 99.9%、3.4 → 12.8）这类
        # 最常见的伪造；宁可保守拒绝，也不放过篡改。
        missing = [n for n in stmt_nums if n not in ev_set]
        if missing:
            return "fail"
    stmt_units = units_in(statement)
    if stmt_units and not units_in(evidence_text):
        return "fail"
    if not stmt_nums and not stmt_units:
        return "not_applicable"
    return "pass"


def qualifier_consistency(statement: str, evidence_text: str) -> str:
    """适用条件检查：陈述里的"仅在…/假设…"必须在证据中也有对应限定。

    返回 ``pass`` / ``fail`` / ``not_applicable``。
    """
    stmt_q = qualifiers_in(statement)
    if not stmt_q:
        return "not_applicable"
    ev_q = qualifiers_in(evidence_text)
    if not ev_q and not has_qualifier(evidence_text):
        return "fail"
    return "pass"


@dataclass
class PageRef:
    """block → 物理页的解析结果（供 anchor 构造使用）。"""

    block_id: BlockId
    page_id: str
    pdf_page_index: int
    page_label: Optional[str] = None


__all__ = [
    "NORMALIZER_VERSION",
    "FUZZY_CANDIDATE_THRESHOLD",
    "RULE_SUPPORT_THRESHOLD",
    "NormalizedText",
    "QuoteMatch",
    "PageRef",
    "normalize_with_map",
    "char_bigrams",
    "lexical_overlap",
    "containment",
    "strip_boilerplate",
    "ratio",
    "match_quote",
    "locate_in_blocks",
    "locate_anywhere",
    "join_source_text",
    "numbers_in",
    "units_in",
    "has_qualifier",
    "qualifiers_in",
    "numeric_consistency",
    "qualifier_consistency",
]


def _anchor_id_unused(scope: Scope, anchor: AnchorId) -> None:  # pragma: no cover
    """保留类型引用，避免 linters 误删 AnchorId 导入。"""
    _ = (scope, anchor)
