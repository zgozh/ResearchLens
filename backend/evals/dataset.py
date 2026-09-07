"""ResearchLens Benchmark 数据集（paper text + ground-truth claims）。

Spec §22: 目标「10 papers / 100 claims」。本模块是数据驱动的 —— 在 `dataset/` 目录放入更多
JSON（或在此追加条目）即可扩展；runner 会对此做真实的 LLM 抽取并计算指标（不是编造数字）。

每条 paper:
  id, title, text(正文语料，供 LLM 抽取), gt_claims[{statement,type,evidence_pages,evidence_region}]
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

DATASET_DIR = Path(__file__).parent / "dataset"

# 内建样例（3 papers / 30 claims）。追加更多 JSON 即可扩展到 10 papers / 100 claims。
_EMBEDDED: List[Dict] = [
    {
        "id": "bench_001",
        "title": "SlimSeg-Net: An Efficient Cross-Attention Network for Real-Time Medical Image Segmentation",
        "text": (
            "Real-time segmentation networks trade accuracy for speed. We introduce SlimSeg-Net, which uses "
            "Ghost convolutions in the encoder to cut FLOPs and a Cross-Attention Gate that fuses spatial and "
            "channel context before the decoder. On the KP-MRI benchmark SlimSeg-Net reaches 0.894 Dice with only "
            "2.1M parameters, and runs at 42 FPS on a consumer GPU, surpassing larger baselines on the best "
            "accuracy-per-parameter frontier. The attention module transfers to chest X-ray pathology masks with "
            "negligible retraining cost. An ablation shows the Cross-Attention Gate contributes +1.9 Dice over a "
            "Ghost-Conv baseline. We evaluate against six baselines across three data splits. In the discussion we "
            "note that attention was tuned for 2D slices and that 3D volumetric and multi-center generalization "
            "are not yet validated. Existing backbones are either heavy or underperform. Clinical demand requires "
            "edge-deployable models, so a lightweight yet accurate network is needed. We also report Dice, IoU, "
            "parameters, FLOPs, and FPS for every model. The gate was tuned only for 2D slices, which is the main "
            "limitation of our study."
        ),
        "gt_claims": [
            {"statement": "SlimSeg-Net achieves 0.894 Dice on the KP-MRI benchmark.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_1"},
            {"statement": "The Cross-Attention Gate contributes +1.9 Dice over the Ghost-Conv baseline.", "type": "METHOD", "evidence_pages": [6], "evidence_region": "fig_3"},
            {"statement": "SlimSeg-Net runs at 42 FPS on a consumer GPU with 2.1M parameters.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_1"},
            {"statement": "The model transfers to chest X-ray pathology masks with low retraining cost.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_2"},
            {"statement": "The attention was tuned for 2D slices only.", "type": "LIMITATION", "evidence_pages": [8], "evidence_region": "discussion"},
            {"statement": "3D volumetric and multi-center generalization are not validated.", "type": "LIMITATION", "evidence_pages": [8], "evidence_region": "discussion"},
            {"statement": "Ghost convolutions reduce FLOPs in the encoder.", "type": "METHOD", "evidence_pages": [3], "evidence_region": "method"},
            {"statement": "The evaluation compares six baselines across three splits.", "type": "EXPERIMENT", "evidence_pages": [6], "evidence_region": "experiments"},
            {"statement": "The method is evaluated in Dice, IoU, parameters, FLOPs and FPS.", "type": "EXPERIMENT", "evidence_pages": [6], "evidence_region": "experiments"},
            {"statement": "A Cross-Attention Gate fuses spatial and channel context before the decoder.", "type": "METHOD", "evidence_pages": [3], "evidence_region": "method"},
        ],
    },
    {
        "id": "bench_002",
        "title": "NetGuard: Graph Contrastive Detection of Zero-Day Lateral Movement from Host Telemetry",
        "text": (
            "Signature-based EDR tools fail against unknown lateral movement. NetGuard models host telemetry as a "
            "privilege-and-process graph and learns a contrastive subgraph embedding without attack labels. It flags "
            "suspicious login-to-process chains by divergence from benign context rather than known signatures. On "
            "the LT24 benchmark NetGuard reaches 0.91 AUC while preserving 0.98 benign precision, and it explains "
            "every alert with the induced subgraph, reducing analyst triage time. We compare against five detectors. "
            "The method relies on host-level telemetry coverage, and we note that cross-tenant and large-scale "
            "aggregation are not yet validated. Alerts are shipped with an inducing subgraph, allowing 0.8s average "
            "triage. Contrastive subgraph embeddings detect attacks without attack labels. Human agreement on the "
            "explanations reached 88 percent. Existing detectors either give plain or no explanation. Detection "
            "depends on coverage of host telemetry, which is a known limitation in our setting."
        ),
        "gt_claims": [
            {"statement": "NetGuard reaches 0.91 AUC on the LT24 benchmark.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_1"},
            {"statement": "NetGuard keeps 0.98 benign precision.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_1"},
            {"statement": "Contrastive subgraph embeddings detect attacks without attack labels.", "type": "METHOD", "evidence_pages": [3], "evidence_region": "method"},
            {"statement": "Every alert is explained with an inducing subgraph.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_2"},
            {"statement": "Average analyst triage time is 0.8 seconds.", "type": "RESULT", "evidence_pages": [8], "evidence_region": "table_2"},
            {"statement": "Human agreement on explanations reached 88 percent.", "type": "RESULT", "evidence_pages": [8], "evidence_region": "table_2"},
            {"statement": "Detection depends on host-level telemetry coverage.", "type": "LIMITATION", "evidence_pages": [8], "evidence_region": "discussion"},
            {"statement": "Cross-tenant and large-scale aggregation are not validated.", "type": "LIMITATION", "evidence_pages": [8], "evidence_region": "discussion"},
            {"statement": "The comparison is against five detectors.", "type": "EXPERIMENT", "evidence_pages": [6], "evidence_region": "experiments"},
            {"statement": "Suspicious login-to-process chains are flagged by divergence from benign context.", "type": "METHOD", "evidence_pages": [3], "evidence_region": "method"},
        ],
    },
    {
        "id": "bench_003",
        "title": "LearnFlow: A Knowledge-Graph Tutor that Personalizes Adaptive Practice from Mistake Patterns",
        "text": (
            "Generic practice platforms give every student the same next exercise. LearnFlow builds a knowledge "
            "graph of skills and models each learner's mistake patterns as latent misconceptions, then chooses the "
            "next exercise that maximizes expected mastery gain. In a six-week randomized study with 620 "
            "undergraduates, LearnFlow raised post-test mastery by 14.8 percent and reduced off-task repetition by "
            "31 percent compared with a difficulty-adaptive baseline. All recommendations are traceable to the "
            "linked skill in the knowledge graph. The skill graph is course-specific, and we note that cross-course "
            "transfer, long-term effects and self-report bias are unresolved. The recommendation policy ablation "
            "shows the full model outperforms difficulty-adaptive and knowledge-graph-only baselines. The study "
            "lasted six weeks and involved 620 undergraduates. Off-task repetition fell by 31 percent. The method "
            "maximizes expected mastery gain when selecting the next exercise."
        ),
        "gt_claims": [
            {"statement": "LearnFlow raised post-test mastery by 14.8 percent.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_1"},
            {"statement": "Off-task repetition decreased by 31 percent.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_1"},
            {"statement": "The study was a six-week randomized study with 620 undergraduates.", "type": "EXPERIMENT", "evidence_pages": [6], "evidence_region": "study"},
            {"statement": "Every recommendation is traceable to a skill in the knowledge graph.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_2"},
            {"statement": "A knowledge graph of skills is built and mistake patterns are modeled as latent misconceptions.", "type": "METHOD", "evidence_pages": [3], "evidence_region": "method"},
            {"statement": "The next exercise is chosen by maximizing expected mastery gain.", "type": "METHOD", "evidence_pages": [3], "evidence_region": "method"},
            {"statement": "The skill graph is course-specific.", "type": "LIMITATION", "evidence_pages": [8], "evidence_region": "discussion"},
            {"statement": "Cross-course transfer and long-term effects are unresolved.", "type": "LIMITATION", "evidence_pages": [8], "evidence_region": "discussion"},
            {"statement": "Self-report bias is a limitation of the study.", "type": "LIMITATION", "evidence_pages": [8], "evidence_region": "discussion"},
            {"statement": "The full model outperforms difficulty-adaptive and knowledge-graph-only baselines.", "type": "RESULT", "evidence_pages": [7], "evidence_region": "table_2"},
        ],
    },
]


def load_dataset() -> List[Dict]:
    """Load embedded dataset + any JSON files under dataset/ for extensibility."""
    data: List[Dict] = [dict(x) for x in _EMBEDDED]
    if DATASET_DIR.exists():
        for f in sorted(DATASET_DIR.glob("*.json")):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(obj, list):
                data.extend(obj)
            elif isinstance(obj, dict):
                data.append(obj)
    return data
