"""Shared helpers for building demo-paper IR (researchlens seed)."""
from __future__ import annotations

from typing import Any, List


class _Accent:
    indigo = "#6366F1"
    violet = "#8B5CF6"
    cyan = "#22D3EE"
    emerald = "#34D399"
    amber = "#F59E0B"
    rose = "#FB7185"


accent = _Accent()


def ev(page: int, region: str, region_type: str = "text", text: str = "", quote: str = "") -> dict:
    return {
        "page": page,
        "region": region,
        "region_type": region_type,
        "text": text,
        "quote": quote,
        "confidence": 0.95,
    }


def fig(fig_no: int, page: int, caption: str, svg: str, importance: str = "medium", description: str = "") -> dict:
    return {
        "fig_no": fig_no,
        "caption": caption,
        "page": page,
        "glyph_svg": svg,
        "importance": importance,
        "description": description,
    }
