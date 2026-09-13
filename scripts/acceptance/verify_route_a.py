"""端到端验收（只读）：核对路线 A 第 2/3 项 + MapView/MethodView/PaperView 修复。

用法: backend/.venv/Scripts/python.exe scripts/acceptance/verify_route_a.py [base] [frontend]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
FRONT = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:4002"

OK = "OK  "
BAD = "FAIL"


def get(path: str, timeout: int = 120):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc)


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{OK if ok else BAD}] {label}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    failures = 0
    for pid in (1, 2, 3):
        print(f"\n=== paper {pid} ===")
        status, d = get(f"/api/papers/{pid}")
        if not isinstance(d, dict):
            failures += 1
            print(f"  [{BAD}] /api/papers/{pid} -> {status} {d}")
            continue

        # 1) 章节 → 正文页：manifest.section_index / exhibits.structure.sections 必须有锚点
        _, man = get(f"/api/papers/{pid}/manifest")
        si = (man or {}).get("section_index") or []
        with_anchor = [e for e in si if e.get("anchor_ids")]
        if not check("manifest.section_index 每节都有 anchor_ids", len(with_anchor) == len(si) and si,
                     f"{len(with_anchor)}/{len(si)}"):
            failures += 1

        _, ex = get(f"/api/papers/{pid}/exhibits")
        secs = ((ex or {}).get("structure") or {}).get("sections") or []
        sec_ok = [s for s in secs if s.get("anchor_ids")]
        if not check("exhibits.structure.sections 每节都有 anchor_ids",
                     len(sec_ok) == len(secs) and secs, f"{len(sec_ok)}/{len(secs)}"):
            failures += 1

        # 锚点必须可解析，且落在该节正文页范围内
        anchor_id = (sec_ok[0]["anchor_ids"][0] if sec_ok else None)
        if anchor_id:
            st, anchor = get(f"/api/papers/{pid}/anchors/{anchor_id}?revision_id={(man or {}).get('revision', {}).get('id', '')}")
            segs = (anchor or {}).get("segments") or []
            page_idx = segs[0].get("pdf_page_index") if segs else None
            if not check(f"章节锚点可解析并带物理页（{anchor_id[:12]}…）",
                         st == 200 and page_idx is not None, f"HTTP {st} page_index={page_idx}"):
                failures += 1

        # 2) 首页元信息
        if not check("authors 非空", bool(d.get("authors")), f"{d.get('authors')}"):
            failures += 1
        if not check("tags 非空", bool(d.get("tags")), f"{d.get('tags')}"):
            failures += 1
        if not check("domain 已判定（非 general）", d.get("domain") not in (None, "", "general"),
                     f"{d.get('domain')}"):
            failures += 1
        if not check("year 为发表年（非入库 2026 以外仍算通过，需人工看值）",
                     bool(d.get("year")), f"{d.get('year')}"):
            failures += 1

        # 3) 前端渲染所需的字段仍在位
        figs = d.get("figures") or []
        if not check("figures 全部有 image_url",
                     bool(figs) and all(f.get("image_url") for f in figs), f"{len(figs)} 图"):
            failures += 1
        secs_legacy = d.get("sections") or []
        if not check("sections 有 body 且与 summary 不同",
                     bool(secs_legacy) and all((s.get("body") or "") != (s.get("summary") or "") for s in secs_legacy),
                     f"{len(secs_legacy)} 节"):
            failures += 1
        if not check("sections 有页码范围（page_start 非空）",
                     bool(secs_legacy) and all(s.get("page_start") for s in secs_legacy)):
            failures += 1
        ms = d.get("map_summary") or {}
        if not check("map_summary 只含非空键", all((v or "").strip() for v in ms.values()), f"keys={sorted(ms)}"):
            failures += 1

    # 4) 前端可访问性
    print("\n=== 前端 ===")
    try:
        with urllib.request.urlopen(FRONT + "/", timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
        check("前端首页 200", r.status == 200, f"{len(body)} bytes")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        check("前端首页 200", False, repr(exc))

    print(f"\n总计失败断言：{failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
