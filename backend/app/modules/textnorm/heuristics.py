"""``kind="header"`` 的作者/机构/邮箱行特判。

真实样本（MinerU 抽出的论文首页）::

    Ashish Vaswani<sup>∗</sup> Google Brain avaswani@google.com
    Ashish Vaswani∗ Google Brain avaswani@google.com     ← 上标符号可能是裸字符

规则（规格第 6 条）：识别「人名 + 上标符号 + 机构 + 邮箱」，把**上标符号 run**
归入 ``sup`` 容器的 children；邮箱与机构文本保持 text 节点；**不删除任何字符**。

实现方式：在事件流上做**后处理切片**（而不是重写原串），这样其他 issue 的
``offset`` 仍然精确指向原始输入。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

#: 上标符号（规格列举）：∗ † ‡ § ¶
MARK_CHARS = "\u2217\u2020\u2021\u00a7\u00b6"
MARK_RE = re.compile(f"[{MARK_CHARS}]+")
#: 邮箱（用于判定「这一行是作者/机构行」）
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def email_line_starts(text: str) -> set:
    """返回包含邮箱的每一行的起始下标集合。"""
    starts = set()
    for match in EMAIL_RE.finditer(text):
        starts.add(text.rfind("\n", 0, match.start()) + 1)
    return starts


def split_mark_run(
    content: str, *, line_email_at: Optional[int], absolute_start: int
) -> Optional[Tuple[str, str, str]]:
    """把一段文本切成 ``(head, marks, tail)``；不满足「人名 + 上标」模式时返回 None。

    - ``head`` 必须以**字母/数字**结尾（人名），因此 ``∗`` 出现在行首不触发；
    - 上标 run 必须出现在本行邮箱**之前**（人的上标脚注在机构/邮箱之前）。
    """
    match = MARK_RE.search(content)
    if match is None:
        return None
    idx = match.start()
    head = content[:idx]
    trimmed = head.rstrip()
    if not trimmed or not trimmed[-1].isalnum():
        return None
    if line_email_at is not None and absolute_start + idx >= line_email_at:
        return None
    return head, match.group(0), content[match.end() :]


def expand_header_events(events: List, raw: str) -> List:
    """对事件流做 header 后处理；``events`` 元素需有 ``kind/text/start/end`` 属性。"""
    if not events or not EMAIL_RE.search(raw):
        return events
    line_starts = email_line_starts(raw)
    if not line_starts:
        return events
    email_positions = {m.start() for m in EMAIL_RE.finditer(raw)}

    out: List = []
    for event in events:
        if event.kind != "text" or event.start < 0:
            out.append(event)
            continue
        # 只在「原串与文本逐字相同」时切片，保证下标换算精确
        if raw[event.start : event.end] != event.text:
            out.append(event)
            continue
        line_start = raw.rfind("\n", 0, event.start) + 1
        if line_start not in line_starts:
            out.append(event)
            continue
        next_email = min((p for p in email_positions if p >= line_start), default=None)
        split = split_mark_run(
            event.text, line_email_at=next_email, absolute_start=event.start
        )
        if split is None:
            out.append(event)
            continue
        head, marks, tail = split
        if head:
            out.append(_like(event, kind="text", text=head, start=event.start, end=event.start + len(head)))
        open_at = event.start + len(head)
        out.append(_like(event, kind="open", text="", tag="sup", start=open_at, end=open_at))
        out.append(
            _like(event, kind="text", text=marks, start=open_at, end=open_at + len(marks))
        )
        close_at = open_at + len(marks)
        out.append(_like(event, kind="close", text="", tag="sup", start=close_at, end=close_at))
        if tail:
            out.append(
                _like(event, kind="text", text=tail, start=close_at, end=event.end)
            )
    return out


def _like(event, *, kind: str, text: str, start: int, end: int, tag: str = ""):
    """复制一个同类型事件（避免 heuristics 反向依赖 core 的事件类）。"""
    clone = type(event)(
        kind=kind, text=text, tag=tag, tag_no=None, start=start, end=end
    )
    return clone


__all__ = [
    "MARK_CHARS",
    "EMAIL_RE",
    "email_line_starts",
    "split_mark_run",
    "expand_header_events",
]
