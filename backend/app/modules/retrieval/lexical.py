"""M07 — 词法索引与打分（REFACTOR_SPEC §5.6）。

中文使用**字符 bigram**（不做分词，避免词典依赖），拉丁术语/数字/单位按词切分；
两侧混合索引，使「BERT」「0.87」「mA h g-1」这类查询在 SQLite 上也能精确命中。

设计取舍：
- 不做 stemmer/停用词表，避免中英混排时的误杀；用 IDF 抑制高频虚词。
- 打分采用 BM25（k1=1.2, b=0.75），比 TF-IDF 更抗长块偏置。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

#: 拉丁术语/数字/单位：允许内部 ``-``、``.``、``/``、``+``（如 g-1、1.2e-3、mA/g）
_LATIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-/]*[A-Za-z0-9]|[A-Za-z0-9]")
#: 中日韩统一表意文字（含扩展 A 与兼容区）
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

_CJK_BIGRAM = "cjk2"
_LATIN_TERM = "lat"

K1 = 1.2
B = 0.75


@dataclass(frozen=True)
class Term:
    """一个索引项：kind 让 bigram 与拉丁词在计数时互不干扰。"""

    kind: str
    text: str


def tokenize(text: str) -> List[Term]:
    """把任意混排文本切成检索项序列（保留顺序，允许重复）。"""
    if not text:
        return []
    terms: List[Term] = []
    cjk_run: List[str] = []

    def _flush_cjk() -> None:
        if not cjk_run:
            return
        if len(cjk_run) == 1:
            # 单字也建项，否则「图」这类单字查询永远命不中
            terms.append(Term(_CJK_BIGRAM, cjk_run[0]))
        else:
            for i in range(len(cjk_run) - 1):
                terms.append(Term(_CJK_BIGRAM, cjk_run[i] + cjk_run[i + 1]))
        cjk_run.clear()

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if _CJK_RE.match(ch):
            cjk_run.append(ch)
            i += 1
            continue
        _flush_cjk()
        m = _LATIN_RE.match(text, i)
        if m:
            piece = m.group(0)
            terms.append(Term(_LATIN_TERM, piece.lower()))
            i = m.end()
            continue
        i += 1
    _flush_cjk()
    return terms


def query_terms(query: str) -> List[str]:
    """查询项去重并保持出现顺序；返回 ``kind\\x1ftext`` 规范键。"""
    seen: Dict[str, None] = {}
    for term in tokenize(query):
        seen.setdefault(_key(term), None)
    return list(seen)


def _key(term: Term) -> str:
    return f"{term.kind}\x1f{term.text}"


def term_key(kind: str, text: str) -> str:
    return f"{kind}\x1f{text}"


@dataclass
class _Doc:
    chunk_id: str
    tf: Dict[str, int] = field(default_factory=dict)
    length: int = 0


class LexicalIndex:
    """内存倒排索引；每次检索按 revision 现建（块数量级为百，代价可忽略）。"""

    def __init__(self) -> None:
        self._docs: Dict[str, _Doc] = {}
        self._postings: Dict[str, List[str]] = {}
        self._total_len = 0

    def add(self, chunk_id: str, text: str) -> None:
        doc = _Doc(chunk_id=chunk_id)
        for term in tokenize(text):
            key = _key(term)
            doc.tf[key] = doc.tf.get(key, 0) + 1
            doc.length += 1
            self._postings.setdefault(key, []).append(chunk_id)
        self._docs[chunk_id] = doc
        self._total_len += doc.length

    @property
    def size(self) -> int:
        return len(self._docs)

    def _avgdl(self) -> float:
        if not self._docs:
            return 0.0
        return self._total_len / len(self._docs)

    def score(self, query: str, limit: int = 30) -> List[Tuple[str, float]]:
        """BM25 打分；返回按分数降序的 ``(chunk_id, score)``，最多 limit 条。"""
        keys = query_terms(query)
        if not keys or not self._docs:
            return []
        n_docs = len(self._docs)
        avgdl = self._avgdl() or 1.0
        acc: Dict[str, float] = {}

        for key in keys:
            posting = self._postings.get(key)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            for chunk_id in posting:
                doc = self._docs[chunk_id]
                tf = doc.tf.get(key, 0)
                if not tf:
                    continue
                denom = tf + K1 * (1.0 - B + B * (doc.length / avgdl))
                acc[chunk_id] = acc.get(chunk_id, 0.0) + idf * (tf * (K1 + 1.0)) / denom

        ranked = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:limit]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """安全余弦：维度不同或存在非有限值返回 0，绝不抛异常。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        if not (math.isfinite(x) and math.isfinite(y)):
            return 0.0
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


__all__ = [
    "Term",
    "tokenize",
    "query_terms",
    "term_key",
    "LexicalIndex",
    "cosine",
    "K1",
    "B",
]
