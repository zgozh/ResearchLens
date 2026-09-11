"""M03 — 表格归一化（REFACTOR_SPEC §5.3、§6.5、§3.4）。

要求：
- 保留 rowspan/colspan、文本与公式标签；
- **不截断**矩阵、不限制 12×12、不截断单元格；
- 原始 HTML 原封保留为不可信提取材料（清理在前端由 DOMPurify 完成）；
- 清理破坏结构时退回原件，不退回截断矩阵冒充原件。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.contracts.artifacts import ExtractedMedia, TableCell
from app.contracts.common import Warning

_TABLE_RE = re.compile(r"<table\b.*?</table>", re.DOTALL | re.IGNORECASE)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_CELL_RE = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
_ROWSPAN_RE = re.compile(r"rowspan\s*=\s*[\"']?(\d+)", re.IGNORECASE)
_COLSPAN_RE = re.compile(r"colspan\s*=\s*[\"']?(\d+)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

#: 明文上限仅用于防极端内存占用；正常表格不触发
MAX_HTML_CHARS = 2_000_000


def extract_cells(html: str, *, origin_label: Optional[str] = None) -> List[TableCell]:
    """把 HTML 表格解析成 TableCell[]，**保留 rowspan/colspan 与完整文本**。"""
    if not html or len(html) > MAX_HTML_CHARS:
        return []
    match = _TABLE_RE.search(html)
    body = match.group(0) if match else html

    cells: List[TableCell] = []
    row_index = 0
    for row_html in _ROW_RE.findall(body):
        col_index = 0
        found_any = False
        for tag, attrs, inner in _CELL_RE.findall(row_html):
            rowspan = _int_attr(_ROWSPAN_RE.search(attrs), default=1)
            colspan = _int_attr(_COLSPAN_RE.search(attrs), default=1)
            text = html_to_text(inner)
            cells.append(
                TableCell(
                    row=row_index,
                    col=col_index,
                    rowspan=max(1, rowspan),
                    colspan=max(1, colspan),
                    text=text,
                    is_header=(tag.lower() == "th"),
                )
            )
            col_index += max(1, colspan)
            found_any = True
        if found_any:
            row_index += 1
    return cells


def html_to_text(inner: str) -> str:
    """把单元格内部 HTML 转成文本；保留公式/符号可见内容，不做长度截断。"""
    if not inner:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", inner, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|tr)>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    text = _unescape(text)
    # 只折叠连续空白，不截断内容
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _unescape(text: str) -> str:
    import html as _html

    try:
        return _html.unescape(text)
    except Exception:  # noqa: BLE001
        return text


def _int_attr(match, *, default: int) -> int:
    if not match:
        return default
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


def build_extracted_media(
    *,
    table_html: Optional[str] = None,
    latex: Optional[str] = None,
    equation_label: Optional[str] = None,
    origin_label: Optional[str] = None,
) -> ExtractedMedia:
    """构造提取表示；HTML 始终标注为不可信提取材料。"""
    warnings: List[Warning] = []
    cells: List[TableCell] = []
    if table_html:
        cells = extract_cells(table_html, origin_label=origin_label)
        warnings.append(
            Warning(
                code="table_html_untrusted",
                message="提取表格 HTML 未经清理，仅作不可信提取材料传递",
                stage="visual",
            )
        )
        if not cells:
            warnings.append(
                Warning(
                    code="table_structure_unparsed",
                    message="未能解析表格结构，保留原始 HTML 供审计；显示应退回原件",
                    stage="visual",
                )
            )
    return ExtractedMedia(
        table_html=table_html or None,
        table_cells=cells,
        latex=latex or None,
        equation_label=equation_label,
        origin="source_extraction",
        warnings=warnings,
    )


def is_structured_table(extracted: Optional[ExtractedMedia]) -> bool:
    """判断提取表示是否具备可用结构（否则应退回原件）。"""
    if extracted is None:
        return False
    return bool(extracted.table_cells) or bool(extracted.latex)


def matrix_projection(cells: List[TableCell]) -> List[List[str]]:
    """仅供旧接口 content 字段投影；不用于新 UI 原件显示。

    注意：这是**矩阵投影**，跨越 rowspan/colspan 填充占位，不等于原表原件。
    """
    if not cells:
        return []
    rows = max(c.row for c in cells) + 1
    cols = max(c.col for c in cells) + 1
    grid: List[List[str]] = [["" for _ in range(cols)] for _ in range(rows)]
    for cell in cells:
        for dr in range(cell.rowspan):
            for dc in range(cell.colspan):
                r, c = cell.row + dr, cell.col + dc
                if 0 <= r < rows and 0 <= c < cols:
                    grid[r][c] = cell.text if (dr == 0 and dc == 0) else ""
    return grid


__all__ = [
    "extract_cells",
    "html_to_text",
    "build_extracted_media",
    "is_structured_table",
    "matrix_projection",
]
