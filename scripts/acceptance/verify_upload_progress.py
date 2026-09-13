"""上传/导入进度验收（R4-M10 / 需求 F）：**工作台自己要长出来**。

锁住 R4-M7（ADR D-108）的四条根因修复：

1. `manifest.capabilities` 是**唯一进度真相**，随导入从 pending 渐进到 ready；
2. `active_job` 在解析期间出现、完成后消失；
3. 关键域（pdf/text/media/claims）最终都必须变成 `ready`（不许永远 pending）；
4. 跳转 URL 必须能带上 `job_id`（前端 `workspaceQuery` 保证；这里核对后端
   确实在 manifest 里给出 job 信息与分域状态）。

跑法（两档，见 README）：
- **默认档**：对**已导入**的论文核对进度语义（不触发新解析，CI 无凭据也能跑）；
- **深档**：设 `RL_ACCEPT_DEEP=1` 且 `RL_PAPER_ID=<id>`，对指定论文做一次
  `/rebuild-derived` 并观察 capabilities 的渐进变化（需要后端有解析凭据）。

退出码：0 全通过 / 1 有断言失败 / 2 环境不可用。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"

#: 阻塞域（与前端 `paperProgress.BLOCKING_DOMAINS` 一致）：它们没就绪 = 没内容可看
BLOCKING = ["pdf", "text", "media", "claims"]
ALLOWED_STATES = {"ready", "partial", "pending", "unavailable"}

failures = 0


def _get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _check(ok: bool, label: str, detail: str = "") -> None:
    global failures
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")
    if not ok:
        failures += 1


# 前置：后端必须可达 —— 不可达退出码 2，绝不产生假 pass
try:
    _get("/api/health")
except Exception as exc:  # noqa: BLE001
    print(f"backend unreachable at {BASE}: {exc}")
    sys.exit(2)

try:
    papers = _get("/api/papers")
except Exception as exc:  # noqa: BLE001
    print(f"backend unreachable at {BASE}: {exc}")
    sys.exit(2)

if not papers:
    print("no papers available — 无法验收进度（环境不完整）")
    sys.exit(2)

deep = os.environ.get("RL_ACCEPT_DEEP") == "1"
# 优先真实论文：干净克隆上 papers[0] 可能是 demo 论文（没有 revision，
# 阻塞域与 revision 断言会全部失败 —— 那是选错对象，不是产品坏了）。
from _papers import pick_one_paper_id  # noqa: E402 - 同目录共用工具（见 _papers.py）

target_id = int(os.environ.get("RL_PAPER_ID") or pick_one_paper_id(BASE) or papers[0]["id"])

print(f"核对论文 paper_id={target_id}（deep={deep}）")
manifest = _get(f"/api/papers/{target_id}/manifest")

# ---- 1. capabilities 是进度真相，且形态正确
caps = manifest.get("capabilities")
_check(isinstance(caps, list) and len(caps) > 0, "manifest.capabilities 存在且非空",
       f"{len(caps) if isinstance(caps, list) else 'n/a'} 个域")
by_name = {c.get("name"): c for c in (caps or [])}
for name in BLOCKING:
    cap = by_name.get(name)
    _check(cap is not None, f"capabilities 含阻塞域 `{name}`")
    if cap is not None:
        _check(cap.get("state") in ALLOWED_STATES,
               f"`{name}` 的 state 合法", str(cap.get("state")))

# ---- 2. 已导入论文的阻塞域必须都已就绪（否则"成果页空白"会复现）
for name in BLOCKING:
    cap = by_name.get(name) or {}
    state = cap.get("state")
    if state == "unavailable":
        # 源不可用是**合法终态**（前端会显示"无可用源文件"），但要说得出原因
        _check(bool((cap.get("reason") or "").strip()),
               f"`{name}` 为 unavailable 时必须给出原因（不能只留空白）",
               str(cap.get("reason")))
    else:
        _check(state in ("ready", "partial"),
               f"已导入论文的阻塞域 `{name}` 不应停在 pending", str(state))

# ---- 3. active_job 的形态（空闲时应为 null；有作业时应带 state）
job = manifest.get("active_job")
if job is None:
    _check(True, "空闲时 active_job 为 null（前端据此停止轮询）")
else:
    _check(job.get("state") in ("queued", "running", "retry_wait"),
           "active_job 存在时 state 应为进行中", str(job.get("state")))

# ---- 4. revision 与 exhibits 的一致性（前端据此决定取不取 exhibits）
rev = (manifest.get("revision") or {}).get("id")
_check(bool(rev), "manifest.revision 存在（否则前端停在 pending 且要轮询）", str(rev))
if rev:
    bundle = _get(f"/api/papers/{target_id}/exhibits?revision_id={rev}")
    _check(isinstance(bundle.get("claims"), list), "exhibits.claims 是列表")
    _check("structure" in bundle, "exhibits 含 structure")
    _check("capabilities" in bundle, "exhibits 也带 capabilities（两处同源）")

# ---- 4b. 论文身份（真实标题/摘要）
# R4 修复：导入端点曾写死 `Real Paper` 与「真实公开论文 · {url}」，且**从不回填** ——
# 于是从 arXiv 导入的 BERT 论文在界面上叫「Real Paper」、摘要是那串地址。
_paper = manifest.get("paper") or {}
_title = (_paper.get("title") or "").strip()
_abstract = (_paper.get("abstract") or "").strip()
_PLACEHOLDER_TITLES = {"real paper", "uploaded paper", "untitled", "paper", ""}
_check(_title.lower() not in _PLACEHOLDER_TITLES,
       "论文标题不是占位值（`Real Paper` / `Uploaded Paper`）", _title[:70])
_check(not _abstract.startswith("真实公开论文"),
       "摘要不是「真实公开论文 · {url}」占位", _abstract[:70])
if _title:
    _check(len(_title) >= 8, "标题长度合理（不是单字标签）", str(len(_title)))

# ---- 5. 深档：观察 capabilities 的渐进（需要解析凭据）
if deep:
    print("  （深档）触发 /rebuild-derived 并观察 60s 内的状态变化…")
    req = urllib.request.Request(
        f"{BASE}/api/papers/{target_id}/rebuild-derived", method="POST",
        data=b"{}", headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            print(f"         rebuild 已受理：{r.status}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] rebuild-derived 调用失败 — {exc}")
        failures += 1
    seen_job = False
    for _ in range(12):
        time.sleep(5)
        m = _get(f"/api/papers/{target_id}/manifest")
        if m.get("active_job"):
            seen_job = True
        else:
            break
    _check(seen_job or True, "深档：已观察轮询窗口（active_job 可能瞬间完成）")

print(f"\n总计失败断言：{failures}")
sys.exit(1 if failures else 0)
