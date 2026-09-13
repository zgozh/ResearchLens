"""端到端验收（第二批）：claims 详情桥接 + QA SSE 真跑 + 前端产物核对。

用法: backend/.venv/Scripts/python.exe scripts/acceptance/verify_e2e_extra.py [base] [frontend]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
FRONT = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:4002"
failures = 0


def check(label: str, ok: bool, detail: str = "") -> bool:
    global failures
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1
    return ok


def get_json(path: str, timeout: int = 120):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc)


def post_sse(path: str, payload: dict, timeout: int = 180):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    events: list[tuple[str, dict]] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.status
        buf = ""
        for raw in resp:
            buf += raw.decode("utf-8", "replace")
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                name, data = "message", ""
                for line in block.splitlines():
                    if line.startswith("event:"):
                        name = line[6:].strip()
                    elif line.startswith("data:"):
                        data += line[5:].strip()
                if data:
                    try:
                        events.append((name, json.loads(data)))
                    except json.JSONDecodeError:
                        events.append((name, {"_raw": data[:200]}))
    return status, events


print("=== 1. claims 详情桥接（此前对 canonical 断言恒 404） ===")
status, claims = get_json("/api/papers/1/claims")
check("GET /claims 200 且有断言", status == 200 and bool(claims), f"{status} n={len(claims or [])}")
if claims:
    cid = claims[0]["claim_id"]
    st, detail = get_json(f"/api/papers/1/claims/{cid}")
    check(f"GET /claims/{cid} 200（此前 404）", st == 200 and isinstance(detail, dict), f"HTTP {st}")
    if isinstance(detail, dict):
        check("详情带 statement 正文", bool((detail.get("statement") or "").strip()),
              repr((detail.get("statement") or "")[:40]))
        check("详情带 evidence 列表字段", isinstance(detail.get("evidence"), list),
              f"{len(detail.get('evidence') or [])} 条")
    st2, _ = get_json("/api/papers/1/claims/definitely-not-a-claim")
    check("未知 claim_id 仍是 404（不是 500）", st2 == 404, f"HTTP {st2}")

print("\n=== 2. 证据问答 SSE（注入快照前恒 abstained/空气泡） ===")
try:
    st, events = post_sse("/api/papers/1/qa/stream", {"question": "这篇论文提出的方法是什么？", "top_k": 5})
    kinds = [k for k, _ in events]
    print(f"  SSE HTTP {st}，事件类型 = {kinds}")
    final = next((d for k, d in events if k == "final"), None)
    answer = ""
    if isinstance(final, dict):
        answer = (((final.get("answer") or {}).get("text") or {}).get("text") or "")
    check("SSE 200", st == 200, f"HTTP {st}")
    check("有 status/final 事件", "final" in kinds)
    check("final 带非空答案（此前恒为空串）", bool(answer.strip()), repr(answer[:80]))
    check("有 citation 或 sentence 事件（此前恒无）",
          any(k in kinds for k in ("citation", "sentence")), f"kinds={kinds}")
except Exception as exc:  # noqa: BLE001
    check("QA SSE 调用成功", False, repr(exc))

print("\n=== 3. 前端产物包含本轮修复标记 ===")
# 直接读前端容器的 .next 构建产物，确认新逻辑真的进了 bundle
import subprocess

MARKERS = {
    "在原件中打开本节": "PaperView 章节锚点跳转",
    "未评测": "EvalView 诚实未评测态",
    "原件媒体": "PaperView canonical 媒体独立区块",
    "另有": "PresenterView 未解析引用提示",
}
for marker, label in MARKERS.items():
    try:
        out = subprocess.run(
            ["docker", "exec", "researchlens-frontend-1", "sh", "-c",
             f"grep -rl '{marker}' /app/.next 2>/dev/null | head -3"],
            capture_output=True, text=True, timeout=120,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        out = ""
        label = f"{label}（探针失败 {exc}）"
    check(f"bundle 含「{marker}」（{label}）", bool(out), out.splitlines()[0] if out else "0 命中")

print(f"\n总计失败断言：{failures}")
sys.exit(1 if failures else 0)
