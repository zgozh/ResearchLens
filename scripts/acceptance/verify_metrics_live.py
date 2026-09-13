"""本轮改动（ADR-0052）的**线上**实测：统计口径是否真的生效。

用法: backend/.venv/Scripts/python.exe scripts/acceptance/verify_metrics_live.py [base]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
fails = 0


def get(path: str, timeout: int = 300):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc)


def check(label: str, ok: bool, detail: str = "") -> None:
    global fails
    if not ok:
        fails += 1
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")


status, papers = get("/api/papers")
check("GET /api/papers 200", status == 200, f"HTTP {status}")
items = papers if isinstance(papers, list) else (papers or {}).get("items", [])

for p in items[:3]:
    pid = p.get("id")
    print(f"\n=== paper {pid} ===")

    s, stmts = get(f"/api/papers/{pid}/statements")
    n_stmt = len(stmts.get("items", stmts) if isinstance(stmts, dict) else (stmts or []))
    check("GET /statements 200 且非空", s == 200 and n_stmt > 0, f"HTTP {s} n={n_stmt}")

    s, pres = get(f"/api/papers/{pid}/presentation")
    scenes = (pres or {}).get("scenes") or []
    texted = [
        x for x in scenes
        if str((x.get("narration") or {}).get("script") or x.get("summary") or "").strip()
    ]
    check("GET /presentation 200 且有讲稿", s == 200 and len(texted) > 0,
          f"HTTP {s} scenes={len(scenes)} 有讲稿={len(texted)}")

    s, ev = get(f"/api/papers/{pid}/evaluation")
    check("GET /evaluation 200", s == 200, f"HTTP {s}")
    m = (ev or {}).get("metrics") or {}
    proxy = m.get("proxy")
    ne = m.get("not_evaluated")
    check("metrics.proxy 是列表（本轮新增）", isinstance(proxy, list), f"proxy={proxy}")
    check("metrics.not_evaluated 是列表", isinstance(ne, list), f"n={len(ne) if ne else 0}")
    # 关键：proxy 项的值必须真的写进 metrics，不能是 null
    if proxy:
        null_proxy = [k for k in proxy if m.get(k) is None]
        check("proxy 项都有值（未被丢成 null）", not null_proxy, f"为 null 的 proxy={null_proxy}")
    # recovery_success_rate 新口径
    rec = m.get("recovery_success_rate")
    status_text = "not_evaluated" if rec is None else f"value={rec}"
    check("recovery_success_rate 口径可见（本轮改为按答案粒度）", True, status_text)
    # overall_score 纪律：金标集未人工确认时必须 null
    check("overall_score 未假装可用（金标集未人工确认 → available=false）",
          m.get("overall_score_available") is False,
          f"available={m.get('overall_score_available')} score={m.get('overall_score')}")

print(f"\n总失败断言：{fails}")
sys.exit(1 if fails else 0)
