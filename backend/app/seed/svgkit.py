"""Programmatic SVG figure renderer.

Spec §25: 生成式 AI 只负责结构化内容，视觉输出由程序渲染。This module turns paper data
(tables / method steps / graph / metrics) into original, consistent SVG figures so the
demo needs no third-party copyrighted images and stays deterministic.

All functions return an inline `<svg>` string.
"""
from __future__ import annotations

import html
from typing import Any, List, Optional

# A cohesive "research lab" palette (dark-aware). Colors are saturated enough on both.
PALETTE = {
    "indigo": "#6366F1",
    "violet": "#8B5CF6",
    "cyan": "#22D3EE",
    "emerald": "#34D399",
    "amber": "#F59E0B",
    "rose": "#FB7185",
    "slate": "#94A3B8",
    "ink": "#0B1220",
    "panel": "#0F172A",
    "line": "#334155",
}

_NS = 'xmlns="http://www.w3.org/2000/svg"'
_FONT = 'font-family="Inter, system-ui, -apple-system, Segoe UI, sans-serif"'


def _esc(s: Any) -> str:
    return html.escape(str(s))


def _wrap_text(text: str, width: int, nchars: int = 26) -> List[str]:
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > nchars:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def _render_text(
    text: str,
    x: float,
    y: float,
    size: int,
    color: str = "#E2E8F0",
    weight: int = 500,
    anchor: str = "start",
    width: Optional[float] = None,
    line_h: int = 18,
) -> str:
    if width:
        parts = []
        lines = _wrap_text(text, width)
        for i, ln in enumerate(lines):
            parts.append(
                f'<text x="{x}" y="{y + i * line_h}" font-size="{size}" {_FONT} '
                f'fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{_esc(ln)}</text>'
            )
        return "".join(parts)
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" {_FONT} '
        f'fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{_esc(text)}</text>'
    )


def _clip(bounds: str, content: str) -> str:
    return (
        f'<clipPath id="c"><rect x="0" y="0" width="{bounds}" height="320"/></clipPath>'
        f'<g clip-path="url(#c)">{content}</g>'
    )


def _frame(title: str, w: int = 720, h: int = 320, tag: str = "") -> str:
    tag_el = f'<text x="{w - 12}" y="26" font-size="11" {_FONT} fill="#64748B" text-anchor="end">{_esc(tag)}</text>'
    return (
        f'<svg {_NS} viewBox="0 0 {w} {h}" width="100%" height="100%" role="img" preserveAspectRatio="xMidYMid meet">'
        f'<rect width="{w}" height="{h}" rx="14" fill="{PALETTE["panel"]}"/>'
        f'<text x="18" y="30" font-size="15" {_FONT} fill="#E2E8F0" font-weight="700">{_esc(title)}</text>'
        f'{tag_el}'
    )


def bar_chart(
    title: str,
    labels: List[str],
    values: List[float],
    color: str = PALETTE["indigo"],
    tag: str = "",
    w: int = 720,
    h: int = 320,
) -> str:
    """Vertical bar chart with value labels."""
    n = len(labels)
    pad_l, pad_r, pad_b, pad_t = 46, 16, 42, 46
    cw = (w - pad_l - pad_r) / n
    max_v = max(values + [1e-9])
    gx0, gy0 = pad_l, pad_t
    gx1, gy1 = w - pad_r, h - pad_b
    parts = [_frame(title, w, h, tag)]
    # gridlines
    for gi in range(5):
        f = gi / 4
        gy = gy1 - f * (gy1 - gy0)
        parts.append(f'<line x1="{gx0}" y1="{gy}" x2="{gx1}" y2="{gy}" stroke="#1E293B" stroke-width="1"/>')
        parts.append(_render_text(f"{max_v*f:.1f}", gx0 - 8, gy + 4, 10, "#64748B", anchor="end"))
    # baseline
    parts.append(f'<line x1="{gx0}" y1="{gy1}" x2="{gx1}" y2="{gy1}" stroke="{PALETTE["line"]}" stroke-width="1.5"/>')
    for i, (lb, val) in enumerate(zip(labels, values)):
        cx = gx0 + cw * (i + 0.5)
        bh = (val / max_v) * (gy1 - gy0)
        x = cx - cw * 0.32
        y = gy1 - bh
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cw*0.64:.1f}" height="{max(bh,2):.1f}" rx="6" '
            f'fill="{color}" opacity="0.92"/>'
        )
        parts.append(
            f'<text x="{cx}" y="{y - 8}" font-size="12" {_FONT} fill="#E2E8F0" font-weight="700" text-anchor="middle">{val:.1f}</text>'
        )
        parts.append(
            f'<text x="{cx}" y="{gy1 + 20}" font-size="10.5" {_FONT} fill="#94A3B8" text-anchor="middle">{_esc(str(lb))}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def line_chart(
    title: str,
    series: List[dict],  # [{name, color?, points:[{x,y}]}]
    x_labels: Optional[List[str]] = None,
    tag: str = "",
    w: int = 720,
    h: int = 320,
) -> str:
    pad_l, pad_r, pad_b, pad_t = 54, 18, 40, 46
    gx0, gy0, gx1, gy1 = pad_l, pad_t, w - pad_r, h - pad_b
    parts = [_frame(title, w, h, tag)]
    all_x = sorted({p["x"] for s in series for p in s["points"]})
    all_y = [p["y"] for s in series for p in s["points"]]
    max_v = max(all_y + [1e-9])
    for gi in range(5):
        f = gi / 4
        gy = gy1 - f * (gy1 - gy0)
        parts.append(f'<line x1="{gx0}" y1="{gy}" x2="{gx1}" y2="{gy}" stroke="#1E293B" stroke-width="1"/>')
        parts.append(_render_text(f"{max_v*f:.1f}", gx0 - 8, gy + 4, 10, "#64748B", anchor="end"))
    parts.append(f'<line x1="{gx0}" y1="{gy1}" x2="{gx1}" y2="{gy1}" stroke="{PALETTE["line"]}" stroke-width="1.5"/>')
    parts.append(f'<line x1="{gx0}" y1="{gy0}" x2="{gx0}" y2="{gy1}" stroke="{PALETTE["line"]}" stroke-width="1.5"/>')
    for si, s in enumerate(series):
        color = s.get("color") or PALETTE["indigo"]
        pts = []
        n = max(len(all_x) - 1, 1)
        for pt in s["points"]:
            px = gx0 + 6 + (pt["x"] - min(all_x)) / max(max(all_x) - min(all_x), 1) * (gx1 - gx0 - 12)
            py = gy1 - (pt["y"] / max_v) * (gy1 - gy0)
            pts.append(f"{px:.1f},{py:.1f}")
        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>')
        for pt in s["points"]:
            px = gx0 + 6 + (pt["x"] - min(all_x)) / max(max(all_x) - min(all_x), 1) * (gx1 - gx0 - 12)
            py = gy1 - (pt["y"] / max_v) * (gy1 - gy0)
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{color}"/>')
    if x_labels:
        for i, lb in enumerate(x_labels):
            px = gx0 + 6 + i / max(len(x_labels) - 1, 1) * (gx1 - gx0 - 12)
            parts.append(f'<text x="{px}" y="{gy1 + 20}" font-size="10.5" {_FONT} fill="#94A3B8" text-anchor="middle">{_esc(str(lb))}</text>')
    # legend
    lx = gx0
    for si, s in enumerate(series):
        color = s.get("color") or PALETTE["indigo"]
        parts.append(f'<rect x="{lx}" y="{gy0 - 22}" width="12" height="4" rx="2" fill="{color}"/>')
        parts.append(_render_text(s.get("name", "series"), lx + 16, gy0 - 17, 11, "#94A3B8"))
        lx += 20 + len(str(s.get("name", "series"))) * 6.4 + 20
    parts.append("</svg>")
    return "".join(parts)


def pipeline(
    title: str,
    steps: List[dict],  # [{label, detail?, phase?, color?}]
    tag: str = "",
    w: int = 720,
    h: int = 320,
) -> str:
    """Horizontal method pipeline (original figure for the Method scene)."""
    parts = [_frame(title, w, h, tag)]
    n = len(steps)
    box_w = (w - 60 - (n - 1) * 46) / n
    top = 96
    box_h = 150
    cx0 = 30 + box_w / 2
    cy = top + box_h / 2
    for i, st in enumerate(steps):
        color = st.get("color") or PALETTE["indigo"]
        x = 30 + i * (box_w + 46)
        parts.append(
            f'<rect x="{x:.1f}" y="{top}" width="{box_w:.1f}" height="{box_h}" rx="12" '
            f'fill="{color}" fill-opacity="0.14" stroke="{color}" stroke-width="1.6"/>'
        )
        # index badge
        parts.append(
            f'<circle cx="{x + box_w/2:.1f}" cy="{top + 24}" r="13" fill="{color}"/>'
            f'<text x="{x + box_w/2:.1f}" y="{top + 29}" font-size="12" {_FONT} fill="#0B1220" font-weight="800" text-anchor="middle">{i+1}</text>'
        )
        parts.append(
            f'<text x="{x + box_w/2:.1f}" y="{top + 62}" font-size="13" {_FONT} fill="#E2E8F0" font-weight="700" text-anchor="middle">{_esc(st.get("label", ""))[:16]}</text>'
        )
        if st.get("detail"):
            parts.append(_render_text(st["detail"], x + box_w / 2, top + 86, 10.5, "#94A3B8", anchor="middle", width=box_w - 12, line_h=14))
        if i < n - 1:
            ax = x + box_w
            parts.append(
                f'<line x1="{ax:.1f}" y1="{cy}" x2="{ax + 46:.1f}" y2="{cy}" stroke="{PALETTE["line"]}" stroke-width="2" stroke-dasharray="4 3"/>'
                f'<path d="M {(ax + 46 - 6):.1f} {cy - 6} L {ax + 52:.1f} {cy} L {(ax + 46 - 6):.1f} {cy + 6} Z" fill="{PALETTE["line"]}"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


def matrix(
    title: str,
    headers: List[str],
    rows: List[List[Any]],
    tag: str = "",
    w: int = 720,
    h: int = 320,
) -> str:
    """A results table rendered as a clean figure (as SVGs keep rows crisp)."""
    parts = [_frame(title, w, h, tag)]
    ncols = len(headers)
    pad_l, pad_t = 40, 64
    tw = w - pad_l * 2
    colw = tw / ncols
    rowh = 26
    y0 = pad_t
    # header
    for c, hd in enumerate(headers):
        x = pad_l + c * colw
        parts.append(f'<rect x="{x}" y="{y0}" width="{colw}" height="{rowh}" fill="#1E293B"/>')
        parts.append(_render_text(hd, x + 10, y0 + 17, 11.5, "#CBD5E1", weight=700))
    y = y0 + rowh
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            x = pad_l + c * colw
            if r % 2 == 0:
                parts.append(f'<rect x="{x}" y="{y}" width="{colw}" height="{rowh}" fill="#0F1B31"/>')
            parts.append(_render_text(val, x + 10, y + 17, 11, "#94A3B8"))
        y += rowh
    parts.append("</svg>")
    return "".join(parts)


def scatter(
    title: str,
    points: List[dict],  # [{x,y,color?,label?}]
    tag: str = "",
    w: int = 720,
    h: int = 320,
) -> str:
    pad_l, pad_r, pad_b, pad_t = 54, 18, 40, 46
    gx0, gy0, gx1, gy1 = pad_l, pad_t, w - pad_r, h - pad_b
    parts = [_frame(title, w, h, tag)]
    xs = [p["x"] for p in points]
    ys = [p["y"] for p in points]
    xmin, xmax = min(xs + [0]), max(xs + [1])
    ymin, ymax = min(ys + [0]), max(ys + [1])
    for gi in range(5):
        f = gi / 4
        gy = gy1 - f * (gy1 - gy0)
        parts.append(f'<line x1="{gx0}" y1="{gy}" x2="{gx1}" y2="{gy}" stroke="#1E293B" stroke-width="1"/>')
        parts.append(_render_text(f"{ymin + f*(ymax-ymin):.1f}", gx0 - 8, gy + 4, 10, "#64748B", anchor="end"))
    for p in points:
        px = gx0 + (p["x"] - xmin) / max(xmax - xmin, 1e-9) * (gx1 - gx0)
        py = gy1 - (p["y"] - ymin) / max(ymax - ymin, 1e-9) * (gy1 - gy0)
        color = p.get("color") or PALETTE["indigo"]
        r = p.get("r") or 6
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r}" fill="{color}" opacity="0.85"/>')
        if p.get("label"):
            parts.append(_render_text(p["label"], px + 8, py + 4, 10.5, "#CBD5E1"))
    parts.append("</svg>")
    return "".join(parts)


def architecture(
    title: str,
    blocks: List[dict],  # [{x,y,w,h,label,color?,sub?}]
    links: List[dict],  # [{from:[x,y], to:[x,y], label?}]
    tag: str = "System Architecture",
    w: int = 720,
    h: int = 320,
) -> str:
    parts = [_frame(title, w, h, tag)]
    for b in blocks:
        color = b.get("color") or PALETTE["indigo"]
        parts.append(
            f'<rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" rx="10" '
            f'fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="1.4"/>'
        )
        parts.append(_render_text(b.get("label", ""), b["x"] + b["w"] / 2, b["y"] + (b.get("sub") and b["h"] / 2 - 6 or b["h"] / 2 + 5), 13, "#E2E8F0", weight=700, anchor="middle", width=b["w"] - 14))
        if b.get("sub"):
            parts.append(_render_text(b["sub"], b["x"] + b["w"] / 2, b["y"] + b["h"] / 2 + 16, 10, "#94A3B8", anchor="middle", width=b["w"] - 14))
    for lk in links:
        (x1, y1), (x2, y2) = lk["from"], lk["to"]
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{PALETTE["line"]}" stroke-width="1.6" stroke-dasharray="3 3"/>'
            f'<circle cx="{x2}" cy="{y2}" r="3.5" fill="{PALETTE["line"]}"/>'
        )
        if lk.get("label"):
            parts.append(_render_text(lk["label"], (x1 + x2) / 2, (y1 + y2) / 2 - 6, 10, "#64748B", anchor="middle"))
    parts.append("</svg>")
    return "".join(parts)
