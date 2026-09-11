"""M03 — 原件媒体与提取表示（REFACTOR_SPEC §6.5）。

公共 API 见 ``service``：

- ``build_media`` / ``get_media`` / ``list_media``
- ``get_policy``（来源显示策略）
- ``ensure_page_preview``（按 source hash/页/渲染参数幂等）

说明：旧 ``app.seed.svgkit`` 的程序化渲染仍可单独导入（``from app.seed import
svgkit``）；本包不再 re-export 它，以免与"原件/提取/示意"的来源语义混淆。
"""
from .service import (  # noqa: F401
    build_media,
    ensure_page_preview,
    get_media,
    get_policy,
    list_media,
)
from .policy import label_for_mode  # noqa: F401

__all__ = [
    "build_media",
    "get_media",
    "list_media",
    "get_policy",
    "ensure_page_preview",
    "label_for_mode",
]
