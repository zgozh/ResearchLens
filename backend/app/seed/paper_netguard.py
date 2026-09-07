from __future__ import annotations

from . import svgkit as sk
from .common import accent, ev, fig

SLUG = "netguard"
ACCENT = accent.cyan

METHOD_STEPS = [
    {"id": "s1", "label": "主机遥测", "phase": "input", "detail": "主机事件 / 告警日志", "color": "#22D3EE"},
    {"id": "s2", "label": "图构建", "phase": "encoder", "detail": "权限-进程图", "color": "#8B5CF6"},
    {"id": "s3", "label": "图对比学习", "phase": "module", "detail": "无标签子图嵌入", "color": "#6366F1"},
    {"id": "s4", "label": "异常打分", "phase": "decoder", "detail": "偏离良性上下文", "color": "#FB7185"},
    {"id": "s5", "label": "告警", "phase": "output", "detail": "可疑路径排序", "color": "#F59E0B"},
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
            "基于签名的终端检测对未知（零日）横向移动几乎无感知。NetGuard 把主机遥测建模为权限-进程图，"
            "在无攻击标签的情况下学习对比子图嵌入，依据子图与良性上下文的偏离程度判定异常，而不是匹配已知签名。"
            "在 LT24 基准上 NetGuard 达到 0.91 AUC，同时保持 0.98 的良性精度，并可用诱导子图解释每条告警，"
            "将分析师研判时间降到平均 0.8 秒。"
        ),
        "map": {
            "problem": "EDR 依赖已知签名，对零日横向移动无感知，且告警缺乏可解释证据。",
            "method": "主机遥测→权限-进程图，图对比学习学子图嵌入，按良性上下文偏离度判异常。",
            "dataset": "LT24 主机遥测基准（820 万事件、490 台主机，含注入的 74 条攻击链）。",
            "experiment": "AUC / 良性精度 / 告警体积 / 可解释性，对比 5 个检测器。",
            "result": "0.91 AUC、0.98 良性精度、单条告警平均 0.8s 出图解释，优于全部基线。",
            "limitation": "依赖主机级遥测覆盖；跨租户与大规模图实时聚合的扩展性未验证。",
        },
        "sections": [
            {"heading": "Introduction", "kind": "intro", "page": 1,
             "summary": "签名型 EDR 无法泛化到零日攻击；横向移动表现为权限提升序列，而攻击标签极度稀缺。",
             "body": (
                 "企业环境的横向移动是攻破内网的关键一步，攻击者往往通过一次登录、一次提权，在主机之间不断跳转。"
                 "传统终端检测依赖已知签名，对从未见过的零日路径几乎无感知。"
                 "更棘手的是，虽然能采集到海量主机遥测，真正的攻击路径标签却非常稀缺。"
             ),
             "key_points": ["横向移动=权限提升序列", "签名检测对零日失效", "攻击标签极度稀缺"]},
            {"heading": "Background & Threat Model", "kind": "intro", "page": 2,
             "summary": "我们把横向移动定义为权限-进程图上的异常子图；攻击标签稀缺使监督学习不可行。",
             "body": (
                 "我们把每个主机的事件流构造成一张权限-进程图，节点是主体与进程，边表示权限授予与进程调用。"
                 "一次正常登录和一次可疑提权，在该图上会呈现不同的局部结构。"
                 "由于我们几乎拿不到带标签的攻击样例，方法必须能在无监督或自监督条件下工作。"
             ),
             "key_points": ["权限-进程图建模", "可疑链接=异常子图", "无监督条件"]},
            {"heading": "Method", "kind": "method", "page": 3,
             "summary": "图构建 + 图对比学习子图嵌入 + 按良性上下文偏离度打分。",
             "body": (
                 "NetGuard 分三步。首先把遥测构造成权限-进程图；接着用图对比学习训练子图嵌入，"
                 "让良性子图与其增广版本在嵌入空间拉近，而异常子图远近；"
                 "最后在推理时，把候选子图的嵌入与良性上下文比较，按偏离程度给出异常分数，从而无需攻击标签即可排序。"
             ),
             "key_points": ["遥测构图", "图对比学子图嵌入", "良性上下文偏离度打分"]},
            {"heading": "Experiments", "kind": "experiment", "page": 6,
             "summary": "LT24 基准 + 5 个检测器 + 可解释性研究。",
             "body": (
                 "我们在 LT24 主机遥测基准上与 5 个检测器对比，报告 AUC、良性精度、每日告警量与可解释性。"
                 "同时做一个可解释性研究：让安全专家判断每条告警的诱导子图是否合理，记录平均研判时间与人工同意率。"
             ),
             "key_points": ["5 个检测器", "AUC/良性精度/告警量", "可解释性研究"]},
            {"heading": "Results", "kind": "result", "page": 7,
             "summary": "0.91 AUC、0.98 良性精度、每日仅 23 条告警，0.8s 出图解释，88% 人工同意率。",
             "body": (
                 "NetGuard 在 LT24 上取得 0.91 AUC，以 0.95 召回水平保持 0.98 的良性精度，且每日只产生约 23 条告警，"
                 "远低于基线。得益于每条告警都附带诱导子图，平均研判时间降到 0.8 秒，人工同意率达 88%。"
                 "对比之下，多数基线只会输出无法解释的纯文本告警。"
             ),
             "key_points": ["0.91 AUC / 0.98 良性精度", "每日 23 条告警", "0.8s 出图解释，88% 同意"]},
            {"heading": "Discussion", "kind": "discussion", "page": 8,
             "summary": "依赖主机级遥测覆盖；跨租户与大规模图实时聚合未验证。",
             "body": (
                 "需要说明局限：检测效果依赖主机遥测的覆盖深度，一旦某个主机没有完整采集事件，该主机上的路径就不可见。"
                 "此外，跨租户场景下的大量图如何实时聚合打分，我们尚未验证其在超大规模下的扩展性。"
                 "若能引入端侧与云端协同的图增量更新，将有助于缓解这一瓶颈。"
             ),
             "key_points": ["依赖遥测覆盖", "跨租户聚合未验证", "大规模实时打分待研究"]},
        ],
        "method_steps": METHOD_STEPS,
        "figures": [
            fig(1, 3, "NetGuard 检测流水线：主机遥测成为权限-进程图，图对比学习得到子图嵌入，按良性上下文偏离度打分。",
                sk.pipeline("NetGuard 检测流水线", METHOD_STEPS, tag="图 1 · 原创"), "high",
                description="系统总览，突出无标签对比学习。"),
            fig(2, 7, "LT24 上的 ROC 曲线。NetGuard（青色）以 0.91 AUC 领先所有基线。",
                sk.line_chart("ROC — LT24", [
                    {"name": "NetGuard", "color": ACCENT, "points": [{"x": 0, "y": 0.0}, {"x": 1, "y": 0.35}, {"x": 2, "y": 0.72}, {"x": 3, "y": 0.91}]},
                    {"name": "E-GraphSAGE", "color": "#94A3B8", "points": [{"x": 0, "y": 0.0}, {"x": 1, "y": 0.28}, {"x": 2, "y": 0.55}, {"x": 3, "y": 0.77}]},
                    {"name": "SIGMA", "color": "#64748B", "points": [{"x": 0, "y": 0.0}, {"x": 1, "y": 0.2}, {"x": 2, "y": 0.42}, {"x": 3, "y": 0.61}]},
                ], x_labels=["0%", "10%", "30%", "50%"], tag="图 2 · ROC"), "high", description="AUC 对比。"),
            fig(3, 7, "0.95 召回下的良性精度：NetGuard 保持 0.98 且告警体积最小。",
                sk.bar_chart("0.95 召回下的良性精度", ["SIGMA", "E-GraphSAGE", "IRIS", "NetGuard"], [0.72, 0.85, 0.90, 0.98], color=ACCENT, tag="图 3"),
                "high", description="低误报 + 低告警体积。"),
            fig(4, 8, "可解释性：平均研判时间对比，NetGuard 显著更短。",
                sk.bar_chart("平均研判时间 (秒)", ["SIGMA", "E-GraphSAGE", "NetGuard"], [42, 55, 0.8], color=ACCENT, tag="图 4 · 研判"),
                "medium", description="子图解释显著缩短研判。"),
        ],
        "tables": [
            {"table_no": 1, "page": 7,
             "caption": "LT24 上的检测性能。",
             "content": [["Detector", "AUC", "Benign Prec.", "Alerts/day", "Explain"],
                         ["SIGMA", "0.61", "0.72", "412", "plain"],
                         ["IRIS", "0.84", "0.90", "188", "partial"],
                         ["E-GraphSAGE", "0.77", "0.85", "231", "no"],
                         ["NetGuard", "0.91", "0.98", "23", "subgraph"]],
             "key_finding": "NetGuard 在 AUC、良性精度、告警量与可解释性上全面领先。"},
            {"table_no": 2, "page": 8,
             "caption": "解释质量（越低越好）：平均子图规模与研判时间。",
             "content": [["Method", "Avg. nodes", "Triage (s)", "Human agree %"],
                         ["SIGMA", "—", "42", "61"],
                         ["E-GraphSAGE", "—", "55", "54"],
                         ["NetGuard", "11", "0.8", "88"]],
             "key_finding": "NetGuard 平均 0.8 秒、88% 人工同意率。"},
        ],
        "claims": [
            {"claim_id": "claim_01", "type": "RESULT", "confidence": 0.96, "rationale": "表 1 给出 AUC。",
             "statement": "NetGuard 在 LT24 上达到 0.91 AUC。", "evidence": [ev(7, "table_1", "table", "表 1 报告 AUC 0.91。", "0.91")]},
            {"claim_id": "claim_02", "type": "RESULT", "confidence": 0.95, "rationale": "表 1 良性精度列。",
             "statement": "NetGuard 保持 0.98 的良性精度。", "evidence": [ev(7, "table_1", "table", "表 1 良性精度 0.98。", "0.98")]},
            {"claim_id": "claim_03", "type": "METHOD", "confidence": 0.95, "rationale": "方法章节。",
             "statement": "在没有攻击标签的情况下，用图对比学习与良性上下文偏离度检测异常，而不匹配签名。",
             "evidence": [ev(3, "method", "section", "方法描述无标签对比学习 + 偏离度打分。", "Method p.3")]},
            {"claim_id": "claim_04", "type": "RESULT", "confidence": 0.93, "rationale": "表 2 与结果章节。",
             "statement": "每条告警都附带诱导子图，平均研判时间 0.8 秒，人工同意率 88%。",
             "evidence": [ev(8, "table_2", "table", "表 2 列出 0.8 秒与 88%。", "0.8s / 88%")]},
            {"claim_id": "claim_05", "type": "RESULT", "confidence": 0.92, "rationale": "表 1 告警量列。",
             "statement": "NetGuard 每日仅产生约 23 条告警，远低于基线。", "evidence": [ev(7, "table_1", "table", "表 1 每日 23 条。", "23/天")]},
            {"claim_id": "claim_06", "type": "LIMITATION", "confidence": 0.86, "rationale": "讨论章节。",
             "statement": "检测依赖主机级遥测覆盖。", "evidence": [ev(8, "discussion", "section", "讨论标明依赖遥测覆盖。", "Discussion p.8")]},
            {"claim_id": "claim_07", "type": "LIMITATION", "confidence": 0.85, "rationale": "讨论章节。",
             "statement": "跨租户与大规模图的实时聚合尚未验证。", "evidence": [ev(8, "discussion", "section", "讨论指出跨租户聚合未验证。", "Discussion p.8")]},
            {"claim_id": "claim_08", "type": "EXPERIMENT", "confidence": 0.91, "rationale": "实验章节。",
             "statement": "方法在 LT24 上与 5 个检测器对比。", "evidence": [ev(6, "experiments", "section", "实验章节 5 个检测器。", "Experiments p.6")]},
        ],
        "graph": {
            "nodes": [
                {"node_id": "g_problem", "kind": "problem", "label": "问题", "props": {"text": "零日横向移动绕过签名"}},
                {"node_id": "g_method", "kind": "method", "label": "方法", "props": {"text": "图对比学习（无标签）"}},
                {"node_id": "g_dataset", "kind": "experiment", "label": "数据集", "props": {"text": "LT24 · 820 万事件"}},
                {"node_id": "g_exp", "kind": "experiment", "label": "实验", "props": {"text": "5 检测器 · LT24"}},
                {"node_id": "g_claim1", "kind": "claim", "label": "断言 01", "props": {"text": "0.91 AUC", "claim_id": "claim_01"}},
                {"node_id": "g_claim3", "kind": "claim", "label": "断言 04", "props": {"text": "0.8s 可解释告警", "claim_id": "claim_04"}},
                {"node_id": "g_ev_t1", "kind": "evidence", "label": "表 1 · p.7", "props": {"text": "AUC / 精度 / 告警"}},
                {"node_id": "g_ev_t2", "kind": "evidence", "label": "表 2 · p.8", "props": {"text": "解释质量"}},
            ],
            "edges": [
                {"source": "g_problem", "target": "g_method", "label": "针对"},
                {"source": "g_method", "target": "g_dataset", "label": "评测于"},
                {"source": "g_dataset", "target": "g_exp", "label": "基准"},
                {"source": "g_exp", "target": "g_claim1", "label": "支持"},
                {"source": "g_exp", "target": "g_claim3", "label": "支持"},
                {"source": "g_claim1", "target": "g_ev_t1", "label": "引用"},
                {"source": "g_claim3", "target": "g_ev_t2", "label": "引用"},
            ],
        },
        "presentation": [
            {"order": 1, "kind": "intro", "title": "研究背景", "summary": "签名型终端检测对未知横向移动几乎无感知。",
             "steps": [{"label": "零日攻击变化快", "detail": "签名依赖暴露滞后"}, {"label": "内网横向渗透", "detail": "登录+提权跳转"}],
             "evidence_refs": ["p.1"], "figure_refs": [],
             "narration": {"script": "企业内网的安全难点之一就是横向移动：攻击者一旦进到一台机器，就能通过提权和跳转不断扩散，而传统签名检测对从未见过的路径几乎没反应。",
                           "subtitle": "签名检测对零日乏力。"}},
            {"order": 2, "kind": "problem", "title": "问题", "summary": "攻击标签稀缺，告警难以解释。",
             "steps": [{"label": "攻击标签稀有", "detail": "监督学习不可行"}, {"label": "告警不可解释", "detail": "响应成本高"}],
             "evidence_refs": ["p.2 Threat Model"], "figure_refs": [],
             "narration": {"script": "真正难的是两件事：一来几乎拿不到带标签的攻击样例，二来传统告警只是一段文本，根本无法解释为什么报警，让分析师很头疼。",
                           "subtitle": "标签稀缺 + 不可解释。"}},
            {"order": 3, "kind": "method", "title": "方法", "summary": "遥测→权限-进程图→图对比学习→子图打分。",
             "steps": [{"label": "遥测构图", "detail": "权限-进程图"}, {"label": "图对比学习", "detail": "无标签子图嵌入"}, {"label": "子图打分", "detail": "偏离良性上下文"}, {"label": "输出告警", "detail": "可疑路径 + 子图"}],
             "evidence_refs": ["图 1"], "figure_refs": [1],
             "narration": {"script": "我们先把遥测构造成权限-进程图，再用图对比学习学出子图嵌入——让良性子图朝自己靠近、异常子图远离，最后按偏离良性上下文的程度给可疑路径打分，完全不需要攻击标签。",
                           "subtitle": "遥测构图 + 图对比学习。"}},
            {"order": 4, "kind": "experiment", "title": "实验", "summary": "LT24 基准，5 个检测器对比 + 可解释性研究。",
             "steps": [{"label": "AUC 对比", "detail": "5 检测器"}, {"label": "良性精度", "detail": "0.95 召回水平"}, {"label": "可解释性", "detail": "专家研判研究"}],
             "evidence_refs": ["表 1"], "figure_refs": [2],
             "narration": {"script": "我们在 LT24 上与 5 个检测器对比，报告 AUC、良性精度、告警量，并做了一项可解释性研究，让安全专家评估我们的子图解释。",
                           "subtitle": "5 检测器 + 可解释性。"}},
            {"order": 5, "kind": "result", "title": "结果", "summary": "0.91 AUC、0.98 良性精度、每日 23 条告警、0.8s 出图解释。",
             "steps": [{"label": "最优 AUC", "detail": "0.91"}, {"label": "最小告警体积", "detail": "每日 23 条"}, {"label": "0.8s 解释", "detail": "88% 人工同意率"}],
             "evidence_refs": ["表 1", "表 2"], "figure_refs": [4],
             "narration": {"script": "结果很能说明问题：0.91 AUC、0.98 良性精度，每天只告警大约 23 条，而且每条都带子图解释，分析师平均 0.8 秒就能研判，人工同意率达到 88%。",
                           "subtitle": "0.91 AUC · 0.8s 解释。"}},
            {"order": 6, "kind": "limitation", "title": "局限", "summary": "依赖主机级遥测覆盖；跨租户与大规模聚合未验证。",
             "steps": [{"label": "依赖遥测覆盖", "detail": "采集不全则不可见"}, {"label": "跨租户聚合", "detail": "未验证"}, {"label": "大规模实时打分", "detail": "待研究"}],
             "evidence_refs": ["p.8 Discussion"], "figure_refs": [],
             "narration": {"script": "客观局限在于，检测依赖主机遥测采集得够不够全；一旦某台主机没采集，它上面的路径就看不见。跨租户和超大规模图的实时聚合也还没验证，这些是后续方向。",
                           "subtitle": "遥测覆盖与规模扩展待验证。"}},
        ],
        "qa_bank": [
            {"q": "这篇论文如何应对零日攻击？", "a": "不依赖攻击签名，而是学习良性上下文的多态子图嵌入，按候选子图与良性上下文的偏离程度判定异常，因此对未见过的攻击模式也能感知。",
             "confidence": "High", "evidence_refs": [ev(3, "method", "section", "方法描述基于良性上下文偏离度的无标签对比学习。", "Method p.3")]},
            {"q": "用什么数据集评测？效果如何？", "a": "用 LT24 主机遥测基准，NetGuard 达到 0.91 AUC 与 0.98 良性精度，每日约 23 条告警。", "confidence": "High",
             "evidence_refs": [ev(7, "table_1", "table", "表 1 报告 0.91 AUC / 0.98 精度。", "Table 1 p.7")]},
            {"q": "论文最值得质疑的地方？", "a": "最值得质疑的是对主机级遥测覆盖的强依赖，以及跨租户、大规模图实时聚合尚未验证，真实大规模环境下的扩展性不清楚。",
             "confidence": "High", "evidence_refs": [ev(8, "discussion", "section", "讨论标明遥测覆盖与大规模聚合待验证。", "Discussion p.8")]},
            {"q": "告警的可解释性如何？", "a": "每条告警附带诱导出的子图证据，平均 0.8 秒即可完成研判，人工同意率 88%。", "confidence": "High",
             "evidence_refs": [ev(8, "table_2", "table", "表 2 报告 0.8 秒研判与 88% 同意率。", "Table 2 p.8")]},
        ],
    }
