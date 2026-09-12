"""问题（``TextIssue``）构造与片段截断。

集中一处，保证：excerpt 恒 ≤80 字符（契约要求）、offset 恒指向**原始输入**下标。
"""
from __future__ import annotations

from typing import Optional

from app.contracts.textnorm import IssueCode, TextIssue

#: 契约要求：excerpt ≤80 字符
EXCERPT_LIMIT = 80


def excerpt(fragment: str, *, limit: int = EXCERPT_LIMIT) -> str:
    """把问题片段压到 ≤``limit`` 字符（超出时末位放省略号，总长仍不超限）。"""
    text = fragment if fragment is not None else ""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "\u2026"


def make_issue(
    code: IssueCode,
    fragment: str,
    offset: Optional[int] = None,
    *,
    severity: str = "warn",
) -> TextIssue:
    """构造一条 issue；``fragment`` 自动截断，``offset`` 为原始输入中的 0-based 下标。"""
    return TextIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        excerpt=excerpt(fragment),
        offset=offset,
    )


__all__ = ["EXCERPT_LIMIT", "excerpt", "make_issue"]
