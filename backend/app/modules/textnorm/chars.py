"""字符级卫生：控制符判定、HTML 转义、全角→半角映射。

分层原则：本模块**只做单字符/字符表**的事，不感知公式与标签结构。
"""
from __future__ import annotations

from typing import Dict, Tuple

#: 保留的“控制符”：换行与制表符（契约要求保留）
_KEEP = {"\n", "\t"}
#: C0（0x00-0x1F，不含保留项）+ DEL（0x7F）+ C1（0x80-0x9F）
_CONTROL = {chr(c) for c in range(0x00, 0x20)} - _KEEP
_CONTROL.add("\x7f")
_CONTROL.update(chr(c) for c in range(0x80, 0xA0))

#: 全角 ASCII（U+FF01-U+FF5E）→ 半角；另加表意空格。
#: 注意：``str.translate`` 的表必须按 **ordinal** 索引，所以这里再 maketrans 一次。
FULLWIDTH_TO_ASCII: Dict[str, str] = {
    chr(0xFF01 + d): chr(0x21 + d) for d in range(0x5E)
}
FULLWIDTH_TO_ASCII["\u3000"] = " "

_TRANSLATE_TABLE = str.maketrans(FULLWIDTH_TO_ASCII)

#: HTML 文本转义表（未知标签按字面文本转义保留）
_HTML_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def is_control(ch: str) -> bool:
    """是否为需要剥离的控制符（``\\n``/``\\t`` 不算）。"""
    return ch in _CONTROL


def escape_html_text(text: str) -> str:
    """把未知标签字面量转义成实体形式（``<unk>`` → ``&lt;unk&gt;``）。

    为什么必须转义：plain 里若原样留下 ``<unk>``，下一次 ``normalize(plain)``
    会再次命中 UNKNOWN_TAG —— 幂等（规格第 9 条）与「原样保留」在纯字符串上
    不可兼得；转义是唯一同时满足「不丢字符」与「幂等」的编码（详见交付报告
    第 4 节「偏离与补充决策」）。
    """
    return "".join(_HTML_ESCAPE.get(c, c) for c in text)


def normalize_fullwidth(text: str) -> Tuple[str, bool]:
    """全角→半角（仅用于公式体）。返回 (新串, 是否发生变化)。"""
    if not text:
        return text, False
    out = text.translate(_TRANSLATE_TABLE)
    return out, out != text


__all__ = [
    "FULLWIDTH_TO_ASCII",
    "is_control",
    "escape_html_text",
    "normalize_fullwidth",
]