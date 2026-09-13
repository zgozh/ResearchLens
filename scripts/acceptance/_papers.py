# -*- coding: utf-8 -*-
"""验收脚本共用：**按 source_mode 挑真实论文**，不再写死 id。

## 为什么需要这个模块

启动自举现在**只自动导入 1 篇**真实论文（`app/modules/pipeline/seed_real.py` 的
`AUTO_SEED_PAPERS`），所以干净克隆上 **id 2/3 很可能是 demo 论文**；而 demo 论文没有
revision —— `/exhibits` 返回 409「尚无可读 revision」、`/graph` 按设计返回空图
（`modules/graph/legacy.py`：找不到 revision 就不猜、不伪造）。

以前四套脚本写死 `for pid in (1, 2, 3)`，在新机器上会变成**断言失败（假红）**，
而不是诚实的「环境缺失（退出码 2）」。统一本模块后：本机有 3 篇真实论文就跑 3 篇，
干净克隆只有 1 篇就跑 1 篇 —— 两种情况的结果都反映真实状态。

（脚本直接用 `python scripts/acceptance/xxx.py` 跑：Python 会把脚本所在目录放进
`sys.path[0]`，所以直接 `import _papers` 即可。）
"""
from __future__ import annotations

import json
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8002"


def fetch_papers(base: str = DEFAULT_BASE, timeout: float = 30.0) -> list:
    """`GET /api/papers`。失败交给调用方处理（各脚本前置健康检查已保证可达）。"""
    with urllib.request.urlopen(f"{base}/api/papers", timeout=timeout) as r:
        rows = json.loads(r.read().decode("utf-8"))
    return rows if isinstance(rows, list) else []


def real_paper_ids(base: str = DEFAULT_BASE, limit: int = 3) -> list:
    """真实论文（`source_mode=real`）的 id，按入库顺序，最多 `limit` 篇。

    取不到就返回空列表 —— **由调用方判失败**，不要在这里悄悄退回 demo 论文
    （那会把"自举没跑起来"伪装成"验收通过"）。
    """
    try:
        rows = fetch_papers(base)
    except Exception:  # noqa: BLE001 - 兜底：调用方本来就在断言可达性
        return []
    return [int(p["id"]) for p in rows if p.get("source_mode") == "real"][:limit]


def pick_one_paper_id(base: str = DEFAULT_BASE):
    """进度/身份这类只需一篇的脚本：优先真实论文（有 revision），否则退回第一篇。"""
    try:
        rows = fetch_papers(base)
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    real = next((p for p in rows if p.get("source_mode") == "real"), None)
    return int((real or rows[0])["id"])


__all__ = ["DEFAULT_BASE", "fetch_papers", "real_paper_ids", "pick_one_paper_id"]
