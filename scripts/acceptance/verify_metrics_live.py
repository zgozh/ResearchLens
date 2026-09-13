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


from _papers import real_paper_ids  # 同目录共用工具（见 _papers.py）

status, papers = get("/api/papers")
check("GET /api/papers 200", status == 200, f"HTTP {status}")

# 动态挑真实论文（理由见 _papers.py）：原先取 `items[:3]`，隐含假设"前 3 篇都是真实论文"。
# 一旦库里只剩 1 篇真实论文（干净克隆，或本机清成新部署的样子），第 2/3 个就是 **demo**
# 论文 —— 它们没有 revision：/statements 会 422、/presentation 0 场景、metrics.proxy 为 None，
# 于是这套验收在**别人的机器上假红**（实测已发生）。
pids = real_paper_ids(BASE, limit=3)
check("库里有真实论文（/api/papers 中 source_mode=real）", bool(pids),
      "一篇都没有 —— 启动自举没跑或还没建论文")
print(f"待核对真实论文：{pids}")

for pid in pids:
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
    # R4-M5（ADR D-105）改写：旧规则是"金标集未人工确认 → overall_score 必须不可用"。
    # 决策 3 删除了人工维度，主分改为 **AI 质量评分（自动）**，所以新规则是：
    #   · 分数不可用时：不得填 0（这条底线没变）；
    #   · 分数可用时：必须声明来源为 `ai_generated`（**不许谎称人工评审**）。
    _avail = m.get("overall_score_available")
    _basis = m.get("overall_score_basis")
    if _avail:
        check("overall_score 可用时必须标明来源为 AI 口径（不许谎称人工评审）",
              _basis == "ai_generated",
              f"available={_avail} basis={_basis!r}")
    else:
        check("overall_score 不可用时不得填 0（未评估就是未评估）",
              m.get("overall_score_canonical") is None,
              f"available={_avail} basis={_basis!r} value={m.get('overall_score_canonical')!r}")

print(f"\n总失败断言：{fails}")
sys.exit(1 if fails else 0)
