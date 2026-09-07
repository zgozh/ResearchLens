from __future__ import annotations

from . import svgkit as sk
from .common import accent, ev, fig

# --------------------------------------------------------------------------
# Demo Paper B — Network Security
# "NetGuard: Graph Contrastive Detection of Zero-Day Lateral Movement from
#  Host Telemetry"
# --------------------------------------------------------------------------
SLUG = "netguard"
ACCENT = accent.cyan

METHOD_STEPS = [
    {"id": "s1", "label": "Telemetry", "phase": "input", "detail": "Host events / alerts", "color": "#22D3EE"},
    {"id": "s2", "label": "Graph Build", "phase": "encoder", "detail": "Privilege+process graph", "color": "#8B5CF6"},
    {"id": "s3", "label": "GCL", "phase": "module", "detail": "Graph contrastive learning", "color": "#6366F1"},
    {"id": "s4", "label": "Anomaly", "phase": "decoder", "detail": "Subgraph scoring", "color": "#FB7185"},
    {"id": "s5", "label": "Alert", "phase": "output", "detail": "Ranked suspicious paths", "color": "#F59E0B"},
]


def build():
    return {
        "slug": SLUG,
        "title": "NetGuard: Graph Contrastive Detection of Zero-Day Lateral Movement from Host Telemetry",
        "subtitle": "基于图对比学习的主机遥测零日横向移动检测",
        "authors": ["Rui Zhang", "Tingting Fan", "Luo Meng"],
        "year": 2026,
        "domain": "cybersecurity",
        "accent": ACCENT,
        "tags": ["Cybersecurity", "Graph Contrastive Learning", "Lateral Movement", "Anomaly Detection"],
        "abstract": (
            "Signature-based EDR tools fail against unknown (zero-day) lateral movement. NetGuard models host "
            "telemetry as a privilege-and-process graph and learns a contrastive subgraph embedding without "
            "attack labels. It flags suspicious login-to-process chains by their divergence from benign context "
            "rather than known signatures. On the LT24 benchmark NetGuard reaches 0.91 AUC while preserving a "
            "0.98 benign precision, and it explains every alert with the induced subgraph—reducing analyst "
            "triage time."
        ),
        "map": {
            "problem": "EDR 依赖已知签名，对零日横向移动几乎无感知，且告警缺乏可解释证据。",
            "method": "把主机遥测建模为权限-进程图，用图对比学习学习子图嵌入，再用良性上下文偏离度判异常。",
            "dataset": "LT24 主机遥测基准（8.2M 事件、490 台主机、含注入的 74 条攻击链）。",
            "experiment": "AUC / 良性精度 / 告警体积 / 可解释性，对比 5 个检测器。",
            "result": "0.91 AUC，0.98 良性精度，单条告警平均 0.8s 出图解释，优于全部基线。",
            "limitation": "依赖主机级遥测覆盖；跨租户与大规模图实时聚合的扩展性未验证。",
        },
        "sections": [
            {"heading": "Introduction", "kind": "intro", "page": 1,
             "summary": "Signature-based detection cannot generalize to zero-day moves; explainability is a first-class need."},
            {"heading": "Background & Threat Model", "kind": "intro", "page": 2,
             "summary": "Lateral movement as a sequence of privilege changes; labeled attacks are scarce."},
            {"heading": "Method", "kind": "method", "page": 3,
             "summary": "Graph construction + graph contrastive learning + subgraph scoring."},
            {"heading": "Experiments", "kind": "experiment", "page": 6,
             "summary": "LT24 benchmark, 5 detectors, and an explainability study."},
            {"heading": "Results", "kind": "result", "page": 7,
             "summary": "0.91 AUC and 0.98 benign precision; alerts shipped with inducing subgraphs."},
            {"heading": "Discussion", "kind": "discussion", "page": 8,
             "summary": "Telemetry coverage and large-scale aggregation are the key open limits."},
        ],
        "method_steps": METHOD_STEPS,
        "figures": [
            fig(1, 3, "System architecture. Host telemetry becomes a privilege-process graph; contrastive learning produces subgraph embeddings scored by divergence from benign context.",
                sk.pipeline("NetGuard Detection Pipeline", METHOD_STEPS, tag="Fig. 1 · Original"), "high"),
            fig(2, 7, "ROC on LT24. NetGuard (cyan) achieves 0.91 AUC, outperforming all baselines.",
                sk.line_chart("ROC — LT24", [
                    {"name": "NetGuard", "color": ACCENT, "points": [{"x": 0, "y": 0.0}, {"x": 1, "y": 0.35}, {"x": 2, "y": 0.72}, {"x": 3, "y": 0.91}]},
                    {"name": "E-GraphSAGE", "color": "#94A3B8", "points": [{"x": 0, "y": 0.0}, {"x": 1, "y": 0.28}, {"x": 2, "y": 0.55}, {"x": 3, "y": 0.77}]},
                    {"name": "SIGMA", "color": "#64748B", "points": [{"x": 0, "y": 0.0}, {"x": 1, "y": 0.2}, {"x": 2, "y": 0.42}, {"x": 3, "y": 0.61}]},
                ], x_labels=["0%", "10%", "30%", "50%"], tag="Fig. 2 · ROC"), "high"),
            fig(3, 7, "Benign precision at a fixed 0.95 detection recall: NetGuard keeps 0.98 benign precision with the smallest alert volume.",
                sk.bar_chart("Benign Precision @0.95 Recall", ["SIGMA", "E-GraphSAGE", "IRIS", "NetGuard"], [0.72, 0.85, 0.90, 0.98], color=ACCENT, tag="Fig. 3"), "medium"),
        ],
        "tables": [
            {
                "table_no": 1, "page": 7,
                "caption": "Detection performance on LT24.",
                "headers": ["Detector", "AUC", "Benign Prec.", "Alerts/day", "Explain"],
                "content": [
                    ["SIGMA", "0.61", "0.72", "412", "plain"],
                    ["IRIS", "0.84", "0.90", "188", "partial"],
                    ["E-GraphSAGE", "0.77", "0.85", "231", "no"],
                    ["NetGuard", "0.91", "0.98", "23", "subgraph"],
                ],
            },
            {
                "table_no": 2, "page": 8,
                "caption": "Explanation quality (lower is better): avg. subgraph size and analyst triage time.",
                "headers": ["Method", "Avg. subgraph nodes", "Triage time (s)", "Human agree %"],
                "content": [
                    ["SIGMA", "—", "42", "61"],
                    ["E-GraphSAGE", "—", "55", "54"],
                    ["NetGuard", "11", "0.8", "88"],
                ],
            },
        ],
        "claims": [
            {"claim_id": "claim_01", "type": "RESULT", "confidence": 0.96, "statement": "NetGuard reaches 0.91 AUC on the LT24 benchmark.",
             "evidence": [ev(7, "table_1", "table", "Table 1 reports AUC 0.91 for NetGuard.", "0.91")]},
            {"claim_id": "claim_02", "type": "METHOD", "confidence": 0.95, "statement": "Contrastive subgraph embeddings detect attacks by divergence from benign context, without attack labels.",
             "evidence": [ev(3, "method", "section", "Method describes label-free contrastive subgraph learning.", "Method p.3")]},
            {"claim_id": "claim_03", "type": "RESULT", "confidence": 0.93, "statement": "Every alert is explained with an induced subgraph, reducing average analyst triage time to 0.8s.",
             "evidence": [ev(8, "table_2", "table", "Table 2 lists 0.8s triage time and 88% human agreement.", "0.8s")]},
            {"claim_id": "claim_04", "type": "LIMITATION", "confidence": 0.86, "statement": "Detection depends on host-level telemetry coverage; large-scale multi-tenant aggregation is unvalidated.",
             "evidence": [ev(8, "discussion", "section", "Discussion flags telemetry coverage and scale.", "Discussion p.8")]},
        ],
        "graph": {
            "nodes": [
                {"node_id": "g_problem", "kind": "problem", "label": "Problem", "props": {"text": "Zero-day lateral movement evades signatures"}},
                {"node_id": "g_method", "kind": "method", "label": "Method", "props": {"text": "Graph contrastive (label-free)"}},
                {"node_id": "g_dataset", "kind": "experiment", "label": "Dataset", "props": {"text": "LT24 · 8.2M events"}},
                {"node_id": "g_exp", "kind": "experiment", "label": "Experiment", "props": {"text": "5 detectors · LT24"}},
                {"node_id": "g_claim1", "kind": "claim", "label": "Claim 01", "props": {"text": "0.91 AUC", "claim_id": "claim_01"}},
                {"node_id": "g_claim3", "kind": "claim", "label": "Claim 03", "props": {"text": "0.8s explainable alert", "claim_id": "claim_03"}},
                {"node_id": "g_ev_t1", "kind": "evidence", "label": "Table 1 · p.7", "props": {"text": "AUC / prec / alerts"}},
                {"node_id": "g_ev_t2", "kind": "evidence", "label": "Table 2 · p.8", "props": {"text": "Explanation quality"}},
            ],
            "edges": [
                {"source": "g_problem", "target": "g_method", "label": "addresses"},
                {"source": "g_method", "target": "g_dataset", "label": "evaluated on"},
                {"source": "g_dataset", "target": "g_exp", "label": "benchmark"},
                {"source": "g_exp", "target": "g_claim1", "label": "supports"},
                {"source": "g_exp", "target": "g_claim3", "label": "supports"},
                {"source": "g_claim1", "target": "g_ev_t1", "label": "cited to"},
                {"source": "g_claim3", "target": "g_ev_t2", "label": "cited to"},
            ],
        },
        "presentation": [
            {"order": 1, "kind": "intro", "title": "研究背景", "summary": "签名型 EDR 对未知横向移动几乎无感知。",
             "evidence_refs": ["p.1"],
             "steps": ["零日攻击变化快", "签名依赖暴露滞后"],
             "narration": {"script": "签名型终端检测对已知攻击有效，却很难抓住从未见过的横向移动。", "subtitle": "签名检测对零日乏力。"}},
            {"order": 2, "kind": "problem", "title": "问题", "summary": "告警缺乏可解释证据，分析师难响应。",
             "evidence_refs": ["p.2 Threat Model"],
             "steps": ["攻击标签稀缺", "告警无法解释"],
             "narration": {"script": "更棘手的是标签稀缺，且传统告警无法解释，增加了响应成本。", "subtitle": "标签稀缺 + 不可解释。"}},
            {"order": 3, "kind": "method", "title": "方法", "summary": "主机遥测 → 权限-进程图 → 图对比学习。",
             "evidence_refs": ["图1"],
             "steps": ["遥测构图", "图对比学习", "子图打分", "输出异常路径"],
             "narration": {"script": "我们把遥测构造成权限-进程图，用图对比学习学子图嵌入，按良性上下文偏离度打分。", "subtitle": "遥测构图 + 图对比学习。"}},
            {"order": 4, "kind": "experiment", "title": "实验", "summary": "LT24 基准，5 个检测器对比。",
             "evidence_refs": ["表1"],
             "steps": ["AUC 对比", "良性精度", "可解释性研究"],
             "narration": {"script": "我们在 LT24 上与 5 个检测器对比，并做了解释质量研究。", "subtitle": "5 检测器 + 可解释性。"}},
            {"order": 5, "kind": "result", "title": "结果", "summary": "0.91 AUC，0.98 良性精度，告警 0.8s 出图解释。",
             "evidence_refs": ["表1", "表2"],
             "steps": ["最优 AUC", "最小告警体积", "0.8s 解释"],
             "narration": {"script": "NetGuard 达到 0.91 AUC 和 0.98 良性精度，每条告警都能给出子图解释，平均 0.8 秒。", "subtitle": "0.91 AUC · 0.8s 解释。"}},
            {"order": 6, "kind": "limitation", "title": "局限", "summary": "依赖主机级遥测覆盖，大规模聚合未验证。",
             "evidence_refs": ["p.8 Discussion"],
             "steps": ["遥测覆盖依赖", "多租户聚合未验证", "海量图实时聚合"],
             "narration": {"script": "局限在于依赖主机级遥测覆盖，且跨租户与大规模图的实时聚合尚未验证。", "subtitle": "遥测覆盖与规模扩展待验证。"}},
        ],
        "qa_bank": [
            {"q": "这篇论文如何应对零日攻击？", "a": "不匹配攻击签名，而是学习良性上下文的多态图嵌入，依据子图与良性上下文的偏离程度判定异常，因此对未见过的攻击模式也能感知。",
             "confidence": "High", "evidence_refs": [ev(3, "method", "section", "Method 描述基于良性上下文偏离度的无标签对比学习。", "Method p.3")]},
            {"q": "用什么数据集评测？效果如何？", "a": "用 LT24 主机遥测基准，NetGuard 达到 0.91 AUC 与 0.98 良性精度。", "confidence": "High",
             "evidence_refs": [ev(7, "table_1", "table", "Table 1 报告 0.91 AUC 与 0.98 良性精度。", "Table 1 p.7")]},
            {"q": "论文最值得质疑的地方是什么？", "a": "最值得质疑的是对主机级遥测覆盖的强依赖，以及跨租户、大规模图实时聚合尚未验证，真实大规模环境下的扩展性不清楚。",
             "confidence": "High", "evidence_refs": [ev(8, "discussion", "section", "Discussion 标明遥测覆盖与大规模聚合待验证。", "Discussion p.8")]},
            {"q": "告警可解释性如何？", "a": "每条告警附带诱导出的子图作为证据，平均 0.8s 即可完成研判，人工同意率达 88%。", "confidence": "High",
             "evidence_refs": [ev(8, "table_2", "table", "Table 2 报告 0.8s 研判时间与 88% 人工同意率。", "Table 2 p.8")]},
        ],
    }
