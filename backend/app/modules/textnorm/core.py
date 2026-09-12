"""textnorm 核心：单遍扫描 → 事件流 → 富文本 AST → 干净 plain。

设计（为什么要单遍）：
- issue 的 ``offset`` 必须指向**原始输入**，因此扫描在原串上进行，控制符是"跳过"
  而不是"先删掉再算"；
- ``plain`` **由 AST 推导**（不是另一条并行路径），这样规格第 11 条
  「plain == 全部叶子文本拼接」由构造保证，不可能漂移。

对外只暴露 ``normalize`` 与 ``scan``（见 ``__init__``）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Tuple

from app.contracts.textnorm import NormalizedText, RichNode, TextIssue

from .chars import escape_html_text, is_control
from .heuristics import expand_header_events
from .inline import classify, match_tag
from .issues import make_issue
from .latex import prepare_math_body

TextKind = Literal["body", "caption", "header"]


@dataclass
class _Ev:
    """扫描事件（构建 AST 的中间表示）。"""

    kind: str  # text | math_inline | math_block | open | close | br
    text: str = ""
    tag: str = ""
    tag_no: Optional[str] = None
    start: int = -1
    end: int = -1


# ------------------------------------------------------------------ 定界符查找


def _escaped(raw: str, pos: int) -> bool:
    """``pos`` 处字符是否被奇数个反斜杠转义。"""
    backslashes = 0
    k = pos - 1
    while k >= 0 and raw[k] == "\\":
        backslashes += 1
        k -= 1
    return backslashes % 2 == 1


def _find_inline_close(raw: str, start: int) -> int:
    """找行内公式的收尾 ``$``（未转义）。"""
    j = start
    n = len(raw)
    while j < n:
        if raw[j] == "\\":
            j += 2
            continue
        if raw[j] == "$":
            return j
        j += 1
    return -1


def _find_block_close(raw: str, start: int) -> int:
    """找块级公式的收尾 ``$$``（未转义）。"""
    j = start
    while True:
        idx = raw.find("$$", j)
        if idx == -1:
            return -1
        if not _escaped(raw, idx):
            return idx
        j = idx + 1


def _find_command_close(raw: str, start: int, delim: str) -> int:
    """找 ``\\)`` / ``\\]`` 收尾（未转义）。"""
    j = start
    while True:
        idx = raw.find(delim, j)
        if idx == -1:
            return -1
        if not _escaped(raw, idx):
            return idx
        j = idx + 1


# ------------------------------------------------------------------ 扫描


def _tokenize(raw: str, kind: TextKind) -> Tuple[List[_Ev], List[TextIssue]]:
    events: List[_Ev] = []
    issues: List[TextIssue] = []
    n = len(raw)
    i = 0
    open_stack: List[str] = []

    while i < n:
        ch = raw[i]

        # 1) 控制符：剥离（保留 \n \t），连续区段合并为一条 issue
        if is_control(ch):
            j = i
            while j < n and is_control(raw[j]):
                j += 1
            issues.append(make_issue("CONTROL_CHAR", raw[i:j], i))
            i = j
            continue

        # 2) 反斜杠：\$ 字面美元；\( \) 行内；\[ \] 块级；其余原样
        if ch == "\\":
            nxt = raw[i + 1] if i + 1 < n else ""
            if nxt == "$":
                events.append(_Ev("text", "\\$", start=i, end=i + 2))
                i += 2
                continue
            if nxt in "([":
                delim = "\\)" if nxt == "(" else "\\]"
                end = _find_command_close(raw, i + 2, delim)
                if end != -1:
                    result = _math_event(
                        raw, start=i, open_len=2, body_end=end, end=end + 2,
                        block=(nxt == "["),
                    )
                    _emit_math(result, events, issues)
                    i = end + 2
                else:
                    # 未配对 \( / \[：按字面文本保留，且**不产 issue**
                    # （否则下一轮 normalize 会重复报同一条 → 破坏幂等）
                    events.append(_Ev("text", raw[i : i + 2], start=i, end=i + 2))
                    i += 2
                continue
            events.append(_Ev("text", "\\", start=i, end=i + 1))
            i += 1
            continue

        # 3) $ / $$ 定界符
        if ch == "$":
            if raw.startswith("$$", i):
                end = _find_block_close(raw, i + 2)
                if end != -1:
                    result = _math_event(
                        raw, start=i, open_len=2, body_end=end, end=end + 2, block=True
                    )
                    _emit_math(result, events, issues)
                    i = end + 2
                else:
                    issues.append(make_issue("BLOCK_DELIMITER_RESIDUE", "$$", i))
                    # 转义成字面美元，保证 plain 幂等（不再被识别为定界符）
                    events.append(_Ev("text", "\\$\\$", start=i, end=i + 2))
                    i += 2
                continue
            end = _find_inline_close(raw, i + 1)
            if end != -1:
                result = _math_event(
                    raw, start=i, open_len=1, body_end=end, end=end + 1, block=False
                )
                _emit_math(result, events, issues)
                i = end + 1
            else:
                issues.append(make_issue("UNPAIRED_DOLLAR", "$", i))
                events.append(_Ev("text", "\\$", start=i, end=i + 1))
                i += 1
            continue

        # 4) 行内标签
        if ch == "<":
            match = match_tag(raw, i)
            if match is not None:
                name = match.group(2).lower()
                closing = bool(match.group(1))
                category = classify(name)
                if category == "br":
                    events.append(_Ev("br", start=i, end=match.end()))
                    i = match.end()
                    continue
                if category == "container":
                    if closing:
                        if name in open_stack:
                            open_stack.remove(name)
                            events.append(_Ev("close", tag=name, start=i, end=match.end()))
                        else:
                            # 悬空闭标签：按未知标签处理（转义保留 + issue），不静默吞字
                            issues.append(make_issue("UNKNOWN_TAG", raw[i : match.end()], i))
                            events.append(_Ev("text", escape_html_text(raw[i : match.end()]),
                                              start=i, end=match.end()))
                    else:
                        open_stack.append(name)
                        events.append(_Ev("open", tag=name, start=i, end=match.end()))
                    i = match.end()
                    continue
                issues.append(make_issue("UNKNOWN_TAG", raw[i : match.end()], i))
                events.append(_Ev("text", escape_html_text(raw[i : match.end()]),
                                  start=i, end=match.end()))
                i = match.end()
                continue
            events.append(_Ev("text", "<", start=i, end=i + 1))
            i += 1
            continue

        # 5) 普通字符：逐字保留（含空格、换行、全角字符 —— 正文一律不动）
        events.append(_Ev("text", ch, start=i, end=i + 1))
        i += 1

    if kind == "header":
        events = expand_header_events(coalesce_text(events), raw)
    return events, issues


def coalesce_text(events: List[_Ev]) -> List[_Ev]:
    """把**在原始输入中连续**的 text 事件并成一个。

    为什么需要：扫描是逐字符产出 text 事件的，而 header 特判要在「人名 + 上标符号」
    这一整段上做正则切片；不先合并就只能看到单字符，模式永远匹配不上。
    只合并 ``prev.end == next.start``（原串连续）的相邻 text，避免把被剥掉的控制符、
    被转义的标签前后的片段错误地粘成一段。
    """
    out: List[_Ev] = []
    for event in events:
        if (
            event.kind == "text"
            and out
            and out[-1].kind == "text"
            and out[-1].end == event.start
            and out[-1].start >= 0
        ):
            out[-1].text += event.text
            out[-1].end = event.end
            continue
        out.append(event)
    return out


def _math_event(
    raw: str, *, start: int, open_len: int, body_end: int, end: int, block: bool
) -> Tuple[Optional[_Ev], List[TextIssue]]:
    """构造公式事件 + 它自己的 issue（在 math 段起点上报 offset）。

    ``open_len`` 是**起始定界符的字符数**（``$``=1，``$$``/``\\(``/``\\[``=2）——
    body 必须从定界符之后开始，定界符绝不进节点 text。

    空公式返回 ``event=None``（定界符既不产出节点也不留字面量），issue 照常返回。
    """
    body_raw = raw[start + open_len : body_end]
    body, tag_no, width_changed, compacted, inline_tag_left = prepare_math_body(
        body_raw, block=block
    )
    segment = raw[start:end]
    extra: List[TextIssue] = []
    if width_changed:
        extra.append(make_issue("MIXED_WIDTH", segment, start))
    if compacted:
        # 压缩发生了 → info 级（规格第 4 条允许 LATEX_SUSPECT/MIXED_WIDTH 二选一）
        extra.append(make_issue("LATEX_SUSPECT", segment, start, severity="info"))
    if inline_tag_left:
        # 行内公式里的 \tag 不剥离，只报警（规格第 2 条）
        extra.append(make_issue("LATEX_SUSPECT", segment, start))
    if not body:
        return None, extra
    kind = "math_block" if block else "math_inline"
    return _Ev(kind, body, tag_no=tag_no, start=start, end=end), extra


def _emit_math(
    result: Tuple[Optional[_Ev], List[TextIssue]],
    events: List[_Ev],
    issues: List[TextIssue],
) -> None:
    """把公式事件与它的问题一起收集。"""
    event, extra = result
    issues.extend(extra)
    if event is not None:
        events.append(event)


# ------------------------------------------------------------------ AST


def _build_rich(events: List[_Ev]) -> List[RichNode]:
    root: List[RichNode] = []
    stack: List[Tuple[str, List[RichNode]]] = []

    def emit(node: RichNode) -> None:
        if stack:
            stack[-1][1].append(node)
        else:
            root.append(node)

    for event in events:
        if event.kind == "text":
            if not event.text:
                continue
            target = stack[-1][1] if stack else root
            if target and target[-1].type == "text" and target[-1].children is None:
                target[-1].text = (target[-1].text or "") + event.text
            else:
                emit(RichNode(type="text", text=event.text))
        elif event.kind == "math_inline":
            emit(RichNode(type="math_inline", text=event.text))
        elif event.kind == "math_block":
            emit(RichNode(type="math_block", text=event.text, tag_no=event.tag_no))
        elif event.kind == "br":
            emit(RichNode(type="br"))
        elif event.kind == "open":
            # 注意：pydantic v2 会**复制**传入的 list，所以必须拿 node.children
            # 本身当容器（否则后续 append 全落进被丢弃的临时 list → 子节点凭空消失）
            node = RichNode(type=event.tag, children=[])
            emit(node)
            stack.append((event.tag, node.children))
        elif event.kind == "close":
            for idx in range(len(stack) - 1, -1, -1):
                if stack[idx][0] == event.tag:
                    del stack[idx:]
                    break

    return _prune(root)


def _prune(nodes: List[RichNode]) -> List[RichNode]:
    """去掉空容器（``<sup></sup>``）并合并相邻 text 节点。

    ——保证容器恒「至少一个子节点」，且 AST 里不出现两个挨着的 text。
    """
    out: List[RichNode] = []
    for node in nodes:
        if node.children is not None:
            children = _prune(node.children)
            if not children:
                continue
            node.children = children
        elif node.type == "text" and not node.text:
            continue
        if (
            node.children is None
            and node.type == "text"
            and out
            and out[-1].children is None
            and out[-1].type == "text"
        ):
            out[-1].text = (out[-1].text or "") + (node.text or "")
            continue
        out.append(node)
    return out


def _flatten(nodes: List[RichNode]) -> str:
    """叶子文本按顺序拼接（容器取其 children 叶子；br 贡献一个换行）。"""
    out: List[str] = []
    for node in nodes:
        if node.children is not None:
            out.append(_flatten(node.children))
        elif node.type == "br":
            out.append("\n")
        else:
            out.append(node.text or "")
    return "".join(out)


# ------------------------------------------------------------------ 对外


def normalize(text: str, *, kind: TextKind = "body") -> NormalizedText:
    """把粗产物规范化为 ``NormalizedText{plain, rich, issues}``。纯规则、零外部调用。"""
    source = text if isinstance(text, str) else ""
    events, issues = _tokenize(source, kind)
    rich = _build_rich(events)
    plain = _flatten(rich)
    ordered = sorted(
        issues, key=lambda item: item.offset if item.offset is not None else 1 << 30
    )
    return NormalizedText(plain=plain, rich=rich, issues=ordered)


def scan(text: str) -> List[TextIssue]:
    """对**任意原始字符串**返回它能发现的所有 issue（供 M11 回归门禁复用）。"""
    source = text if isinstance(text, str) else ""
    _events, issues = _tokenize(source, "body")
    return sorted(
        issues, key=lambda item: item.offset if item.offset is not None else 1 << 30
    )


__all__ = ["TextKind", "normalize", "scan"]
