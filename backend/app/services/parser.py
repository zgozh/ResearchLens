"""services/parser — 兼容薄壳（REFACTOR_SPEC §6.4：旧签名代理）。

本模块**保留原有全部公共函数名与签名**，内部可迁移的部分转发到
``app.modules.parse``；尚未迁移的保留原实现并标注 ``# legacy: not yet migrated``。

新代码请使用 ``app.modules.parse``（canonical：parse/persist/get_pages/...）
与 ``app.modules.papers``（源文件字节与资产存储）。
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Dict, List

try:
    import pypdf  # type: ignore
except Exception:  # pragma: no cover
    pypdf = None

#: 旧启发式章节关键词表（保留原值，行为不变）
_SECTION_HINTS = [
    ("abstract", "abstract", "abstract"),
    ("introduction", "intro", "introduction"),
    ("related work", "intro", "related work"),
    ("background", "intro", "background"),
    ("method", "method", "method"),
    ("methodology", "method", "methodology"),
    ("approach", "method", "approach"),
    ("experiment", "experiment", "experiment"),
    ("experiments", "experiment", "experiments"),
    ("evaluation", "experiment", "evaluation"),
    ("results", "result", "results"),
    ("result", "result", "result"),
    ("discussion", "discussion", "discussion"),
    ("conclusion", "conclusion", "conclusion"),
    ("limitation", "discussion", "limitation"),
    ("references", "references", "references"),
]


def extract_pdf_pages(data: bytes) -> List[dict]:
    """# legacy: not yet migrated — 旧 pypdf 逐页取文（无坐标/无页码语义）。

    新实现见 ``app.modules.parse.parse``（MinerU 优先、PyMuPDF 降级，保留块与坐标）。
    """
    if pypdf is None:
        return []
    reader = pypdf.PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        txt = re.sub(r"[ \t]+", " ", txt)
        pages.append({"page_no": i, "text": txt.strip(), "region_map": {}})
    return pages


def detect_sections(pages: List[dict]) -> List[dict]:
    """# legacy: not yet migrated — 旧标题启发式（可能误判，不产生 verified 结构）。

    新结构抽取归 M06；本函数仅保留旧返回形状供旧管线使用。
    """
    kind_by_heading: Dict[str, str] = {}
    for raw, kind, _ in _SECTION_HINTS:
        kind_by_heading[raw] = kind

    sections: List[dict] = []
    for pg in pages:
        lines = [l.strip() for l in pg["text"].split("\n") if l.strip()]
        for line in lines:
            low = line.lower()
            if len(line) <= 46 and any(h in low for h in kind_by_heading):
                matched = next(h for h in kind_by_heading if h in low)
                sections.append({
                    "heading": line,
                    "kind": kind_by_heading[matched],
                    "page": pg["page_no"],
                    "summary": "",
                })
                break
    return sections


def parse_pdf(data: bytes) -> dict:
    """# legacy: not yet migrated — 旧结构 IR（pages/sections/full_text/corpus）。

    新代码改用 ``app.modules.parse.parse`` + ``persist``（保留完整物理页、块与坐标）。
    """
    pages = extract_pdf_pages(data)
    full_text = "\n\n".join(p["text"] for p in pages)
    sections = detect_sections(pages)
    return {
        "pages": pages,
        "sections": sections,
        "full_text": full_text,
        "corpus": full_text[:20000],
    }


def default_upload_dir() -> Path:
    """# legacy: not yet migrated — 历史上传目录。

    新路径：``app.modules.papers`` 内容寻址存储（``settings.assets_dir``）。
    """
    backend = Path(__file__).resolve().parents[2]
    d = backend / "data" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(dir_path: Path, filename: str, data: bytes) -> Path:
    """# legacy: not yet migrated — 历史同名写盘（**会覆盖同名文件**）。

    新路径：``app.modules.papers.store_source`` / ``put_asset``（临时文件 → sha256 →
    原子 rename；同名不覆盖）。
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "upload.pdf"
    target = dir_path / safe
    target.write_bytes(data)
    return target


__all__ = [
    "extract_pdf_pages",
    "detect_sections",
    "parse_pdf",
    "default_upload_dir",
    "save_upload",
]
