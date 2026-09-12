"""M1 textnorm —— Text normalization and issue detection (pure rules, no LLM, no DB).

对外契约只有两个函数（其余模块都是内部实现，禁止跨模块直接 import）：:

    normalize(text, *, kind="body") -> NormalizedText
    scan(text) -> list[TextIssue]

分层：

- ``core``       单遍扫描 → 事件流 → AST → plain；对外入口
- ``inline``     ``<sup>/<sub>/<i>/<b>/<br>`` 白名单与未知标签判定
- ``latex``      公式体：``\\tag`` 剥离、MinerU 空格修复、全角归一
- ``heuristics`` ``kind="header"`` 的作者/机构/邮箱行特判
- ``chars``      控制符剥离、HTML 转义、全角映射
- ``issues``     ``TextIssue`` 构造与 excerpt 截断
"""
from __future__ import annotations

from .core import normalize, scan

__all__ = ["normalize", "scan"]
