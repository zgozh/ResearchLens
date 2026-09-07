from __future__ import annotations

from . import svgkit as sk
from .common import accent, ev, fig

SLUG = "slimseg-net"
ACCENT = accent.indigo

METHOD_STEPS = [
    {"id": "s1", "label": "输入图像", "phase": "input", "detail": "512×512 CT 切片", "color": "#6366F1"},
    {"id": "s2", "label": "Ghost 编码器", "phase": "encoder", "detail": "Ghost 卷积下采样，压低参数量", "color": "#8B5CF6"},
    {"id": "s3", "label": "跨注意力门控", "phase": "module", "detail": "空间×通道跨注意力融合", "color": "#22D3EE"},
    {"id": "s4", "label": "轻量解码器", "phase": "decoder", "detail": "上采样 + 跳跃连接", "color": "#34D399"},
    {"id": "s5", "label": "输出掩码", "phase": "output", "detail": "二值分割结果", "color": "#F59E0B"},
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
            "现有实时分割网络往往用精度换速度。SlimSeg-Net 引入跨注意力门控，以远低于参数代价融合空间与通道上下文中；"
            "编码器用 Ghost 卷积大幅降低 FLOPs。在 KP-MRI 基准上，SlimSeg-Net 以仅 2.1M 参数达到 0.894 Dice，"
            "在消费级 GPU 上以 42 FPS 运行，是所有基线中精度-参数比最优者。消融实验表明跨注意力门控加上 1.9 Dice。"
            "我们进一步证明该注意力模块可低成本迁移到胸部 X 光病理掩码任务。"
        ),
        "map": {
            "problem": "临床实时部署既要分割精度、又要轻量；堆叠注意力模块会拖垮延迟预算。",
            "method": "Ghost 卷积编码器 + 跨注意力门控（解码前融合空间与通道上下文）。",
            "dataset": "KP-MRI（多器官 CT/MRI）与 COVID-ChestX（迁移微调），共 1.84 万张标注切片。",
            "experiment": "以 Dice / IoU / 参数量 / FLOPs / FPS 对比 6 个基线，跨 3 个数据划分。",
            "result": "在 2.1M 参数、5.6G FLOPs 下达到 0.894 Dice、42 FPS，精度-参数比最优。",
            "limitation": "注意力针对 2D 切片调参；3D 体数据与多中心泛化尚未验证。",
        },
        "sections": [
            {"heading": "Introduction", "kind": "intro", "page": 1,
             "summary": "临床对可部署于边缘的分割模型需求强烈；现有骨干要么重、要么精度不足。",
             "body": (
                 "医学影像分割是临床诊断与手术规划的基础，但把高精度模型部署到床边或边缘设备始终面临算力瓶颈。"
                 "现有方法或使用很深的骨干网络追求精度，或在资源受限场景大幅牺牲精度。"
                 "如何在不牺牲精度的前提下把模型做到足够轻量，是实时医疗影像分割的核心矛盾。"
             ),
             "key_points": ["高精度模型参数量大、部署难", "轻量模型又往往精读不足", "需要精度-轻量的平衡点"]},
            {"heading": "Method", "kind": "method", "page": 3,
             "summary": "用 Ghost 卷积压缩编码器，并在解码前用跨注意力门控融合空间与通道信息。",
             "body": (
                 "SlimSeg-Net 由三部分组成。编码器用 Ghost 卷积生成冗余特征图，从而在不显著增加参数的前提下保留表达能力。"
                 "核心是跨注意力门控：它分别从空间与通道两个维度计算注意力，再把二者相乘融合，在解码前对有用区域加权，"
                 "抑制无关背景。最后是一个轻量解码器，通过上采样与跳跃连接恢复空间分辨率并输出二值掩码。"
             ),
             "key_points": ["Ghost 卷积压缩参数但保留表达", "空间×通道跨注意力加权", "轻量解码器恢复分辨率"]},
            {"heading": "Experiments", "kind": "experiment", "page": 6,
             "summary": "在 KP-MRI 基准上对比 6 个基线，并迁移到 COVID-ChestX 验证跨数据集能力。",
             "body": (
                 "我们在 KP-MRI 基准上与其他 6 个基线对比，覆盖 Dice、IoU、参数量、FLOPs、FPS 五类指标，"
                 "并在 3 个数据划分上重复实验取均值与标准差。为验证通用性，我们把训练好的模型迁移到 "
                 "COVID-ChestX 胸部 X 光病理掩码任务，对比零样本与少量微调的效果。"
             ),
             "key_points": ["6 基线 × 3 数据划分", "五类指标对比", "跨数据集迁移测试"]},
            {"heading": "Results", "kind": "result", "page": 7,
             "summary": "2.1M 参数下 0.894 Dice、42 FPS，精度-参数比最优；消融显示门控贡献 +1.9 Dice。",
             "body": (
                 "在 KP-MRI 上，SlimSeg-Net 以 2.1M 参数、5.6G FLOPs 达到 0.894 Dice，并在消费级 GPU 上跑到 42 FPS。"
                 "与 DeepLabV3+ 相比精度接近但参数量仅为其 1/28；与 MobileNetV3 相比速度接近但精度高出 6.6 个百分点。"
                 "消融实验表明，仅跨注意力门控一项就带来 1.9 个点的 Dice 提升，是最大的单点贡献。"
             ),
             "key_points": ["0.894 Dice @ 2.1M 参数", "42 FPS 消费级 GPU", "门控贡献 +1.9 Dice"]},
            {"heading": "Discussion & Limitations", "kind": "discussion", "page": 8,
             "summary": "注意力针对二维切片调参，仅在单中心数据集验证；三维与多中心推广有待研究。",
             "body": (
                 "需要诚实说明局限性：跨注意力门控是针对二维切片调参的，我们对三维体数据与多中心分布尚未验证其泛化。"
                 "此外，当前 A100 与消费级 GPU 上的速度结果依赖具体软硬件环境。"
                 "未来工作将把门控扩展到 3D 卷积，并在多中心数据上验证稳定性。"
             ),
             "key_points": ["仅 2D 切片调参", "单中心数据集验证", "3D 与多中心推广待研究"]},
        ],
        "method_steps": METHOD_STEPS,
        "figures": [
            fig(1, 3, "SlimSeg-Net 整体架构：输入 CT 经 Ghost 卷积下采样，在解码前由跨注意力门控细化，再由轻量解码器恢复掩码。",
                sk.pipeline("SlimSeg-Net 流水线", METHOD_STEPS, tag="图 1 · 原创"),
                "high", description="方法总览图：五步流水线，突出跨注意力门控为创新核心。"),
            fig(2, 6, "KP-MRI 上 Dice 与参数量的帕累托图。SlimSeg-Net 占据最优的精度-参数比点。",
                sk.scatter("Dice vs 参数量 (KP-MRI)", [
                    {"x": 1.2, "y": 0.812, "label": "U-Net", "r": 5, "color": "#94A3B8"},
                    {"x": 2.1, "y": 0.894, "label": "SlimSeg-Net", "r": 7, "color": ACCENT},
                    {"x": 4.8, "y": 0.861, "label": "AttnU-Net", "r": 5, "color": "#94A3B8"},
                    {"x": 12.0, "y": 0.903, "label": "DeepLabV3+", "r": 5, "color": "#94A3B8"},
                ], tag="图 2 · 帕累托"), "high", description="显示 SlimSeg-Net 在精度/参数权衡上优于更大模型。"),
            fig(3, 7, "跨注意力门控的消融实验：门控带来最大的单点精度增益（+1.9 Dice）。",
                sk.bar_chart("消融实验 (Dice)", ["Baseline", "+Ghost", "+Gate", "Full"],
                             [0.861, 0.875, 0.894, 0.894], color=ACCENT, tag="图 3 · 消融"),
                "high", description="把门控去掉后精度明显下降，证明其重要性。"),
            fig(4, 7, "训练过程中 Dice 随迭代的变化。Ghost 编码器保持稳定收敛。",
                sk.line_chart("训练曲线 (Dice)",
                              [{"name": "SlimSeg-Net", "color": ACCENT,
                                "points": [{"x": 0, "y": 0.42}, {"x": 10, "y": 0.72}, {"x": 20, "y": 0.83}, {"x": 30, "y": 0.894}]}],
                              x_labels=["0k", "10k", "20k", "30k"], tag="图 4 · 训练"), "medium", description="收敛稳定。"),
        ],
        "tables": [
            {"table_no": 1, "page": 7,
             "caption": "KP-MRI 上 5 折均值±标准差对比。",
             "content": [["Model", "Dice", "Params(M)", "FLOPs(G)", "FPS"],
                         ["U-Net", "0.812", "31.0", "218", "11"],
                         ["AttnU-Net", "0.861", "46.3", "302", "7"],
                         ["DeepLabV3+", "0.903", "58.6", "287", "6"],
                         ["MobileNetV3", "0.828", "4.2", "12.1", "51"],
                         ["SlimSeg-Net", "0.894", "2.1", "5.6", "42"]],
             "key_finding": "SlimSeg-Net 用 1/28 的参数量取得接近 DeepLabV3+ 的精度，速度远超它。"},
            {"table_no": 2, "page": 7,
             "caption": "跨数据集迁移到 COVID-ChestX 病理掩码。",
             "content": [["Setting", "Dice", "IoU"],
                         ["Zero-shot", "0.702", "0.616"],
                         ["Fine-tune (50 imgs)", "0.876", "0.811"],
                         ["Fine-tune (200 imgs)", "0.902", "0.844"]],
             "key_finding": "仅 200 张迁移样本即可达到 0.902 Dice，体现注意力模块的可迁移性。"},
            {"table_no": 3, "page": 7,
             "caption": "跨注意力门控消融（KP-MRI）。",
             "content": [["Variant", "Dice", "Params(M)"],
                         ["Baseline", "0.861", "1.8"],
                         ["+ Ghost", "0.875", "1.9"],
                         ["+ Gate (Full)", "0.894", "2.1"]],
             "key_finding": "跨注意力门控贡献 +1.9 Dice，同时仅增加 0.2M 参数。"},
        ],
        "claims": [
            {"claim_id": "claim_01", "type": "RESULT", "confidence": 0.97, "rationale": "表 1 直接给出 SlimSeg-Net 的 Dice 值。",
             "statement": "SlimSeg-Net 在 KP-MRI 上达到 0.894 Dice。",
             "evidence": [ev(7, "table_1", "table", "表 1 报告 SlimSeg-Net 的 Dice 为 0.894。", "0.894")]},
            {"claim_id": "claim_02", "type": "METHOD", "confidence": 0.96, "rationale": "消融图显示门控带来最大增益。",
             "statement": "跨注意力门控单独贡献 +1.9 Dice。",
             "evidence": [ev(7, "fig_3", "figure", "图 3 消融显示加入门控后 Dice 从 0.875 提升到 0.894。", "+1.9 Dice")]},
            {"claim_id": "claim_03", "type": "RESULT", "confidence": 0.95, "rationale": "表 1 与正文给出参数量与 FPS。",
             "statement": "SlimSeg-Net 仅 2.1M 参数，以 42 FPS 运行。",
             "evidence": [ev(7, "table_1", "table", "表 1 列出 2.1M 参数与 42 FPS。", "42 FPS")]},
            {"claim_id": "claim_04", "type": "RESULT", "confidence": 0.93, "rationale": "与 DeepLabV3+/MobileNetV3 对比。",
             "statement": "SlimSeg-Net 以 1/28 的参数量取得接近 DeepLabV3+ 的精度。",
             "evidence": [ev(7, "table_1", "table", "表 1 显示 DeepLabV3+ 参数 58.6M、SlimSeg-Net 2.1M。", "1/28 参数量")]},
            {"claim_id": "claim_05", "type": "CONTEXT", "confidence": 0.9, "rationale": "表 2 显示迁移结果。",
             "statement": "方法可低成本迁移到胸部 X 光病理掩码，200 张样本即达 0.902 Dice。",
             "evidence": [ev(7, "table_2", "table", "表 2 报告微调 200 张后 Dice 0.902。", "0.902")]},
            {"claim_id": "claim_06", "type": "METHOD", "confidence": 0.94, "rationale": "方法章节描述 Ghost 卷积作用。",
             "statement": "Ghost 卷积在编码器中降低 FLOPs 且保留表达能力。",
             "evidence": [ev(3, "method", "section", "方法章节说明 Ghost 卷积生成冗余特征图以减参。", "Ghost 卷积")]},
            {"claim_id": "claim_07", "type": "RESULT", "confidence": 0.92, "rationale": "消融表 3。",
             "statement": "在 Baseline 基础上加入 Ghost 卷积提升 1.4 点 Dice。",
             "evidence": [ev(7, "table_3", "table", "表 3 显示 Baseline 0.861 → +Ghost 0.875。", "+1.4")]},
            {"claim_id": "claim_08", "type": "LIMITATION", "confidence": 0.85, "rationale": "讨论章节。",
             "statement": "注意力针对 2D 切片调参，3D 体数据泛化未验证。",
             "evidence": [ev(8, "discussion", "section", "讨论明确指出仅 2D 切片调参、3D 待验证。", "2D 切片调参")]},
            {"claim_id": "claim_09", "type": "LIMITATION", "confidence": 0.84, "rationale": "讨论章节。",
             "statement": "仅在单中心数据集验证，多中心推广有待研究。",
             "evidence": [ev(8, "discussion", "section", "讨论标明单中心验证、多中心待研究。", "单中心")]},
            {"claim_id": "claim_10", "type": "EXPERIMENT", "confidence": 0.91, "rationale": "实验章节。",
             "statement": "方法在 6 个基线、3 个数据划分上评测，覆盖五类指标。",
             "evidence": [ev(6, "experiments", "section", "实验章节说明 6 基线 × 3 划分。", "实验结果")]},
        ],
        "graph": {
            "nodes": [
                {"node_id": "g_problem", "kind": "problem", "label": "问题", "props": {"text": "临床分割要精度也要轻量"}},
                {"node_id": "g_method", "kind": "method", "label": "方法", "props": {"text": "Ghost 卷积 + 跨注意力门控"}},
                {"node_id": "g_dataset", "kind": "experiment", "label": "数据集", "props": {"text": "KP-MRI + COVID-ChestX"}},
                {"node_id": "g_exp", "kind": "experiment", "label": "实验", "props": {"text": "6 基线 × 3 划分"}},
                {"node_id": "g_claim1", "kind": "claim", "label": "断言 01", "props": {"text": "0.894 Dice on KP-MRI", "claim_id": "claim_01"}},
                {"node_id": "g_claim2", "kind": "claim", "label": "断言 03", "props": {"text": "42 FPS @ 2.1M 参数", "claim_id": "claim_03"}},
                {"node_id": "g_claim3", "kind": "claim", "label": "断言 06", "props": {"text": "门控贡献 +1.9 Dice", "claim_id": "claim_06"}},
                {"node_id": "g_ev_t1", "kind": "evidence", "label": "表 1 · p.7", "props": {"text": "Dice/参数/FLOPs/FPS"}},
                {"node_id": "g_ev_fig", "kind": "evidence", "label": "图 3 · p.7", "props": {"text": "消融"}},
            ],
            "edges": [
                {"source": "g_problem", "target": "g_method", "label": "针对"},
                {"source": "g_method", "target": "g_dataset", "label": "评测于"},
                {"source": "g_dataset", "target": "g_exp", "label": "基准"},
                {"source": "g_exp", "target": "g_claim1", "label": "支持"},
                {"source": "g_exp", "target": "g_claim2", "label": "支持"},
                {"source": "g_claim1", "target": "g_ev_t1", "label": "引用"},
                {"source": "g_claim2", "target": "g_ev_t1", "label": "引用"},
                {"source": "g_claim3", "target": "g_ev_fig", "label": "引用"},
            ],
        },
        "presentation": [
            {"order": 1, "kind": "intro", "title": "研究背景", "summary": "临床影像分割既要准、又要能部署到边缘设备。",
             "steps": [{"label": "高精度模型部署难", "detail": "深层骨干参数量大"}, {"label": "轻量模型精度不足", "detail": "牺牲精度换速度"}],
             "evidence_refs": ["p.1"],
             "figure_refs": [],
             "narration": {"script": "临床影像分割需要在准确与速度之间取得平衡。现有方法要么用很深的骨干换来精度，要么在边缘场景大幅牺牲精度，我们希望在两者之间找到更好的平衡点。",
                           "subtitle": "临床分割：求准，也求快。"}},
            {"order": 2, "kind": "problem", "title": "问题", "summary": "堆叠注意力模块虽然能提升精度，却往往拖垮实时推理。",
             "steps": [{"label": "注意力模块重", "detail": "计算与内存开销大"}, {"label": "实时预算告吹", "detail": "延迟超标"}],
             "evidence_refs": ["p.1 Introduction"],
             "figure_refs": [],
             "narration": {"script": "更棘手的是，很多能涨点的方法靠堆叠注意力模块，这会让参数量和延迟一起飙升，恰恰不适合实时临床。",
                           "subtitle": "重注意力 → 延迟超标。"}},
            {"order": 3, "kind": "method", "title": "方法", "summary": "Ghost 卷积编码器 + 跨注意力门控 + 轻量解码器。",
             "steps": [{"label": "输入图像", "detail": "512×512 CT"}, {"label": "Ghost 编码器", "detail": "减参不失表达"}, {"label": "跨注意力门控", "detail": "空间×通道融合"}, {"label": "轻量解码器", "detail": "恢复分辨率"}, {"label": "输出掩码", "detail": "二值分割"}],
             "evidence_refs": ["图 1"],
             "figure_refs": [1],
             "narration": {"script": "方法的创新核心是跨注意力门控：在解码前，分别从空间和通道两个维度计算注意力并相乘，加权到真正有用的区域，而编码器用 Ghost 卷积把参数量压下来，从而做到又准又轻。",
                           "subtitle": "Ghost 编码器 + 跨注意力门控。"}},
            {"order": 4, "kind": "experiment", "title": "实验", "summary": "KP-MRI 基准 + 跨数据集迁移到 COVID-ChestX。",
             "steps": [{"label": "6 个基线", "detail": "覆盖主流通用分割"}, {"label": "3 个数据划分", "detail": "取均值±标准差"}, {"label": "五类指标", "detail": "Dice/IoU/参数/FLOPs/FPS"}],
             "evidence_refs": ["表 1", "表 2"],
             "figure_refs": [2],
             "narration": {"script": "我们在 KP-MRI 上与 6 个基线在 3 个数据划分上对比五类指标，并把它迁移到胸部 X 光病理掩码，验证跨数据集能力。",
                           "subtitle": "6 基线 + 跨数据集迁移。"}},
            {"order": 5, "kind": "result", "title": "结果", "summary": "0.894 Dice、2.1M 参数、42 FPS；门控贡献 +1.9 Dice。",
             "steps": [{"label": "最优精度-参数比", "detail": "1/28 参数接近 DeepLabV3+"}, {"label": "42 FPS", "detail": "消费级 GPU"}, {"label": "+1.9 Dice", "detail": "来自跨注意力门控"}],
             "evidence_refs": ["表 1", "图 3"],
             "figure_refs": [3],
             "narration": {"script": "结果非常直观：在 2.1M 参数下拿到 0.894 Dice 和 42 FPS，是所有基线里精度-参数比最优的；消融也证明，这一大块提升几乎都来自跨注意力门控。",
                           "subtitle": "0.894 Dice · 2.1M · 42 FPS。"}},
            {"order": 6, "kind": "limitation", "title": "局限", "summary": "仅二维切片与单中心验证；三维与多中心推广待研究。",
             "steps": [{"label": "2D 切片调参", "detail": "3D 泛化未验证"}, {"label": "单中心", "detail": "多中心待研究"}, {"label": "硬件依赖", "detail": "速度随环境变化"}],
             "evidence_refs": ["p.8 Discussion"],
             "figure_refs": [],
             "narration": {"script": "需要客观地说局限性：门控是针对二维切片调参的，也只在单中心验证，三维体数据与多中心推广还没有做，这些是我们的下一步方向。",
                           "subtitle": "2D 调参，3D 待验证。"}},
        ],
        "qa_bank": [
            {"q": "这篇论文哪里最值得质疑？", "a": "最值得质疑的是结论的泛化性：跨注意力门控针对二维切片调参，且只在单中心数据集验证，三维体数据与多中心推广尚未证实。",
             "confidence": "High", "evidence_refs": [ev(8, "discussion", "section", "讨论明确标注 2D 调参、单中心、多中心待研究。", "Discussion p.8")]},
            {"q": "方法在什么数据集上评测？", "a": "在 KP-MRI 上评测，并迁移到 COVID-ChestX 做跨数据集验证。", "confidence": "High",
             "evidence_refs": [ev(6, "experiments", "section", "实验章节点明 KP-MRI 与 COVID-ChestX。", "Experiments p.6")]},
            {"q": "模型参数与速度如何？", "a": "2.1M 参数、5.6G FLOPs、42 FPS。", "confidence": "High",
             "evidence_refs": [ev(7, "table_1", "table", "表 1 列出 2.1M params / 42 FPS。", "Table 1 p.7")]},
            {"q": "本篇论文的主要贡献是什么？", "a": "提出 SlimSeg-Net：用 Ghost 卷积大幅压缩编码器，并以跨注意力门控在解码前融合空间与通道上下文，从而在超轻量下保持高分割精度。", "confidence": "High",
             "evidence_refs": [ev(3, "method", "section", "方法章节描述 Ghost-Conv + Cross-Attention Gate。", "Method p.3")]},
            {"q": "跨注意力门控到底提升了多少？", "a": "在消融中，加上门控让 Dice 从 0.875 提升到 0.894，即 +1.9 Dice。", "confidence": "High",
             "evidence_refs": [ev(7, "table_3", "table", "表 3 显示 +Ghost 0.875 → Full 0.894。", "Table 3 p.7")]},
        ],
    }
