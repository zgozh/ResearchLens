"""ResearchLens Benchmark CLI.

用法（在 backend/ 目录下）：
    python -m evals.run_benchmark
    python -m evals.run_benchmark --live        # 调用真实 LLM 抽取（需配置 .env 的 API）
    python -m evals.run_benchmark --limit 3

输出：控制台报告 + evals/report.json（真实测得的数据，供答辩 PPT 使用）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.dataset import load_dataset
from evals.benchmark import run_benchmark
from app.services.ai import get_ai


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="调用真实 LLM 抽取")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 篇")
    ap.add_argument("--out", default=str(Path(__file__).parent / "report.json"))
    args = ap.parse_args()

    papers = load_dataset()
    if args.limit:
        papers = papers[: args.limit]

    ai = get_ai()
    if not (ai and ai.ready):
        print("[warn] LLM_API_KEY 为空，--live 需要真实 API；将用空抽取演示。")
        from evals.benchmark import compute_paper_metrics, _aggregate
        per_paper = [compute_paper_metrics(p, []) for p in papers]
        report = {"papers": per_paper, "aggregate": _aggregate(per_paper)}
    else:
        print(f"[run] 使用 LLM 对 {len(papers)} 篇论文做真实抽取…")
        report = run_benchmark(ai, papers)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    agg = report["aggregate"]
    print("\n=== ResearchLens Evaluation (Benchmark) ===")
    for k, v in agg.items():
        print(f"  {k:32} {v}")
    print(f"\n详细结果 → {args.out}")


if __name__ == "__main__":
    main()
