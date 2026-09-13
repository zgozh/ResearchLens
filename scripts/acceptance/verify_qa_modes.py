"""QA 模式验收（R4-M10）：**没有"拒答"这一档**，每条回答都带 mode + 置信度 + 非空正文。

锁住 R4-M3/M4 的产品决策（ADR D-104）：
1. `mode` 必须落在**新取值表**里（`abstained` 已从契约删除）；
2. 每条回答都有**非空正文**与**置信度**；
3. 默认三个问题（其中「哪里最值得质疑」历史上走拒答）都能得到回答。

退出码：0 全通过 / 1 有断言失败 / 2 环境不可用。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"

#: 新 mode 取值表（`abstained` **不在此表** —— 它已从 AnswerMode 删除）
ALLOWED_MODES = {"generated", "extractive", "general", "not_mentioned", "cached", "unavailable"}
ALLOWED_CONFIDENCE = {"High", "Medium", "Low"}

#: 三个默认问题（与前端 PRESETS 一致），含历史上走拒答的那条
QUESTIONS = [
    "这篇论文哪里最值得质疑？",
    "这篇论文的主要贡献是什么？",
    "论文用了什么数据集？",
]


def ask(pid: int, question: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}/api/papers/{pid}/qa/stream",
        data=json.dumps({"question": question, "top_k": 5}).encode("utf-8"),
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
    answer = ((final.get("answer") or {}).get("text") or {}).get("text") or ""
    legacy = final.get("legacy") or {}
    return {
        "kinds": kinds,
        "answer": answer or legacy.get("answer") or "",
        "mode": ((final.get("answer") or {}).get("mode")) or legacy.get("mode") or "",
        "confidence": ((final.get("answer") or {}).get("confidence"))
        or legacy.get("confidence") or "",
        "has_final": "final" in kinds,
    }


failures = 0
checked = 0

# 前置：后端必须可达 —— 不可达就退出码 2，**绝不产生假 pass**
try:
    with urllib.request.urlopen(f"{BASE}/api/health", timeout=10) as r:
        if r.status != 200:
            raise urllib.error.URLError(f"health {r.status}")
except Exception as exc:  # noqa: BLE001
    print(f"backend unreachable at {BASE}: {exc}")
    sys.exit(2)

import pathlib  # noqa: E402
import urllib.request as _u  # noqa: E402

from _papers import real_paper_ids  # noqa: E402 - 同目录共用工具（见 _papers.py）

# 优先真实论文（启动自举只自动导入 1 篇，干净克隆上前两篇可能是 demo 论文）；
# 万一库里还没有真实论文，退回前两篇 —— 至少 mode 契约仍然被验到。
with _u.urlopen(f"{BASE}/api/papers", timeout=30) as r:
    papers = json.loads(r.read().decode("utf-8"))
paper_ids = real_paper_ids(BASE, limit=2) or [p["id"] for p in papers[:2]] or [1]
print(f"待核对论文：{paper_ids}")

for pid in paper_ids:
    for question in QUESTIONS:
        try:
            res = ask(pid, question)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  [FAIL] paper {pid} 「{question}」请求失败 — {exc}")
            continue
        checked += 1
        problems = []
        if not res["has_final"]:
            problems.append("没有 final 事件（终端保证失守）")
        if not res["answer"].strip():
            problems.append("正文为空")
        if res["mode"] == "abstained":
            problems.append("mode=abstained（该取值已从契约删除，说明拒答没退干净）")
        elif res["mode"] not in ALLOWED_MODES:
            problems.append(f"mode={res['mode']!r} 不在新取值表里")
        if res["confidence"] not in ALLOWED_CONFIDENCE:
            problems.append(f"confidence={res['confidence']!r} 非法")
        status = "OK  " if not problems else "FAIL"
        print(
            f"  [{status}] paper {pid} 「{question}」 mode={res['mode']} "
            f"conf={res['confidence']} len={len(res['answer'])}"
        )
        if problems:
            failures += 1
            for p in problems:
                print(f"         - {p}")

print(f"\n总失败断言：{failures}（共检查 {checked} 条回答）")
sys.exit(1 if failures else 0)
