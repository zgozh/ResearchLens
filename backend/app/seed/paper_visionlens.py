from __future__ import annotations

from . import svgkit as sk
from .common import accent, ev, fig

# --------------------------------------------------------------------------
# Demo Paper A — Computer Vision
# "SlimSeg-Net: An Efficient Cross-Attention Network for Real-Time Medical
#  Image Segmentation"
# --------------------------------------------------------------------------
SLUG = "slimseg-net"
ACCENT = accent.indigo

# --- original method figure (programmatic pipeline) ---
METHOD_STEPS = [
    {"id": "s1", "label": "Input", "phase": "input", "detail": "CT image 512×512", "color": "#6366F1"},
    {"id": "s2", "label": "Encoder", "phase": "encoder", "detail": "Ghost-Conv downsample", "color": "#8B5CF6"},
    {"id": "s3", "label": "Cross-Attn", "phase": "module", "detail": "Spatial×channel attention", "color": "#22D3EE"},
    {"id": "s4", "label": "Decoder", "phase": "decoder", "detail": "Upsample + skip", "color": "#34D399"},
    {"id": "s5", "label": "Prediction", "phase": "output", "detail": "Binary mask", "color": "#F59E0B"},
]


def build():
    return {
        "slug": SLUG,
        "title": "SlimSeg-Net: An Efficient Cross-Attention Network for Real-Time Medical Image Segmentation",
        "subtitle": "基于跨注意力与 Ghost 卷积的高效实时医学影像分割网络",
        "authors": ["Wenhao Chen", "Yue Li", "Kai Zhou"],
        "year": 2026,
        "domain": "computer-vision",
        "accent": ACCENT,
        "tags": ["Medical Imaging", "Semantic Segmentation", "Cross-Attention", "Efficiency"],
        "abstract": (
            "Existing real-time segmentation networks trade accuracy for speed. SlimSeg-Net introduces a "
            "cross-attention gate that fuses spatial and channel context at a fraction of the parameter cost, "
            "using Ghost convolutions in the encoder to cut FLOPs. On the KP-MRI benchmark it reaches 0.894 "
            "Dice with only 2.1M parameters, surpassing larger baselines while running at 42 FPS on a "
            "consumer GPU. We further show that the attention module transfers to chest X-ray pathology masks "
            "with negligible retraining cost."
        ),
        "map": {
            "problem": "Real-time clinical deployment needs segmentation that is accurate AND lightweight; heavy attention blocks break the latency budget.",
            "method": "Ghost-Conv encoder + a Cross-Attention Gate that re-weights spatial and channel features before the decoder.",
            "dataset": "KP-MRI (multi-organ CT/MRI) and COVID-ChestX (fine-tuning), 18.4k annotated slices.",
            "experiment": "Dice / IoU / Parameters / FLOPs / FPS, compared against 6 baselines across 3 splits.",
            "result": "0.894 Dice, 2.1M params, 42 FPS — best accuracy-per-parameter among all baselines.",
            "limitation": "Attention gate tuned for 2D slices; 3D volumetric and multi-center generalization not yet validated.",
        },
        "sections": [
            {"heading": "Introduction", "kind": "intro", "page": 1,
             "summary": "Clinical demand for edge-deployable segmentation; existing backbones are either heavy or underperform."},
            {"heading": "Method", "kind": "method", "page": 3,
             "summary": "Ghost-Conv encoder with a cross-attention gate that fuses spatial and channel context."},
            {"heading": "Experiments", "kind": "experiment", "page": 6,
             "summary": "Benchmark against 6 baselines on KP-MRI and transfer to COVID-ChestX."},
            {"heading": "Results", "kind": "result", "page": 7,
             "summary": "0.894 Dice at 2.1M params and 42 FPS; ablation isolates the gate gain."},
            {"heading": "Discussion & Limitation", "kind": "discussion", "page": 8,
             "summary": "Dataset size and single-center distribution are the primary concerns; 3D generalization is open."},
        ],
        "method_steps": METHOD_STEPS,
        "figures": [
            fig(
                fig_no=1, page=3, importance="high",
                caption="Method architecture of SlimSeg-Net. Input CT is downsampled by Ghost convolutions, refined by the Cross-Attention Gate, and restored by a lightweight decoder.",
                svg=sk.pipeline(
                    "SlimSeg-Net Pipeline",
                    METHOD_STEPS,
                    tag="Fig. 1 · Original",
                ),
            ),
            fig(
                fig_no=2, page=6, importance="high",
                caption="Dice score versus parameter count on KP-MRI. SlimSeg-Net occupies the best Pareto frontier point.",
                svg=sk.scatter(
                    "Dice vs. Parameters (KP-MRI)",
                    [
                        {"x": 1.2, "y": 0.812, "label": "U-Net", "r": 5, "color": "#94A3B8"},
                        {"x": 2.1, "y": 0.894, "label": "SlimSeg-Net", "r": 7, "color": ACCENT},
                        {"x": 4.8, "y": 0.861, "label": "AttnU-Net", "r": 5, "color": "#94A3B8"},
                        {"x": 12.0, "y": 0.903, "label": "DeepLabV3+", "r": 5, "color": "#94A3B8"},
                    ],
                    tag="Fig. 2 · Pareto",
                ),
            ),
            fig(
                fig_no=3, page=6, importance="medium",
                caption="Ablation of the Cross-Attention Gate: the gate contributes the largest single accuracy gain (+1.9 Dice).",
                svg=sk.bar_chart(
                    "Ablation Study (Dice)",
                    ["Baseline", "+Ghost", "+Gate", "Full"],
                    [0.861, 0.875, 0.894, 0.894],
                    color=ACCENT,
                    tag="Fig. 3 · Ablation",
                ),
            ),
        ],
        "tables": [
            {
                "table_no": 1, "page": 7,
                "caption": "Quantitative comparison on KP-MRI (5-fold mean ± std).",
                "headers": ["Model", "Dice", "Params(M)", "FLOPs(G)", "FPS"],
                "content": [
                    ["U-Net", "0.812", "31.0", "218", "11"],
                    ["AttnU-Net", "0.861", "46.3", "302", "7"],
                    ["DeepLabV3+", "0.903", "58.6", "287", "6"],
                    ["MobileNetV3", "0.828", "4.2", "12.1", "51"],
                    ["SlimSeg-Net", "0.894", "2.1", "5.6", "42"],
                ],
            },
            {
                "table_no": 2, "page": 7,
                "caption": "Cross-dataset transfer to COVID-ChestX pathology masks.",
                "headers": ["Setting", "Dice", "IoU", "Δ vs fine-tune"],
                "content": [
                    ["Zero-shot", "0.702", "0.616", "-"],
                    ["Fine-tune (50 imgs)", "0.876", "0.811", "+0.174"],
                    ["Fine-tune (200 imgs)", "0.902", "0.844", "+0.200"],
                ],
            },
        ],
        "claims": [
            {
                "claim_id": "claim_01", "type": "RESULT", "confidence": 0.97, "statement": "SlimSeg-Net achieves 0.894 Dice on KP-MRI.",
                "evidence": [ev(7, "table_1", "table", "Table 1 reports a mean Dice of 0.894 for SlimSeg-Net.", "0.894")],
            },
            {
                "claim_id": "claim_02", "type": "METHOD", "confidence": 0.96, "statement": "The Cross-Attention Gate alone contributes +1.9 Dice over the Ghost-Conv baseline.",
                "evidence": [ev(6, "fig_3", "figure", "Ablation in Fig. 3 shows +1.9 Dice from the gate.", "Fig. 3")],
            },
            {
                "claim_id": "claim_03", "type": "RESULT", "confidence": 0.95, "statement": "SlimSeg-Net runs at 42 FPS on a consumer GPU with only 2.1M parameters.",
                "evidence": [ev(7, "table_1", "table", "Table 1 lists 2.1M parameters and 42 FPS.", "42 FPS")],
            },
            {
                "claim_id": "claim_04", "type": "CONTEXT", "confidence": 0.9, "statement": "The method transfers to chest X-ray pathology masks with 200 fine-tuning images reaching 0.902 Dice.",
                "evidence": [ev(7, "table_2", "table", "Table 2 reports 0.902 Dice after fine-tuning on 200 images.", "0.902")],
            },
            {
                "claim_id": "claim_05", "type": "LIMITATION", "confidence": 0.85, "statement": "Attention was tuned for 2D slices; 3D volumetric generalization is not yet validated.",
                "evidence": [ev(8, "discussion", "section", "Discussion notes 2D-only tuning and open 3D generalization.", "Discussion")],
            },
        ],
        "graph": {
            "nodes": [
                {"node_id": "g_problem", "kind": "problem", "label": "Problem", "props": {"text": "Accuracy vs. latency in clinical segmentation"}},
                {"node_id": "g_method", "kind": "method", "label": "Method", "props": {"text": "Ghost-Conv + Cross-Attention Gate"}},
                {"node_id": "g_dataset", "kind": "experiment", "label": "Dataset", "props": {"text": "KP-MRI + COVID-ChestX"}},
                {"node_id": "g_exp", "kind": "experiment", "label": "Experiment", "props": {"text": "6 baselines × 3 splits"}},
                {"node_id": "g_claim1", "kind": "claim", "label": "Claim 01", "props": {"text": "0.894 Dice on KP-MRI", "claim_id": "claim_01"}},
                {"node_id": "g_claim2", "kind": "claim", "label": "Claim 03", "props": {"text": "42 FPS at 2.1M params", "claim_id": "claim_03"}},
                {"node_id": "g_ev_t1", "kind": "evidence", "label": "Table 1 · p.7", "props": {"text": "Dice / Params / FLOPs / FPS"}},
                {"node_id": "g_ev_fig", "kind": "evidence", "label": "Fig. 3 · p.6", "props": {"text": "Ablation"}},
            ],
            "edges": [
                {"source": "g_problem", "target": "g_method", "label": "addresses"},
                {"source": "g_method", "target": "g_dataset", "label": "evaluated on"},
                {"source": "g_dataset", "target": "g_exp", "label": "benchmark"},
                {"source": "g_exp", "target": "g_claim1", "label": "supports"},
                {"source": "g_exp", "target": "g_claim2", "label": "supports"},
                {"source": "g_claim1", "target": "g_ev_t1", "label": "cited to"},
                {"source": "g_claim2", "target": "g_ev_t1", "label": "cited to"},
                {"source": "g_claim2", "target": "g_ev_fig", "label": "cited to"},
            ],
        },
        "presentation": [
            {"order": 1, "kind": "intro", "title": "研究背景", "summary": "临床影像分割要既能准、又要能跑到边缘设备。",
             "evidence_refs": ["图1"],
             "steps": ["临床部署要求高精度+轻量", "现有骨干要么重要么不准"],
             "narration": {"script": "临床影像分割需要在准确与速度之间取得平衡，SlimSeg-Net 的目标是在超轻量参数下保持高分割精度。", "subtitle": "临床影像分割：求准，也求快。"}},
            {"order": 2, "kind": "problem", "title": "问题", "summary": "重注意力模块让实时推理的延迟预算告吹。",
             "evidence_refs": ["p.1 Introduction"],
             "steps": ["高精度模型参数量大", "实时设备算力受限"],
             "narration": {"script": "现有方案里，堆叠注意力模块能提升精度，却往往拖垮了推理速度。", "subtitle": "重注意力 → 延迟超标。"}},
            {"order": 3, "kind": "method", "title": "方法", "summary": "Ghost 卷积编码器 + 跨注意力门控。",
             "evidence_refs": ["图1"],
             "steps": ["Input 512×512", "Ghost-Conv 下采样", "Spatial×Channel 跨注意力", "轻量解码器", "输出掩码"],
             "narration": {"script": "方法核心是用 Ghost 卷积压缩编码器，并用跨注意力门控在解码前融合空间与通道信息。", "subtitle": "Ghost 编码器 + 跨注意力门控。"}},
            {"order": 4, "kind": "experiment", "title": "实验", "summary": "KP-MRI 基准 + 迁移到 COVID-ChestX。",
             "evidence_refs": ["表1", "表2"],
             "steps": ["6 个基线", "3 个数据划分", "消融实验"],
             "narration": {"script": "我们在 KP-MRI 上与 6 个基线对比，并把它迁移到胸部 X 光病理掩码。", "subtitle": "6 基线 + 跨数据集迁移。"}},
            {"order": 5, "kind": "result", "title": "结果", "summary": "0.894 Dice，2.1M 参数，42 FPS。",
             "evidence_refs": ["表1", "图2"],
             "steps": ["最佳精度-参数比", "+1.9 Dice 来自注意力门控"],
             "narration": {"script": "在 2.1M 参数下达到 0.894 Dice 与 42 FPS，是所有基线里精度-参数比最优的。", "subtitle": "0.894 Dice · 2.1M · 42 FPS。"}},
            {"order": 6, "kind": "limitation", "title": "局限", "summary": "仅二维切片验证，三维与多中心推广待验证。",
             "evidence_refs": ["p.8 Discussion"],
             "steps": ["二维切片调参", "三维体数据待验证", "单中心分布"],
             "narration": {"script": "需要强调的局限是注意力针对二维切片调参，三维体数据与多中心泛化尚未验证。", "subtitle": "2D 调参，3D 待验证。"}},
        ],
        "qa_bank": [
            {"q": "这篇论文哪里最值得质疑？", "a": "最值得质疑的是结论的泛化性：注意力针对二维切片调参，且只在单中心数据集上验证，三维体数据与多中心推广尚未证实。",
             "confidence": "High", "evidence_refs": [ev(8, "discussion", "section", "Discussion 明确标注 2D-only 调参与开放的多中心/三维问题。", "Discussion p.8")]},
            {"q": "方法在什么数据集上评测？", "a": "在 KP-MRI 上评测，并迁移到 COVID-ChestX 做跨数据集验证。", "confidence": "High",
             "evidence_refs": [ev(6, "experiments", "section", "Experiments 章节点明 KP-MRI 与 COVID-ChestX。", "Experiments p.6")]},
            {"q": "模型参数和速度如何？", "a": "2.1M 参数、5.6G FLOPs、42 FPS。", "confidence": "High",
             "evidence_refs": [ev(7, "table_1", "table", "Table 1 列出 2.1M params / 42 FPS。", "Table 1 p.7")]},
            {"q": "本篇论文的主要贡献是什么？", "a": "提出 SlimSeg-Net：用 Ghost 卷积大幅压缩编码器，并以跨注意力门控在解码前融合空间与通道上下文，从而在超轻量下保持高分割精度。", "confidence": "High",
             "evidence_refs": [ev(3, "method", "section", "Method 章节描述 Ghost-Conv + Cross-Attention Gate。", "Method p.3")]},
        ],
    }
