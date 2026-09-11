"""M07 — 分块（REFACTOR_SPEC §5.6）。

规则：
- **只消费 ``origin=source_extraction`` 的块**，绝不把 AI 摘要当一级证据；
- 保留章节路径、图题/表头与行列上下文；
- 同页相邻段落合并到目标字符数，跨块引文保留多个 ``block_ids``/``anchor_ids``；
- ``content_hash`` 用规范化后的正文，供 ``uq_chunk_revision_hash`` 去重。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from app.contracts.documents import BlockKind

#: 目标块大小（字符）。中文 bigram 索引下，过小的块会让 IDF 失去区分度。
TARGET_CHARS = 700
MAX_CHARS = 1400
MIN_CHARS = 80

#: 这些 kind 自带结构语义，尽量不与其他块合并
_STANDALONE_KINDS = {"caption", "table", "equation", "heading", "image"}

#: 表/图题前缀识别，用于标注 ``context`` 行
_LABEL_PREFIXES = ("图", "表", "式", "fig", "table", "figure", "eq", "equation")


@dataclass(frozen=True)
class SourceBlock:
    """从 ORM 投影出的冻结原文块快照（离开 Session 后仍可读）。"""

    id: str
    page_index: int
    ordinal: int
    kind: str
    text: str
    anchor_id: Optional[str]
    media_id: Optional[str]
    section_path: List[str]


@dataclass
class ChunkDraft:
    ordinal: int
    text: str
    block_ids: List[str] = field(default_factory=list)
    anchor_ids: List[str] = field(default_factory=list)
    media_ids: List[str] = field(default_factory=list)
    section_path: List[str] = field(default_factory=list)
    content_hash: str = ""
    token_estimate: int = 0

    def finalize(self) -> "ChunkDraft":
        self.content_hash = hash_text(self.text)
        self.token_estimate = estimate_tokens(self.text)
        return self


def hash_text(text: str) -> str:
    normalized = normalize_for_hash(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_for_hash(text: str) -> str:
    """去空白差异，避免仅格式不同的块被当成两份独立证据。"""
    return " ".join((text or "").split())


def estimate_tokens(text: str) -> int:
    """粗估：CJK 约 1 token/字，拉丁约 1 token/4 字符。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff")
    other = len(text) - cjk
    return int(cjk + other / 4) + 1


def is_standalone(kind: str) -> bool:
    return kind in _STANDALONE_KINDS


def block_context_line(block: SourceBlock) -> str:
    """为 caption/table 补一行结构说明，让检索能命中「表头」「图题」这类词。"""
    parts: List[str] = []
    if block.section_path:
        parts.append("章节：" + " / ".join(block.section_path))
    lowered = (block.text or "").strip().lower()
    if block.kind == "caption" and any(lowered.startswith(p) for p in _LABEL_PREFIXES):
        parts.append("图题/表题")
    elif block.kind == "table":
        parts.append("表格内容（含表头行）")
    elif block.kind == "equation":
        parts.append("公式")
    elif block.kind == "heading":
        parts.append("章节标题")
    if not parts:
        return ""
    return "【" + "；".join(parts) + "】"


def build_chunks(blocks: Sequence[SourceBlock]) -> List[ChunkDraft]:
    """把原文块聚合成分块草稿（按原顺序）。"""
    drafts: List[ChunkDraft] = []
    buf: List[SourceBlock] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        if not buf:
            return
        drafts.append(_merge(buf, len(drafts)).finalize())
        buf = []
        buf_len = 0

    for block in blocks:
        if not (block.text or "").strip():
            continue
        piece_len = len(block.text) + len(block_context_line(block))

        if is_standalone(block.kind):
            flush()
            drafts.append(_merge([block], len(drafts)).finalize())
            continue

        if buf and buf_len + piece_len > MAX_CHARS:
            flush()
        buf.append(block)
        buf_len += piece_len
        if buf_len >= TARGET_CHARS:
            flush()

    if buf:
        # 尾部过短则并入上一块（避免产生只有一句话的噪声块）
        if buf_len < MIN_CHARS and drafts:
            last = drafts[-1]
            extra = _merge(buf, last.ordinal)
            merged_text = (last.text + "\n" + extra.text).strip()
            drafts[-1] = ChunkDraft(
                ordinal=last.ordinal,
                text=merged_text,
                block_ids=last.block_ids + extra.block_ids,
                anchor_ids=_dedup(last.anchor_ids + extra.anchor_ids),
                media_ids=_dedup(last.media_ids + extra.media_ids),
                section_path=last.section_path or extra.section_path,
            ).finalize()
        else:
            flush()

    return drafts


def _merge(blocks: Sequence[SourceBlock], ordinal: int) -> ChunkDraft:
    lines: List[str] = []
    block_ids: List[str] = []
    anchor_ids: List[str] = []
    media_ids: List[str] = []
    section_path: List[str] = []
    for block in blocks:
        ctx = block_context_line(block)
        lines.append(f"{ctx}\n{block.text}".strip() if ctx else block.text)
        block_ids.append(block.id)
        if block.anchor_id:
            anchor_ids.append(block.anchor_id)
        if block.media_id:
            media_ids.append(block.media_id)
        if not section_path and block.section_path:
            section_path = list(block.section_path)
    return ChunkDraft(
        ordinal=ordinal,
        text="\n".join(lines).strip(),
        block_ids=block_ids,
        anchor_ids=_dedup(anchor_ids),
        media_ids=_dedup(media_ids),
        section_path=section_path,
    )


def _dedup(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


__all__ = [
    "TARGET_CHARS",
    "MAX_CHARS",
    "MIN_CHARS",
    "SourceBlock",
    "ChunkDraft",
    "build_chunks",
    "hash_text",
    "normalize_for_hash",
    "estimate_tokens",
    "block_context_line",
    "is_standalone",
]
