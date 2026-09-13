"""端到端验收（图谱批）：/graph 的节点/边构成与告警可见性。"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def get(path: str):
    try:
        with urllib.request.urlopen(BASE + path, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


for pid in (1, 2, 3):
    print(f"\n=== paper {pid} ===")
    st, g = get(f"/api/papers/{pid}/graph")
    if not isinstance(g, dict):
        check(f"/graph 200", False, f"HTTP {st}")
        continue
    nodes = g.get("nodes") or []
    edges = g.get("edges") or []
    kinds: dict[str, int] = {}
    for n in nodes:
        kinds[n.get("kind", "?")] = kinds.get(n.get("kind", "?"), 0) + 1
    rels: dict[str, int] = {}
    for e in edges:
        rels[e.get("relation", "?")] = rels.get(e.get("relation", "?"), 0) + 1
    print(f"  nodes={len(nodes)} {kinds}")
    print(f"  edges={len(edges)} {rels}")
    check("hits 200 且有 claim 节点", st == 200 and kinds.get("claim", 0) > 0, f"HTTP {st}")
    check("有 supports 边（此前 claim→evidence 绑定 0 条）", rels.get("supports", 0) > 0,
          f"supports={rels.get('supports', 0)}")
    check("有 evidence 节点", kinds.get("evidence", 0) > 0, f"evidence={kinds.get('evidence', 0)}")
    # 边两端必须都在节点集里（不得悬空）
    ids = {n.get("id") for n in nodes}
    dangling = [e for e in edges if e.get("source") not in ids or e.get("target") not in ids]
    check("没有悬空边", not dangling, f"{len(dangling)} 条悬空")
    # 告警可见性：legacy /graph（GraphOut）不带 warnings，canonical /exhibits 带
    st_ex, ex = get(f"/api/papers/{pid}/exhibits")
    g2 = (ex or {}).get("graph") or {}
    warns = [w.get("code") for w in (g2.get("warnings") or [])]
    check("exhibits.graph 里图谱告警可见", st_ex == 200 and isinstance(g2.get("warnings"), list),
          f"{warns[:4]}")

print(f"\n总计失败断言：{failures}")
sys.exit(1 if failures else 0)
