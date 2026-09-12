"""公式体处理：``\\tag`` 剥离、MinerU 空格修复、全角归一半角。

**只作用于公式体内部**；正文一个空格都不动（规格第 4/8 条）。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .chars import normalize_fullwidth

#: ``\tag{N}`` —— 编号取出、命令本体剥离（仅块级）
_TAG_CMD_RE = re.compile(r"\\tag\s*\{([^{}]*)\}")
#: 任何 ``\tag`` 痕迹（用于行内公式的 LATEX_SUSPECT 判定）
_TAG_ANY_RE = re.compile(r"\\tag\b")

#: 文本模式命令：其花括号内容里的空格是**语义**（``\text{hello world}``），必须保护
_TEXT_CMD_RE = re.compile(
    r"\\(?:text|textrm|textit|textbf|textnormal|mbox|operatorname\*?)\s*"
    r"\{(?:[^{}]|\{[^{}]*\})*\}"
)

_PROTECT_OPEN = "\ue000"
_PROTECT_CLOSE = "\ue001"
_PROTECT_RE = re.compile(_PROTECT_OPEN + r"(\d+)" + _PROTECT_CLOSE)


def extract_tag(body: str) -> Tuple[str, Optional[str]]:
    """从块级公式体剥离 ``\\tag{N}``，返回 (剩余体, 编号)。

    编号为 ``\\tag{}`` 的空内容时返回 ``None``（不算编号）。
    """
    if not body or not _TAG_ANY_RE.search(body):
        return body, None
    tag_no: Optional[str] = None
    for match in _TAG_CMD_RE.finditer(body):
        value = match.group(1).strip()
        if value and tag_no is None:
            tag_no = value
    stripped = _TAG_CMD_RE.sub(" ", body)
    return stripped, tag_no


def has_tag_command(body: str) -> bool:
    """公式体里是否出现 ``\\tag``（行内公式据此产出 LATEX_SUSPECT）。"""
    return bool(body) and bool(_TAG_ANY_RE.search(body))


def join_single_char_runs(text: str) -> str:
    """把「单字符之间被空格打断」的序列粘回去：``0 . 1`` → ``0.1``、``d r o p`` → ``drop``。

    MinerU 逐字排版会把 ``P _ { d r o p }`` 拆成单字符 token。规则：**整段**都由
    单字符 token 组成时才粘连；一旦遇到多字符 token（``\\sqrt``、``1.0``）就断开，
    因此 ``1.0 \\cdot 10^{20}`` 的语义空格不受影响。

    已知取舍：``\\int f d x`` 这类「相邻单字符但本意有空格」的写法也会被粘连。
    数学模式下 TeX/KaTeX 本来就忽略这些空格（渲染结果完全相同），只有纯文本
    阅读会略受影响 —— 换取 ``P _ { d r o p }`` 这类真实脏数据的正确还原，值。
    """
    if not text:
        return text
    parts = re.split(r"([ \t\r\n]+)", text)
    words: List[str] = parts[0::2]
    seps: List[str] = parts[1::2]
    total = len(words)
    if total <= 1:
        return text
    out: List[str] = []
    i = 0
    while i < total:
        if len(words[i]) == 1:
            j = i
            while j + 1 < total and len(words[j + 1]) == 1:
                j += 1
            if j > i:
                out.append("".join(words[i : j + 1]))
                if j < total - 1:
                    out.append(seps[j])
                i = j + 1
                continue
        out.append(words[i])
        if i < total - 1:
            out.append(seps[i])
        i += 1
    return "".join(out)


def compact_body(body: str) -> str:
    """压缩公式体内的多余空格（幂等：压缩结果再压缩不变）。"""
    if not body:
        return body

    protected: List[str] = []

    def _protect(match: "re.Match[str]") -> str:
        protected.append(match.group(0))
        return f"{_PROTECT_OPEN}{len(protected) - 1}{_PROTECT_CLOSE}"

    out = _TEXT_CMD_RE.sub(_protect, body)

    # 1) 单字符 run 先粘（``P _ { d r o p }`` → ``P_{drop}``）
    out = join_single_char_runs(out)
    # 2) 结构符两侧的空格：``{``/``}``/``_``/``^``/``=``
    out = re.sub(r"(?<!\\)\{\s+", "{", out)
    out = re.sub(r"\s+(?<!\\)\}", "}", out)
    out = re.sub(r"([_^])\s+", r"\1", out)
    out = re.sub(r"\s+([_^])", r"\1", out)
    out = re.sub(r"\s*=\s*", "=", out)
    # 3) 控制序列与花括号之间：``\sqrt {`` → ``\sqrt{``
    out = re.sub(r"(\\[A-Za-z]+)\s+(?=\{)", r"\1", out)

    def _restore(match: "re.Match[str]") -> str:
        return protected[int(match.group(1))]

    return _PROTECT_RE.sub(_restore, out)


def prepare_math_body(
    raw_body: str, *, block: bool
) -> Tuple[str, Optional[str], bool, bool, bool]:
    """公式体流水线：全角归一 → （块级）剥 ``\\tag`` → 压缩空格。

    返回 ``(body, tag_no, width_changed, compacted, inline_tag_left)``：

    - ``width_changed``：全角/半角发生归一（→ MIXED_WIDTH issue）
    - ``compacted``：压缩改变了 body（→ LATEX_SUSPECT(info) issue）
    - ``inline_tag_left``：行内公式里残留 ``\\tag``（→ LATEX_SUSPECT(warn) issue）
    """
    work, width_changed = normalize_fullwidth(raw_body)
    tag_no: Optional[str] = None
    stripped = work
    inline_tag_left = False
    if block:
        stripped, tag_no = extract_tag(work)
    else:
        inline_tag_left = has_tag_command(work)
    stripped = stripped.strip()
    compacted_body = compact_body(stripped)
    return compacted_body, tag_no, width_changed, compacted_body != stripped, inline_tag_left


__all__ = [
    "extract_tag",
    "has_tag_command",
    "join_single_char_runs",
    "compact_body",
    "prepare_math_body",
]
