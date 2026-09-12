"""M1 textnorm — 文本规范化契约（REFACTOR_SPEC §5.3）。

**冻结接口**：字段名/可选性一律不得改动 —— 前端 ``lib/contracts.ts`` 按本文件
逐字镜像 TS 类型。任何形状变化都必须先改规格再改这里。

语义约束（由 ``app/modules/textnorm`` 保证，本文件只声明形状）：

- 容器节点（``sup``/``sub``/``i``/``b``）**必须**用 ``children`` 装内容；
- 叶子节点（``text``/``math_inline``/``math_block``/``code``/``br``）**必须**用
  ``text``，其中 ``br`` 的 ``text`` 恒为 ``None``；
- ``math_inline``/``math_block`` 的 ``text`` 是**不含定界符**的纯 LaTeX；
- ``NormalizedText.plain`` 逐字等于 ``rich`` 全部叶子文本按顺序拼接。
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

#: 富文本节点判别联合的全部取值
NodeType = Literal["text", "sup", "sub", "i", "b", "br", "code", "math_inline", "math_block"]
#: 问题清单的全部取值（M11 回归门禁按此枚举做漂移检查）
IssueCode = Literal[
    "UNPAIRED_DOLLAR",
    "BLOCK_DELIMITER_RESIDUE",
    "UNKNOWN_TAG",
    "CONTROL_CHAR",
    "MIXED_WIDTH",
    "LATEX_SUSPECT",
]


class RichNode(BaseModel):
    """富文本 AST 节点（判别联合）。"""

    type: NodeType
    #: 叶子节点（text/math_inline/math_block/code）的内容；math 为**不含定界符**的纯 LaTeX
    text: Optional[str] = None
    #: 容器节点（sup/sub/i/b）的子节点，至少一个 text 子节点
    children: Optional[List["RichNode"]] = None
    #: 保留字段，本期 textnorm 不产出 link 节点
    href: Optional[str] = None
    #: 仅 math_block：``\\tag{N}`` 的编号
    tag_no: Optional[str] = None


class TextIssue(BaseModel):
    """规范化过程中发现的问题。"""

    code: IssueCode
    severity: Literal["info", "warn"] = "warn"
    #: 问题片段，≤80 字符
    excerpt: str
    #: 在**原始输入字符串**中的起始下标（0-based），算不出给 None
    offset: Optional[int] = None


class NormalizedText(BaseModel):
    """规范化产物：干净正文 + 富文本 AST + 问题清单。"""

    #: 干净正文：无 HTML 标签、无控制符、公式为紧凑 LaTeX（无 $ 定界符、无 \tag）
    plain: str
    #: 富文本 AST，按顺序拼回语义等价于 plain
    rich: List[RichNode]
    issues: List[TextIssue] = Field(default_factory=list)


RichNode.model_rebuild()

__all__ = [
    "NodeType",
    "IssueCode",
    "RichNode",
    "TextIssue",
    "NormalizedText",
]
