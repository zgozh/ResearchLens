"""M02 — MinerU/PyMuPDF 解析与页码坐标（REFACTOR_SPEC §6.4）。

公共 API 见 ``service``（parse/persist/get_pages/get_blocks/get_page/
resolve_page_label/apply_page_overrides）。

说明：旧 ``app.services.parser`` 的兼容函数（extract_pdf_pages/detect_sections/
parse_pdf/default_upload_dir/save_upload）**仍由旧 shim 提供**，不在本包重复导出，
以免与本模块的 canonical 公共入口混淆。

例外：``save_upload`` / ``default_upload_dir`` 被 ``api/routes.py`` 直接通过
``app.modules.parse`` 使用（历史调用面），因此保留同名薄转发。
"""
from .service import (  # noqa: F401
    apply_page_overrides,
    get_blocks,
    get_page,
    get_pages,
    load_media_candidates,
    parse,
    persist,
    resolve_page_label,
)

# --- 兼容转发：历史调用方使用 app.modules.parse.save_upload / default_upload_dir ---
from .compat import default_upload_dir, save_upload  # noqa: F401

__all__ = [
    "parse",
    "persist",
    "get_pages",
    "load_media_candidates",
    "get_blocks",
    "get_page",
    "resolve_page_label",
    "apply_page_overrides",
    "save_upload",
    "default_upload_dir",
]
