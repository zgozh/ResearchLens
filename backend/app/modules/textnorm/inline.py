"""行内标签白名单解析。

白名单：``<sup>`` ``<sub>`` ``<i>`` ``<b>`` ``<br>``（大小写不敏感）。
- 带属性一律**不认属性**（属性被丢弃，只认标签名）；
- 其余一切 ``<…>`` 序列按字面文本**转义保留** + UNKNOWN_TAG issue（规格第 5 条）。
"""
from __future__ import annotations

import re
from typing import Optional

#: 转成 AST 容器节点的白名单标签
CONTAINER_TAGS = frozenset({"sup", "sub", "i", "b"})
#: 转成 br 叶子节点的标签
BREAK_TAGS = frozenset({"br"})

#: 形如 ``<name attr=...>`` / ``</name>`` / ``<br/>``；属性里不允许出现 ``<>`` 与换行，
#: 避免把 ``a < b > c`` 这类数学比较误判成标签。
TAG_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)((?:\s[^<>\n]*)?)(/?)>")


def match_tag(text: str, pos: int) -> Optional["re.Match[str]"]:
    """在 ``pos`` 处尝试匹配一个标签（``text[pos] == "<"``）。"""
    if pos >= len(text) or text[pos] != "<":
        return None
    return TAG_RE.match(text, pos)


def classify(name: str) -> str:
    """标签分类：``container`` / ``br`` / ``unknown``。"""
    lowered = name.lower()
    if lowered in BREAK_TAGS:
        return "br"
    if lowered in CONTAINER_TAGS:
        return "container"
    return "unknown"


__all__ = ["CONTAINER_TAGS", "BREAK_TAGS", "TAG_RE", "match_tag", "classify"]
