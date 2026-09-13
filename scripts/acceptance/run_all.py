# -*- coding: utf-8 -*-
"""端到端验收总入口（REFACTOR_PLAN_R3 M11）。

一条命令跑全五套验收，输出**统一机读结果**：

    python scripts/acceptance/run_all.py [--base-url URL] [--frontend-url URL] [--only name,...]

约定：
- **前置健康检查**：后端不可达 → 立即非零退出并打印 `backend unreachable at {url}`，
  **不会**把后续检查标成"跳过"或"成功"（那等于自欺）；
- 每套脚本输出一行 JSON：`{script, status: pass|fail|error, failures, elapsed_ms, tail}`；
- 汇总写 `scripts/acceptance/results.json`；
- 任一 fail/error → 退出码非 0；
- 退出码：0=全绿，1=有失败，2=前置检查未通过（服务栈没起来）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BASE = os.environ.get("RL_API", "http://127.0.0.1:8002")
DEFAULT_FRONTEND = os.environ.get("RL_WEB", "http://127.0.0.1:4002")

#: 迁移入库的七套验收脚本（顺序即执行顺序）
#: R4-M10 新增两套：`verify_upload_progress.py`（需求 F：成果页自己长出来）与
#: `verify_qa_modes.py`（需求 C：没有拒答、每条回答带 mode + 置信度）。
SCRIPTS = [
    "verify_route_a.py",
    "verify_graph.py",
    "verify_e2e_extra.py",
    "verify_qa_modes.py",
    "verify_upload_progress.py",
    "verify_metrics_live.py",
    "verify_qa_stability.py",
]

# 各脚本的失败计数行实测是「总计失败断言：N」/「总失败断言：N」（不是"失败数"）
_FAIL_RE = re.compile(r"失败断言[：:]\s*(\d+)")


def _decode(raw: bytes | None) -> str:
    """子进程输出解码：Windows 上子脚本可能写 GBK、CI 上写 UTF-8 —— 两种都要认。

    实测教训：只按一种编码解码时，中文全变替换字符，连"失败数：N"都正则不出来
    （`failures` 字段恒为 null），而且把 U+FFFD 打到 GBK 控制台还会直接抛 UnicodeEncodeError。
    """
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def main() -> int:
    # Windows 控制台默认 GBK：子脚本输出里的替换字符/中文会让 print 直接抛 UnicodeEncodeError。
    # CI 与本地都统一按 UTF-8 输出（这是机读结果的正确编码）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001  某些环境不支持 reconfigure，忽略即可
            pass
    parser = argparse.ArgumentParser(description="ResearchLens 端到端验收")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND)
    parser.add_argument("--only", default="", help="逗号分隔的脚本名过滤")
    parser.add_argument("--timeout", type=int, default=900, help="单脚本超时秒数")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    # ---- 前置健康检查（不通过就直接退出，绝不产生假 pass）----
    if not _reachable(f"{base}/api/health"):
        print(f"backend unreachable at {base}", file=sys.stderr)
        return 2
    if args.frontend_url and not _reachable(args.frontend_url.rstrip("/") + "/"):
        print(f"frontend unreachable at {args.frontend_url}", file=sys.stderr)
        return 2

    wanted = [s.strip() for s in args.only.split(",") if s.strip()] or SCRIPTS
    results = []
    for name in SCRIPTS:
        if name not in wanted:
            continue
        script = HERE / name
        t0 = time.time()
        if not script.exists():
            results.append({
                "script": name, "status": "error", "failures": None,
                "elapsed_ms": 0, "tail": "脚本不存在（清单腐败？）",
            })
            print(json.dumps(results[-1], ensure_ascii=False))
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(script), base, args.frontend_url],
                capture_output=True, timeout=args.timeout,
                cwd=str(HERE.parent.parent),
            )
            out = _decode(proc.stdout) + _decode(proc.stderr)
            m = _FAIL_RE.search(out)
            failures = int(m.group(1)) if m else None
            if proc.returncode == 0:
                status = "pass"
            else:
                status = "fail"
        except subprocess.TimeoutExpired:
            out, status, failures = f"超时（>{args.timeout}s）", "error", None
        except Exception as exc:  # noqa: BLE001
            out, status, failures = f"执行异常：{exc}", "error", None
        row = {
            "script": name,
            "status": status,
            "failures": failures,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "tail": "\n".join(out.strip().splitlines()[-3:]),
        }
        results.append(row)
        print(json.dumps(row, ensure_ascii=False))

    summary = {
        "base_url": base,
        "frontend_url": args.frontend_url,
        "total": len(results),
        "passed": sum(1 for r in results if r["status"] == "pass"),
        "failed": sum(1 for r in results if r["status"] != "pass"),
        "results": results,
    }
    (HERE / "results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ("total", "passed", "failed")}, ensure_ascii=False))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
