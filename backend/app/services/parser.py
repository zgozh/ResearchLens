"""Paper parser (Spec §28). Live path: PDF → pages/sections/figures/tables.

Demo path does not call this — the 3 demo papers are fully structured seeds.
This module exists so a real uploaded PDF can be processed with only lightweight
deps (pypdf), and structure is then enriched by a vision/LLM step when available.
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
    """Return [{page_no, text, region_map}]."""
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
    """Heuristic heading detection → sections with a mapped kind."""
    kind_by_heading: Dict[str, str] = {}
    for raw, kind, _ in _SECTION_HINTS:
        kind_by_heading[raw] = kind

    sections: List[dict] = []
    for pg in pages:
        # find candidate heading lines (short lines, mostly titles)
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
                break  # one heading per page is enough
    return sections


def parse_pdf(data: bytes) -> dict:
    """Full parse → structure IR (structure extraction step)."""
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
    """Default upload directory (absolute) — resolves relative to backend root."""
    backend = Path(__file__).resolve().parents[2]
    d = backend / "data" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(dir_path: Path, filename: str, data: bytes) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "upload.pdf"
    target = dir_path / safe
    target.write_bytes(data)
    return target
