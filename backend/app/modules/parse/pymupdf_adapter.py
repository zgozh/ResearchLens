"""M02 — PyMuPDF 适配器（REFACTOR_SPEC §5.2、§6.4）。

**统一失败降级路径**：MinerU 不可用时由本模块提供原文、页尺寸、块与坐标。

关键纪律：
- 解析**已保存的同一份字节**（``bytes`` 入参），不重新下载；
- ``pdf_page_index`` 0-based 是唯一位置主键；``page_label`` 独立；
- 保留空白页/纯图页、header/footer/page_number 块；
- 缺坐标就是 page-only（anchor.rect=None），**绝不伪造 bbox**；
- 原文唯一 ``origin=source_extraction``。
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List, Optional

from app.contracts.common import Warning
from app.core.logging import get_logger

log = get_logger(__name__)

ADAPTER_NAME = "pymupdf"
ADAPTER_VERSION = "1"

try:  # pragma: no cover - 依赖实际安装
    import pymupdf  # type: ignore

    _HAS_PYMUPDF = True
except Exception:  # noqa: BLE001
    pymupdf = None
    _HAS_PYMUPDF = False


@dataclass
class RawBlock:
    """适配器层原始块；坐标保留原始像素/点单位，不做归一化猜测。"""

    kind: str
    text: str
    bbox: Optional[List[float]] = None
    bbox_units: str = "unknown"
    ordinal: int = 0
    #: 表格**原始 HTML**（MinerU ``table_body``）。此前被 ``_item_text`` 剥掉标签、
    #: 只留纯文本，导致表格无法对齐渲染。保留它供 M03 建 Media 用。
    table_html: Optional[str] = None
    #: 表格**独立 caption**（MinerU ``table_caption``），与 body 分离，避免
    #: caption 与正文粘连、以及"同一张表英文+中文 caption 被当成两张表"。
    table_caption: Optional[str] = None


@dataclass
class RawPage:
    pdf_page_index: int
    width_pt: float
    height_pt: float
    rotation: int = 0
    cropbox_pdf: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    text: str = ""
    extraction_quality: str = "text"
    blocks: List[RawBlock] = field(default_factory=list)
    image_blocks: List[dict] = field(default_factory=list)


@dataclass
class RawDocument:
    pages: List[RawPage] = field(default_factory=list)
    page_count: int = 0
    toc: List[list] = field(default_factory=list)
    warnings: List[Warning] = field(default_factory=list)
    parser_name: str = ADAPTER_NAME
    parser_version: str = ADAPTER_VERSION
    full_text: str = ""


#: PyMuPDF block 类型编号 → 契约 BlockKind
_PYMUPDF_BLOCK_KIND = {0: "paragraph", 1: "image"}

_HEADER_FOOTER_BAND = 0.08  # 上下 8% 视为页眉/页脚候选带


def available() -> bool:
    return _HAS_PYMUPDF


def parse_bytes(data: bytes, *, include_blank: bool = True) -> RawDocument:
    """解析 PDF 字节 → 原始文档结构（所有物理页都保留）。"""
    if not _HAS_PYMUPDF:
        raise RuntimeError("PyMuPDF 未安装")
    doc = pymupdf.open(stream=data, filetype="pdf")
    warnings: List[Warning] = []
    pages: List[RawPage] = []
    texts: List[str] = []
    try:
        toc = [list(item) for item in (doc.get_toc() or [])]
        for index in range(doc.page_count):
            page = doc[index]
            rect = page.rect
            mediabox = page.mediabox
            page_dict = page.get_text("dict") or {}
            blocks: List[RawBlock] = []
            image_blocks: List[dict] = []
            ordinal = 0
            for raw in page_dict.get("blocks", []):
                btype = raw.get("type", 0)
                bbox = _bbox_of(raw)
                if btype == 1:
                    # 图像块：无文本；仍保留其位置，供 M03 裁剪候选
                    image_blocks.append(
                        {
                            "bbox": bbox,
                            "width": raw.get("width"),
                            "height": raw.get("height"),
                            "number": raw.get("number"),
                        }
                    )
                    blocks.append(
                        RawBlock(kind="image", text="", bbox=bbox, bbox_units="point",
                                 ordinal=ordinal)
                    )
                    ordinal += 1
                    continue
                text = _text_of(raw)
                if not text.strip():
                    continue
                kind = _classify(raw, bbox, rect)
                blocks.append(
                    RawBlock(kind=kind, text=text.strip(), bbox=bbox, bbox_units="point",
                             ordinal=ordinal)
                )
                ordinal += 1

            page_text = "\n".join(b.text for b in blocks if b.text).strip()
            quality = _quality(page_text, len(image_blocks))
            cropbox = _cropbox(page, mediabox)
            pages.append(
                RawPage(
                    pdf_page_index=index,
                    width_pt=float(rect.width or 0.0),
                    height_pt=float(rect.height or 0.0),
                    rotation=_normalise_rotation(page.rotation),
                    cropbox_pdf=cropbox,
                    text=page_text,
                    extraction_quality=quality,
                    blocks=blocks,
                    image_blocks=image_blocks,
                )
            )
            texts.append(page_text)
        if not pages:
            warnings.append(Warning(code="empty_document", message="PDF 没有可读页面", stage="parse"))
        return RawDocument(
            pages=pages,
            page_count=doc.page_count,
            toc=toc,
            warnings=warnings,
            full_text="\n\n".join(texts),
        )
    finally:
        doc.close()


def count_pages(data: bytes) -> int:
    if not _HAS_PYMUPDF:
        return 0
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return 0


def render_page_png(data: bytes, pdf_page_index: int, *, dpi: int = 110) -> Optional[bytes]:
    """渲染单页为 PNG（供 M03 页预览/裁剪）；失败返回 None，由调用方降级。"""
    if not _HAS_PYMUPDF:
        return None
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            if pdf_page_index < 0 or pdf_page_index >= doc.page_count:
                return None
            page = doc[pdf_page_index]
            zoom = max(0.5, min(3.0, dpi / 72.0))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return pix.tobytes("png")
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("页渲染失败 index=%s: %s", pdf_page_index, type(exc).__name__)
        return None


def crop_region_png(
    data: bytes,
    pdf_page_index: int,
    rect_normalized: List[float],
    *,
    dpi: int = 150,
) -> Optional[bytes]:
    """按归一化矩形（相对可见页面，左上原点）裁剪并渲染为 PNG。

    坐标语义与 §5.2 统一坐标系一致：已应用旋转、可见 CropBox 的正向页面。
    """
    if not _HAS_PYMUPDF:
        return None
    if not rect_normalized or len(rect_normalized) != 4:
        return None
    x0, y0, x1, y1 = (float(v) for v in rect_normalized)
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return None
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            if pdf_page_index < 0 or pdf_page_index >= doc.page_count:
                return None
            page = doc[pdf_page_index]
            visible = _visible_rect(page)
            clip = pymupdf.Rect(
                visible.x0 + x0 * visible.width,
                visible.y0 + y0 * visible.height,
                visible.x0 + x1 * visible.width,
                visible.y0 + y1 * visible.height,
            )
            zoom = max(0.5, min(4.0, dpi / 72.0))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
            return pix.tobytes("png")
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("区域裁剪失败 index=%s: %s", pdf_page_index, type(exc).__name__)
        return None


# --------------------------------------------------------------- 内部辅助


def _visible_rect(page):
    """已应用旋转的可见 CropBox（正向页面）。"""
    try:
        return page.rect
    except Exception:  # noqa: BLE001
        return page.mediabox


def _cropbox(page, mediabox) -> List[float]:
    try:
        cb = page.cropbox
        return [float(cb.x0), float(cb.y0), float(cb.x1), float(cb.y1)]
    except Exception:  # noqa: BLE001
        try:
            return [float(mediabox.x0), float(mediabox.y0), float(mediabox.x1), float(mediabox.y1)]
        except Exception:  # noqa: BLE001
            return [0.0, 0.0, 0.0, 0.0]


def _normalise_rotation(value) -> int:
    try:
        rot = int(value) % 360
    except (TypeError, ValueError):
        return 0
    return rot if rot in (0, 90, 180, 270) else 0


def _bbox_of(raw: dict) -> Optional[List[float]]:
    bbox = raw.get("bbox")
    if not bbox or len(bbox) < 4:
        return None
    try:
        return [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    except (TypeError, ValueError):
        return None


def _text_of(raw: dict) -> str:
    lines = []
    for line in raw.get("lines", []) or []:
        spans = [s.get("text", "") for s in (line.get("spans") or [])]
        joined = "".join(spans)
        if joined.strip():
            lines.append(joined)
    return "\n".join(lines)


def _classify(raw: dict, bbox: Optional[List[float]], rect) -> str:
    """保守分类：只识别尺寸/字号/位置可作为依据的类别，不臆测语义。"""
    if bbox is not None and rect is not None and rect.height:
        y0, y1 = bbox[1], bbox[3]
        top_band = rect.y0 + rect.height * _HEADER_FOOTER_BAND
        bottom_band = rect.y1 - rect.height * _HEADER_FOOTER_BAND
        if y1 <= top_band:
            return "header"
        if y0 >= bottom_band:
            return "footer"

    # 页号：极短且多为数字
    text = _text_of(raw).strip()
    if text and len(text) <= 12 and any(ch.isdigit() for ch in text):
        stripped = text.strip(" -–—・.")
        if stripped.isdigit() or (stripped.replace("第", "").replace("页", "").strip().isdigit()):
            return "page_number"

    # 标题：单行、字号显著大于块内其他行
    sizes = [
        float(span.get("size", 0) or 0)
        for line in (raw.get("lines") or [])
        for span in (line.get("spans") or [])
    ]
    max_size = max(sizes) if sizes else 0.0
    line_count = len(raw.get("lines") or [])
    if max_size >= 13.0 and line_count <= 2 and len(text) <= 120:
        return "heading"
    return "paragraph"


def _quality(text: str, image_count: int) -> str:
    if text.strip():
        return "text"
    if image_count:
        return "image_only"
    return "empty"


__all__ = [
    "RawBlock",
    "RawPage",
    "RawDocument",
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "available",
    "parse_bytes",
    "count_pages",
    "render_page_png",
    "crop_region_png",
]
