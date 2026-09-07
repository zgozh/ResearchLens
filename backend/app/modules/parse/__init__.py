"""modules/parse — 解析器模块（Spec §B.1）。

职责：PDF → pages → blocks（段落/标题/图/表/公式），保留阅读顺序。
API: extract_pdf_pages / detect_sections / parse_pdf / default_upload_dir / save_upload
评价：结构抽取准确率。
"""
from app.services.parser import (  # noqa: F401
    default_upload_dir,
    detect_sections,
    extract_pdf_pages,
    parse_pdf,
    save_upload,
)
