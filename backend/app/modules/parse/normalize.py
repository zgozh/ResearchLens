"""M02 — 归一化（REFACTOR_SPEC §5.2、§6.4）。

把适配器原始结构（``RawDocument``）转成契约 DTO（``Page`` / ``Block`` / ``Anchor``
/ ``PageLabelMapping`` / ``ParsedMediaCandidate``）。

纪律：
- ``pdf_page_index`` 0-based；``pdf_page_no`` 只是兼容投影（index+1）；
- 所有物理页入库，包括空白/纯图页；
- 原文唯一 ``origin=source_extraction``；
- 缺坐标 → page-only Anchor（rect=None、quads=[]），**绝不伪造 bbox**；
- 页码映射不猜固定页差：只承认可核实的候选（PDF 元数据 / 页内可见页码 / 人工）。
"""
from __future__ import annotations

import hashlib
import re
from typing import List, Optional, Sequence, Tuple

from app.contracts.artifacts import ExtractedMedia, TableCell
from app.contracts.common import Scope, Warning
from app.contracts.documents import (
    Anchor,
    AnchorSegment,
    Block,
    Page,
    PageLabelMapping,
    ParsedMediaCandidate,
    RawRef,
)

from .pymupdf_adapter import RawBlock, RawDocument, RawPage

NORMALIZER_VERSION = "m02.normalize/1"

_PAGE_NUM_RE = re.compile(r"^\s*(?:第\s*)?([0-9]{1,4}|[ivxlcIVXLC]{1,7})\s*(?:页)?\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[\.\s]")
_LABELED_HEADING_RE = re.compile(
    r"^\s*(?:abstract|introduction|related\s+work|background|method(?:ology)?|approach|"
    r"experiments?|evaluation|results?|discussion|conclusions?|limitations?|references|"
    r"摘要|引言|绪论|相关工作|背景|方法|实验|评估|结果|讨论|结论|局限|参考文献)\b",
    re.IGNORECASE,
)
_EQUATION_LABEL_RE = re.compile(r"\((\d+(?:\.\d+)*)\)\s*$")
_FIGURE_LABEL_RE = re.compile(r"(?:figure|fig\.?|图)\s*([0-9]+[a-zA-Z]?(?:\([a-zA-Z0-9]\))?)", re.I)
_TABLE_LABEL_RE = re.compile(r"(?:table|tbl\.?|表)\s*([0-9]+[a-zA-Z]?(?:\([a-zA-Z0-9]\))?)", re.I)


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def detect_language(text: str) -> str:
    """粗粒度语言标注：中文优先判定，其余标 en；不确定留空。"""
    if not text:
        return ""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk >= max(1, len(text) // 10):
        return "zh"
    if any(ch.isalpha() for ch in text):
        return "en"
    return ""


def known_headings(raw: RawDocument) -> List[Tuple[int, str, str]]:
    """基于 PDF 目录（TOC）返回 (pdf_page_index, title, level)；无可核实信息则空。"""
    out: List[Tuple[int, str, str]] = []
    for entry in raw.toc or []:
        if len(entry) < 3:
            continue
        try:
            level = int(entry[0])
            title = str(entry[1]).strip()
            page_no = int(entry[2])
        except (TypeError, ValueError):
            continue
        if not title:
            continue
        index = max(0, page_no - 1)
        out.append((index, title, str(level)))
    return out


def build_pages(scope: Scope, raw: RawDocument, *, page_ids: List[str],
                preview_asset_ids: Optional[List[Optional[str]]] = None) -> List[Page]:
    """构造全部物理页。``page_ids`` 由调用方预生成，保证 persist 幂等可复现。"""
    previews = preview_asset_ids or [None] * len(raw.pages)
    pages: List[Page] = []
    labels = label_candidates(raw)
    for offset, rp in enumerate(raw.pages):
        index = rp.pdf_page_index
        width = rp.width_pt if rp.width_pt > 0 else 1.0
        height = rp.height_pt if rp.height_pt > 0 else 1.0
        label, status = labels.get(index, (None, "unknown"))
        pages.append(
            Page(
                scope=scope,
                id=page_ids[offset],
                pdf_page_index=index,
                pdf_page_no=index + 1,
                page_label=label,
                label_status=status,
                width_pt=float(width),
                height_pt=float(height),
                rotation=rp.rotation if rp.rotation in (0, 90, 180, 270) else 0,
                cropbox_pdf=list(rp.cropbox_pdf or [0.0, 0.0, 0.0, 0.0]),
                text=rp.text or "",
                text_origin="source_extraction",
                preview_asset_id=previews[offset] if offset < len(previews) else None,
                extraction_quality=rp.extraction_quality if rp.extraction_quality in
                ("text", "ocr", "image_only", "empty") else "text",
            )
        )
    return pages


def build_blocks(
    scope: Scope,
    raw: RawDocument,
    *,
    pages: List[Page],
    block_ids: List[List[str]],
    section_paths: Optional[dict] = None,
) -> List[Block]:
    """构造全部块（含 header/footer/page_number），保留 ordinal 与推导的 kind。"""
    blocks: List[Block] = []
    paths = section_paths or {}
    for page_offset, rp in enumerate(raw.pages):
        page = pages[page_offset]
        ids = block_ids[page_offset] if page_offset < len(block_ids) else []
        for offset, rb in enumerate(rp.blocks):
            if offset >= len(ids):
                break
            block_id = ids[offset]
            kind = _refine_kind(rb, rp)
            blocks.append(
                Block(
                    scope=scope,
                    id=block_id,
                    page_id=page.id,
                    ordinal=rb.ordinal if rb.ordinal >= 0 else offset,
                    kind=kind,
                    text=rb.text or "",
                    origin="source_extraction",
                    section_path=list(paths.get(block_id, [])),
                    raw_ref=_raw_ref(rb) if rb.bbox else None,
                    language=detect_language(rb.text or ""),
                    content_hash=content_hash(rb.text or ""),
                )
            )
    return blocks


def _raw_ref(rb: RawBlock) -> RawRef:
    return RawRef(
        asset_id="",  # 由 service 层在拿到 raw asset 后补；此处不伪造资产
        record_path=f"blocks[{rb.ordinal}]",
        native_id=None,
        bbox_values=list(rb.bbox) if rb.bbox else None,
        bbox_units=rb.bbox_units if rb.bbox_units in ("pixel", "point", "normalized", "unknown")
        else "unknown",
        coordinate_frame=None,
    )


def _refine_kind(rb: RawBlock, rp: RawPage) -> str:
    """在适配器分类基础上做保守细化（只依据文本形态，不吃位置猜测）。"""
    text = (rb.text or "").strip()
    if rb.kind in ("header", "footer", "page_number", "table", "equation", "image"):
        return rb.kind
    if not text:
        return "other" if rb.kind == "other" else "paragraph"
    if rb.kind == "heading":
        return "heading"
    if _LABELED_HEADING_RE.match(text) or (_NUMBERED_HEADING_RE.match(text) and len(text) <= 90):
        return "heading"
    if _FIGURE_LABEL_RE.search(text) and text.lower().startswith(("figure", "fig", "图")):
        return "caption"
    if _TABLE_LABEL_RE.search(text) and text.lower().startswith(("table", "tbl", "表")):
        return "caption"
    if _EQUATION_LABEL_RE.search(text) and len(text) <= 160:
        return "equation"
    if previous_is_equation_marker(text):
        return "equation"
    return "paragraph"


def previous_is_equation_marker(text: str) -> bool:
    return bool(_EQUATION_LABEL_RE.search(text)) and len(text) <= 40


# --------------------------------------------------------------- 页码映射


def label_candidates(raw: RawDocument) -> dict:
    """返回 ``{pdf_page_index: (label, status)}``。

    仅承认两类可核实来源：
    - PDF 目录/TOC 声明（candidate）；
    - 页内可见页号块（candidate）。
    **不做全局固定页差推断。** 同一 label 出现在多页时状态为 ambiguous。
    """
    collected: dict = {}  # label -> list[index]
    sources: dict = {}    # index -> (label, method)

    for index, title, _level in known_headings(raw):
        if index < len(raw.pages):
            sources.setdefault(index, (None, "pdf_metadata"))

    for rp in raw.pages:
        for block in rp.blocks:
            if block.kind != "page_number":
                continue
            found = extract_visible_page_number(block.text)
            if found:
                sources[rp.pdf_page_index] = (found, "printed_ocr")
                collected.setdefault(found, []).append(rp.pdf_page_index)
                break

    out: dict = {}
    for index, (label, _method) in sources.items():
        if not label:
            out[index] = (None, "unknown")
            continue
        occurrences = collected.get(label, [index])
        status = "ambiguous" if len(occurrences) > 1 else "candidate"
        out[index] = (label, status)
    return out


def extract_visible_page_number(text: str) -> Optional[str]:
    """从页内文本提取可见页号（阿拉伯/罗马数字）；不返回猜测值。"""
    if not text:
        return None
    stripped = text.strip().strip("·•-–—[]()|")
    match = _PAGE_NUM_RE.match(stripped)
    if not match:
        # 允许 "Page 12" / "页码 12"
        match2 = re.search(r"(?:page|p\.|页码)\s*([0-9]{1,4})", stripped, re.IGNORECASE)
        if match2:
            return match2.group(1)
        return None
    value = match.group(1)
    if value.lower() in ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"):
        return value.lower()
    return value


def build_label_mappings(scope: Scope, raw: RawDocument, *, mapping_ids: List[List[str]],
                         pages: List[Page]) -> List[PageLabelMapping]:
    """无块关联的简易版本；优先使用 ``build_label_mappings_with_blocks``。"""
    labels = label_candidates(raw)
    out: List[PageLabelMapping] = []
    for index, (label, status) in labels.items():
        if not label:
            continue
        ids = mapping_ids[index] if index < len(mapping_ids) else []
        out.append(
            PageLabelMapping(
                scope=scope,
                id=ids[0] if ids else _stable_id(scope, "label", f"{index}:{label}"),
                page_label=str(label),
                pdf_page_index=index,
                method="printed_ocr",
                status="ambiguous" if status == "ambiguous" else "candidate",
                source_block_ids=[],
                confidence=None,
            )
        )
    return out


def build_label_mappings_with_blocks(
    scope: Scope,
    raw: RawDocument,
    *,
    pages: List[Page],
    blocks: List[Block],
    id_factory,
) -> List[PageLabelMapping]:
    """完整版：把页号块 ID 关联到映射（source_block_ids）。"""
    labels = label_candidates(raw)
    blocks_by_page: dict = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page_id, []).append(block)

    out: List[PageLabelMapping] = []
    for index in sorted(labels):
        label, status = labels[index]
        if not label:
            continue
        page = pages[index] if index < len(pages) else None
        source_blocks = []
        if page is not None:
            for block in blocks_by_page.get(page.id, []):
                if block.kind == "page_number" and extract_visible_page_number(block.text) == label:
                    source_blocks.append(block.id)
        out.append(
            PageLabelMapping(
                scope=scope,
                id=id_factory("label", f"{index}:{label}"),
                page_label=str(label),
                pdf_page_index=index,
                method="printed_ocr",
                status="ambiguous" if status == "ambiguous" else "candidate",
                source_block_ids=source_blocks,
                confidence=None,
            )
        )
    return out


# --------------------------------------------------------------- 锚点


def build_page_anchor(
    scope: Scope,
    *,
    anchor_id: str,
    source_document_id: str,
    pages: List[Page],
    page_id: str,
    block_ids: List[str],
    rect: Optional[List[float]] = None,
    quote_spans: Optional[list] = None,
) -> Anchor:
    """构造 Anchor；无 rect 时是 page-only（不伪造矩形）。"""
    page = next((p for p in pages if p.id == page_id), None)
    index = page.pdf_page_index if page is not None else 0
    label = page.page_label if page is not None else None
    segment = AnchorSegment(
        page_id=page_id,
        pdf_page_index=index,
        page_label=label,
        rect=list(rect) if rect else None,
        quads=[],
        block_ids=list(block_ids),
        quote_spans=list(quote_spans or []),
    )
    return Anchor(
        scope=scope,
        id=anchor_id,
        source_document_id=source_document_id,
        precision="region" if rect else "page",
        segments=[segment],
        transform=None,
        raw_ref=None,
    )


# --------------------------------------------------------------- 媒体候选


#: caption 里的图表编号标记（用于切分"相邻对象粘连"的 caption）
_CAPTION_MARKER_RE = re.compile(
    r"(图|表|式|figure|fig\.?|table|tbl\.?|equation|eq\.?)\s*"
    r"([0-9]+[a-zA-Z]?(?:\([a-zA-Z0-9]\))?)",
    re.I,
)

#: 装饰性插图（二维码/作者头像）的归一化面积上限。
#: 实测：装饰性插图 0.60%–0.68%，带 caption 的子图面板 0.82%–0.85%，真图 4.8%+。
#: 取 2% 作分界，且**必须与"caption 为空"取交集**——只按面积会误删图 1 的 6 个面板。
MIN_FIGURE_AREA_FRACTION = 0.02


def _marker_kind(prefix: str) -> str:
    p = (prefix or "").lower().rstrip(".")
    if p == "图" or p.startswith("fig"):
        return "figure"
    if p == "表" or p.startswith("tab"):
        return "table"
    if p == "式" or p.startswith("eq"):
        return "equation"
    return ""


def _base_label(label: str) -> str:
    """去掉子图后缀：``2(a)`` → ``2``（子图与父图属同一对象，不得互相切断）。"""
    return re.sub(r"\(.*$", "", (label or "")).strip().lower()


def split_caption_own_object(text: str) -> str:
    """只保留 caption 中**属于本对象**的那一段。

    MinerU 的 ``image_caption``/``table_caption`` 是**数组**，``mineru_adapter._as_text()``
    用 ``" ".join`` 整串拼接，于是相邻对象的 caption 被粘成一条（实测
    ``图 9 …箱线图 图 10 …箱线图`` 把两幅图连在一起）。

    切分规则：在出现**不同 (kind, 编号)** 标记处截断；**同编号**的中英双语
    （``Fig.1 … 图 1 …``）与子图/父图（``图 8(a)`` 与 ``图 8``）一律保留。
    """
    body = (text or "").strip()
    markers = [
        (m.start(), _marker_kind(m.group(1)), _base_label(m.group(2)))
        for m in _CAPTION_MARKER_RE.finditer(body)
    ]
    if len(markers) < 2:
        return body
    _, first_kind, first_label = markers[0]
    for start, kind, label in markers[1:]:
        if (kind, label) != (first_kind, first_label):
            return body[:start].strip()
    return body


def _relative_area(rb: RawBlock, page) -> Optional[float]:
    """块 bbox 的归一化面积占比；单位/尺寸不足则返回 ``None``（不猜）。"""
    bbox = getattr(rb, "bbox", None)
    if not bbox or len(bbox) < 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox[:4])
    except (TypeError, ValueError):
        return None
    width, height = abs(x1 - x0), abs(y1 - y0)
    units = (getattr(rb, "bbox_units", "") or "").lower()
    if units == "normalized":
        # MinerU 的 bbox 是 0–1000 归一化网格
        return (width * height) / (1000.0 * 1000.0)
    if units in ("pixel", "point"):
        page_w = float(getattr(page, "width_pt", 0) or 0)
        page_h = float(getattr(page, "height_pt", 0) or 0)
        if page_w > 1.0 and page_h > 1.0:
            return (width * height) / (page_w * page_h)
    return None


def _decorative_figure_reason(rb: RawBlock, page, caption_text: str) -> Optional[str]:
    """装饰性插图判据：**caption 为空** 且 归一化面积过小。返回原因或 ``None``。

    只按"caption 为空"会误删丢了 caption 的真图（实测面积 4.8%）；
    只按"面积小"会误删带 caption 的子图面板（0.82%–0.85%）。故取交集。
    """
    if getattr(rb, "kind", "") != "image":
        return None
    if (caption_text or "").strip():
        return None
    area = _relative_area(rb, page)
    if area is None or area >= MIN_FIGURE_AREA_FRACTION:
        return None
    return (
        f"无 caption 且面积占比 {area:.2%} < {MIN_FIGURE_AREA_FRACTION:.0%}，"
        f"判定为装饰性插图（二维码/作者头像）"
    )


#: CJK 连续块：以汉字起头，允许汉字/数字/空白/常见标点跟在后面，
#: 使整段中文 caption 成为**一块**（避免从"原图像"这种 3 字处误切）。
_CJK_BLOCK_RE = re.compile(r"[\u4e00-\u9fff][\u4e00-\u9fff0-9\s，。、；：（）()%\-]{5,}")
#: 拉丁连续块：≥20 字符，排除只有图号/缩写（"Fig.1"、"MAE"）的短串。
_LATIN_BLOCK_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-'\s,;:.()%]{19,}")

#: 子图面板标记：(a) / (b) / (1) …
_PANEL_MARK_RE = re.compile(r"^\s*\(([a-z0-9]{1,2})\)", re.I)


def _dominant_language(pages: Sequence) -> str:
    """文档主导语言：只看**首页**（题名/摘要）。

    不能用全文统计——真实中文论文的参考文献与公式会让拉丁字母数**反超**汉字
    （实测 paper 3：CJK 17714 vs Latin 19491），据此判断会把中文论文判成英文。
    """
    for page in pages or []:
        text = getattr(page, "text", "") or ""
        if not text.strip():
            continue
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
        return "zh" if cjk >= latin else "en"
    return "zh"


def split_bilingual_caption(text: str, *, prefer: str = "zh") -> tuple:
    """把「同一对象的中英双语 caption」拆成 ``(主语言段, 另一语言段)``。

    非双语（只有一种语言、或另一语言只是 ``Fig.1``/``MAE`` 这类短串）时
    返回 ``(原文本, "")``——**绝不误切**。``prefer`` 是文档主导语言，
    决定哪一段进主 caption（另一段无损进 ``caption_alt``）。
    """
    body = (text or "").strip()
    if not body:
        return "", ""
    zh = _CJK_BLOCK_RE.search(body)
    en = _LATIN_BLOCK_RE.search(body)
    if not zh or not en:
        return body, ""

    if en.start() < zh.start():
        # 英文在前、中文在后
        head, tail = body[: zh.start()].strip(), body[zh.start():].strip()
        seg_en, seg_zh = head, tail
    elif zh.start() < en.start():
        # 中文在前、英文在后
        head, tail = body[: en.start()].strip(), body[en.start():].strip()
        seg_zh, seg_en = head, tail
    else:
        return body, ""

    if not seg_zh or not seg_en:
        return body, ""
    if prefer == "en":
        return seg_en, seg_zh
    return seg_zh, seg_en


def _assign_subfigure_parents(candidates, geometry) -> int:
    """给「只有面板标记、没有父图号」的子图补上父图编号（**不合并行**）。

    REFACTOR_SPEC §480 要求子图保持独立 Media，故这里只补 ``original_label``，
    让面板在图谱/讲解里能被识别为同一张图的一部分，而不是无主孤儿。

    判据：同页 + 纵向重叠超过较矮者 50%（"同一行"）+ 水平相邻；
    **父图必须自带完整 ``图 N`` 编号**，因此像 paper 3 第 14 页那种
    "两个不同图并排"（都带完整编号、都不是面板）不会被误并。
    返回补上编号的面板数量。
    """
    parents = []
    for idx, cand in enumerate(candidates):
        if cand.kind != "figure" or not cand.original_label:
            continue
        geo = geometry[idx] if idx < len(geometry) else None
        if geo is not None:
            parents.append((idx, cand.original_label, geo))
    if not parents:
        return 0

    fixed = 0
    for idx, cand in enumerate(candidates):
        if cand.kind != "figure" or cand.original_label:
            continue
        if not _PANEL_MARK_RE.match(cand.caption or ""):
            continue
        geo = geometry[idx] if idx < len(geometry) else None
        if geo is None:
            continue
        label = _nearest_parent_label(geo, parents, skip=idx)
        if label:
            cand.original_label = label
            fixed += 1
    return fixed


def _nearest_parent_label(geo, parents, *, skip: int):
    """在同一行内找最近的自带编号的父图；找不到返回 ``None``。"""
    page, x0, y0, x1, y1 = geo
    best = None
    for idx, label, other in parents:
        if idx == skip:
            continue
        opage, ox0, oy0, ox1, oy1 = other
        if opage != page:
            continue
        height, oheight = (y1 - y0), (oy1 - oy0)
        if height <= 0 or oheight <= 0:
            continue
        overlap = min(y1, oy1) - max(y0, oy0)
        if overlap <= 0.5 * min(height, oheight):
            continue
        gap = max(x0 - ox1, ox0 - x1, 0.0)
        if gap > 1.5 * max(x1 - x0, ox1 - ox0):
            continue
        distance = abs(((x0 + x1) / 2) - ((ox0 + ox1) / 2))
        if best is None or distance < best[0]:
            best = (distance, label)
    return best[1] if best else None


def build_media_candidates(
    scope: Scope,
    raw: RawDocument,
    *,
    pages: List[Page],
    blocks: List[Block],
    page_index_by_id: dict,
    raw_asset_id: str = "",
) -> List[ParsedMediaCandidate]:
    """从块构造媒体候选。保留原始编号；无坐标不做区域断言；不凑数量。"""
    candidates: List[ParsedMediaCandidate] = []
    geometry: List[Optional[tuple]] = []
    doc_lang = _dominant_language(pages)
    for page_offset, rp in enumerate(raw.pages):
        page = pages[page_offset] if page_offset < len(pages) else None
        if page is None:
            continue
        for rb in rp.blocks:
            if rb.kind not in ("table", "equation", "image"):
                continue
            kind = {"table": "table", "equation": "equation", "image": "figure"}[rb.kind]
            # 表格：caption 与 body 分离（此前把 ``rb.text`` 同时当 caption 和
            # table_html，caption 与正文粘连，且原始 HTML 被剥成纯文本）。
            caption_text = (getattr(rb, "table_caption", None) or rb.text or "").strip()
            # 相邻对象的 caption 可能被适配器粘成一条（见 split_caption_own_object）
            caption_alt = ""
            if kind in ("figure", "table"):
                caption_text = split_caption_own_object(caption_text)
                # 同一对象的中英双语：主语言进 caption，另一种无损留 caption_alt
                caption_text, caption_alt = split_bilingual_caption(
                    caption_text, prefer=doc_lang
                )
            label = _extract_label(kind, caption_text)
            exclusion_reason = _decorative_figure_reason(rb, page, caption_text)
            extracted = None
            if kind == "table":
                extracted = ExtractedMedia(
                    table_html=getattr(rb, "table_html", None) or None,
                    table_cells=[],
                    origin="source_extraction",
                    warnings=[
                        Warning(
                            code="table_html_untrusted",
                            message="提取表格 HTML 未经清理，仅作不可信提取材料",
                            stage="parse",
                        )
                    ],
                )
            elif kind == "equation":
                extracted = ExtractedMedia(
                    latex=None,
                    equation_label=label,
                    origin="source_extraction",
                )
            bbox = getattr(rb, "bbox", None)
            geometry.append(
                (page_offset, float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                if bbox and len(bbox) >= 4 else None
            )
            candidates.append(
                ParsedMediaCandidate(
                    kind=kind,
                    original_label=label,
                    caption=caption_text,
                    caption_alt=caption_alt,
                    anchor_ids=[],
                    raw_ref=_raw_ref(rb) if rb.bbox else None,
                    extracted=extracted,
                    embedded_asset_id=raw_asset_id or None,
                    excluded=bool(exclusion_reason),
                    exclusion_reason=exclusion_reason,
                )
            )
    # 子图面板补父图编号（只改 original_label，不合并任何行）
    _assign_subfigure_parents(candidates, geometry)
    return candidates


def _extract_label(kind: str, text: str) -> Optional[str]:
    if kind == "figure":
        m = _FIGURE_LABEL_RE.search(text or "")
        return m.group(1) if m else None
    if kind == "table":
        m = _TABLE_LABEL_RE.search(text or "")
        return m.group(1) if m else None
    if kind == "equation":
        m = _EQUATION_LABEL_RE.search(text or "")
        return m.group(1) if m else None
    return None


def section_paths_from_headings(blocks: List[Block]) -> dict:
    """按块顺序推导 section_path（纯结构，不生成标题）。"""
    out: dict = {}
    current: List[str] = []
    for block in blocks:
        if block.kind == "heading" and (block.text or "").strip():
            current = [block.text.strip()[:120]]
        out[block.id] = list(current)
    return out


def _stable_id(scope: Scope, kind: str, key: str) -> str:
    digest = hashlib.sha256(f"{scope.paper_id}|{scope.revision_id}|{kind}|{key}".encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


__all__ = [
    "NORMALIZER_VERSION",
    "content_hash",
    "detect_language",
    "known_headings",
    "build_pages",
    "build_blocks",
    "label_candidates",
    "extract_visible_page_number",
    "build_label_mappings",
    "build_label_mappings_with_blocks",
    "build_page_anchor",
    "build_media_candidates",
    "section_paths_from_headings",
]
