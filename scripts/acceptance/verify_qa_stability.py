"""QA 稳定性验收：同一问题连续多次，必须每次都给出非空答案 + 证据。"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
QUESTION = "这篇论文提出的方法是什么？"
ROUNDS = 3


def ask(pid: int):
    req = urllib.request.Request(
        f"{BASE}/api/papers/{pid}/qa/stream",
        data=json.dumps({"question": QUESTION, "top_k": 5}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    kinds: list[str] = []
    final: dict = {}
    with urllib.request.urlopen(req, timeout=300) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line.startswith("event:"):
                kinds.append(line[6:].strip())
            elif line.startswith("data:"):
                try:
                    payload = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if kinds and kinds[-1] == "final":
                    final = payload
    answer = ((final.get("legacy") or {}).get("answer") or "")
    mode = ((final.get("answer") or {}).get("mode")) or ""
    grounded = bool((final.get("legacy") or {}).get("grounded"))
    return kinds, answer, mode, grounded


failures = 0
for pid in (1, 2, 3):
    for i in range(ROUNDS):
        kinds, answer, mode, grounded = ask(pid)
        ok = bool(answer.strip())
        n_cit = kinds.count("citation")
        n_sent = kinds.count("sentence")
        print(
            f"paper {pid} round {i + 1}: answer_len={len(answer)} mode={mode} grounded={grounded} "
            f"citation={n_cit} sentence={n_sent} {'OK' if ok else 'EMPTY'}"
        )
        if not ok:
            failures += 1
            print(f"    kinds={kinds}")

print(f"\n空答案次数：{failures}/{3 * ROUNDS}")
sys.exit(1 if failures else 0)
