"""M07 — 原文检索模块（REFACTOR_SPEC §3.2、§5.6、§5.10、§6.9）。

CPU 可用、中文优先的原文检索底座：中文字符 bigram + 拉丁术语/数字/单位混合索引，
RRF 融合（常数 60）与预算内可选重排；SQLite 纯词法即可用，
embedding 不可用只降级不中断。

API:
- ``index(scope, ctx) -> IndexResult``
- ``retrieve(request, ctx) -> RetrievalResult``
"""
from .service import ALGORITHM_VERSION, index, retrieve  # noqa: F401

__all__ = ["index", "retrieve", "ALGORITHM_VERSION"]
