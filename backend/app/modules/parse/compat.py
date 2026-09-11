"""M02 兼容层：历史上传目录/文件落盘函数。

``api/routes.py`` 通过 ``app.modules.parse.save_upload`` 使用（历史调用面）。
这里**只做签名转发**到 ``app.services.parser``（其本身是薄壳），避免复制逻辑。

新代码请改用 M01：
``app.modules.papers.store_source``（内容寻址、流式限体积、PDF 魔数校验）。
"""
from __future__ import annotations

from pathlib import Path

from app.services import parser as _legacy_parser


def default_upload_dir() -> Path:
    """# legacy: not yet migrated — 历史上传目录（非内容寻址，仅供旧路由兼容）。"""
    return _legacy_parser.default_upload_dir()


def save_upload(dir_path: Path, filename: str, data: bytes) -> Path:
    """# legacy: not yet migrated — 历史同名写盘（会覆盖同名文件）。

    ⚠️ 新代码不要使用：改用 ``app.modules.papers.store_source``（内容寻址 + 原子 rename）。
    """
    return _legacy_parser.save_upload(dir_path, filename, data)


__all__ = ["default_upload_dir", "save_upload"]
