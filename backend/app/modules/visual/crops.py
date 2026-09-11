"""M03 — 原件裁剪与页预览（REFACTOR_SPEC §5.3、§6.5、§3.4）。

- PDF 坐标裁剪优先：从**同一源字节**渲染，记录 mime/hash/尺寸/renderer_version；
- 页预览按 ``source hash + 页 + 渲染参数`` 幂等缓存，独立于语义 revision；
- 限制分辨率/并发/超时，失败退页级或返回 None（调用方降级），不伪造原件。
"""
from __future__ import annotations

import hashlib
import io
import threading
from dataclasses import dataclass
from typing import List, Optional

from app.core.config import settings
from app.core.errors import invalid_input
from app.core.logging import get_logger

from . import tables as tables_mod

log = get_logger(__name__)

RENDERER_VERSION = "pymupdf/render/1"

#: 渲染限制（§6.5：分辨率/并发/超时限制）
MAX_DPI = 300
MIN_DPI = 72
DEFAULT_PREVIEW_DPI = 110
DEFAULT_CROP_DPI = 150
MAX_CROP_PIXELS = 40_000_000
_RENDER_TIMEOUT_S = 20.0

_render_semaphore = threading.Semaphore(2)


@dataclass
class RenderedImage:
    data: bytes
    mime: str
    width_px: Optional[int]
    height_px: Optional[int]
    renderer_version: str = RENDERER_VERSION


def clamp_dpi(dpi: Optional[int], *, default: int) -> int:
    if dpi is None:
        return default
    try:
        value = int(dpi)
    except (TypeError, ValueError):
        raise invalid_input("dpi 必须是整数", field="dpi")
    return max(MIN_DPI, min(MAX_DPI, value))


def _png_size(data: bytes) -> tuple:
    """从 PNG 头解析宽高（避免再次解码）。失败返回 (None, None)。"""
    try:
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None, None
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height
    except Exception:  # noqa: BLE001
        return None, None


def render_page(
    source_bytes: bytes,
    pdf_page_index: int,
    *,
    dpi: Optional[int] = None,
) -> Optional[RenderedImage]:
    """渲染整页为 PNG（供 preview 资产）。分辨率受限，失败返回 None。"""
    from app.modules.parse import pymupdf_adapter

    if not pymupdf_adapter.available():
        return None
    zoom_dpi = clamp_dpi(dpi, default=DEFAULT_PREVIEW_DPI)
    acquired = _render_semaphore.acquire(timeout=_RENDER_TIMEOUT_S)
    if not acquired:
        log.warning("渲染并发已满，跳过页预览渲染")
        return None
    try:
        data = pymupdf_adapter.render_page_png(source_bytes, pdf_page_index, dpi=zoom_dpi)
        if not data:
            return None
        width, height = _png_size(data)
        if width and height and width * height > MAX_CROP_PIXELS:
            log.warning("渲染结果像素过多，拒绝")
            return None
        return RenderedImage(data=data, mime="image/png", width_px=width, height_px=height)
    finally:
        _render_semaphore.release()


def render_region(
    source_bytes: bytes,
    pdf_page_index: int,
    rect_normalized: List[float],
    *,
    dpi: Optional[int] = None,
) -> Optional[RenderedImage]:
    """按归一化矩形裁剪渲染；无效坐标抛 INVALID_INPUT，渲染失败返回 None。"""
    from app.modules.parse import pymupdf_adapter

    rect = _validate_rect(rect_normalized)
    if not pymupdf_adapter.available():
        return None
    zoom_dpi = clamp_dpi(dpi, default=DEFAULT_CROP_DPI)
    acquired = _render_semaphore.acquire(timeout=_RENDER_TIMEOUT_S)
    if not acquired:
        return None
    try:
        data = pymupdf_adapter.crop_region_png(
            source_bytes, pdf_page_index, rect, dpi=zoom_dpi
        )
        if not data:
            return None
        width, height = _png_size(data)
        return RenderedImage(data=data, mime="image/png", width_px=width, height_px=height)
    finally:
        _render_semaphore.release()


def _validate_rect(rect: List[float]) -> List[float]:
    if not rect or len(rect) != 4:
        raise invalid_input("rect 必须为 [x0,y0,x1,y1]", field="rect")
    values = [float(v) for v in rect]
    for value in values:
        if value != value or value in (float("inf"), float("-inf")):
            raise invalid_input("rect 必须为有限数", field="rect")
    x0, y0, x1, y1 = values
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        raise invalid_input("rect 必须归一化到 0..1 且 x0<x1、y0<y1", field="rect")
    return values


def preview_cache_key(source_sha256: str, pdf_page_index: int, dpi: int) -> str:
    """页预览幂等键：source hash + 页 + 渲染参数 + renderer 版本。"""
    raw = f"{source_sha256}|{pdf_page_index}|{dpi}|{RENDERER_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def crop_cache_key(source_sha256: str, pdf_page_index: int, rect: List[float], dpi: int) -> str:
    rect_str = ",".join(f"{v:.6f}" for v in rect)
    raw = f"{source_sha256}|{pdf_page_index}|{rect_str}|{dpi}|{RENDERER_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def assets_for_media(media) -> List[str]:
    """媒体可用原件资产：优先非缩略版本（§5.3 resize 资产仅供预览）。"""
    return list(media.original_asset_ids or [])


__all__ = [
    "RenderedImage",
    "RENDERER_VERSION",
    "DEFAULT_PREVIEW_DPI",
    "DEFAULT_CROP_DPI",
    "MAX_DPI",
    "clamp_dpi",
    "render_page",
    "render_region",
    "preview_cache_key",
    "crop_cache_key",
    "assets_for_media",
]
