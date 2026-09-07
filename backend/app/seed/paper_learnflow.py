from __future__ import annotations

from . import svgkit as sk
from .common import accent, ev, fig

SLUG = "learnflow"
ACCENT = accent.emerald

METHOD_STEPS = [
    {"id": "s1", "label": "作答记录", "phase": "input", "detail": "学生答题日志", "color": "#34D399"},
    {"id": "s2", "label": "错因编码", "phase": "encoder", "detail": "误解模式嵌入", "color": "#8B5CF6"},
    {"id": "s3", "label": "图谱匹配", "phase": "module", "detail": "知识图谱技能链接", "color": "#6366F1"},
    {"id": "s4", "label": "选题策略", "phase": "decoder", "detail": "期望掌握增益最大化", "color": "#22D3EE"},
    {"id": "s5", "label": "个性化路径", "phase": "output", "detail": "推荐下一题", "color": "#F59E0B"},
]


def build():
    return {
        "slug": SLUG,
        "title": "LearnFlow: A Knowledge-Graph Tutor that Personalizes Adaptive Practice from Mistake Patterns",
        "subtitle": "基于知识图谱与错因建模的自适应练习辅导系统",
        "authors": ["Jiawei Sun", "Mei Huang", "Qingyu Zhao"],
        "year": 2026,
        "domain": "education-ai",
        "accent": ACCENT,
        "tags": ["Adaptive Learning", "Knowledge Graph", "Knowledge Tracing", "Education AI"],
        "abstract": (
            "通用练习平台对所有学生推荐同一道题。LearnFlow 构建技能知识图谱，并把每位学生的错因建模为潜在误解，"
            "然后选择期望掌握增益最大的下一题。在为期 6 周的随机对照实验中，620 名本科生在 LearnFlow 下的"
            "后测掌握度提升 14.8 个百分点，离题重复下降 31%。所有推荐均可追溯回知识图谱中的相应技能。"
        ),
        "map": {
            "problem": "练习平台对所有学生给同一道题，无法针对错因做个性化。",
            "method": "技能知识图谱 + 错因(误解)嵌入 + 期望掌握增益最大化的选题策略。",
            "dataset": "6 周随机对照，620 名本科生，12.8 万条作答，覆盖 42 个技能的图谱。",
            "experiment": "后测掌握度 / 掌握增益 / 离题重复 / 学习时长，对比难度自适应基线。",
            "result": "后测掌握度 +14.8 个百分点，离题重复 −31%，推荐可追溯到图谱技能。",
            "limitation": "技能图谱为课程内先验构建，跨课程迁移与大样本长期效应未验证；自我报告动机有偏倚。",
        },
        "sections": [
            {"heading": "Introduction", "kind": "intro", "page": 1,
             "summary": "练习平台难以为不同学生做到个性化，也难以建模并追踪学生的误解。",
             "body": (
                 "自适应练习被认为能显著提升学习效率，但主流平台在推荐下一题时，往往对所有学生给出相同或仅基于难度的选择。"
                 "真正个性化的难点在于：既要追踪学生在每个技能上的掌握度，又要理解他卡在了哪个错误概念上。"
                 "现有知识追踪与知识图谱推荐各自为政，很少把两者结合。"
             ),
             "key_points": ["千人一面的练习推荐", "个性化需掌握度+错因", "知识追踪与图谱各自为政"]},
            {"heading": "Related Work", "kind": "intro", "page": 2,
             "summary": "知识追踪在时序建模，知识图谱推荐在技能依赖建模，但二者都未联合建模误解。",
             "body": (
                 "知识追踪方法用循环神经网络建模学生答题序列，预测掌握度；知识图谱推荐则利用技能之间的先验依赖来选择下一题。"
                 "前者忽略了错误的具体类型，后者忽略了个体差异。"
                 "我们提出把二者结合：在知识图谱上建模技能依赖，同时把错因作为潜在误解嵌入，从而联合建模。"
             ),
             "key_points": ["知识追踪=时序掌握度", "图谱推荐=技能依赖", "二者结合可联合建模误解"]},
            {"heading": "Method", "kind": "method", "page": 3,
             "summary": "技能知识图谱 + 错因编码器 + 期望掌握增益最大化策略。",
             "body": (
                 "LearnFlow 由三部分构成。一是一张技能知识图谱，节点是技能、边表示先验依赖；"
                 "二是错因编码器，把每次作答的错题与正确选项的差异编码为潜在误解；"
                 "三是选题策略，综合图谱技能与误解，选择期望掌握增益最大的下一题。"
                 "这样给出的推荐既能针对薄弱技能，又能针对错误概念。"
             ),
             "key_points": ["技能知识图谱", "错因(误解)嵌入", "期望掌握增益最大化"]},
            {"heading": "Study Design", "kind": "experiment", "page": 6,
             "summary": "6 周随机对照，620 名本科生，测后测与日志指标。",
             "body": (
                 "我们把 620 名本科生随机分为两组：实验组使用 LearnFlow，对照组使用难度自适应基线，连续 6 周。"
                 "主要结果是后测掌握度；次要结果包括离题重复、学习时长、技能覆盖度，以及推荐的可追溯性。"
                 "我们还做了策略消融，以拆解图谱链接与错因模型各自的贡献。"
             ),
             "key_points": ["620 人 6 周 RCT", "后测+日志指标", "策略消融"]},
            {"heading": "Results", "kind": "result", "page": 7,
             "summary": "后测掌握度 +14.8 个百分点、离题重复 −31%、技能覆盖 +14，推荐可追溯。",
             "body": (
                 "实验结果表明，LearnFlow 把后测掌握度提升 14.8 个百分点，把离题重复降低 31%，并把技能覆盖从 24/42 提升到 38/42。"
                 "消融显示，仅靠图谱链接不够，必须再加上错因模型才达到最佳效果。"
                 "更重要的是，所有推荐都能追溯回图谱上的具体技能与误解，便于向学生与教师解释。"
             ),
             "key_points": ["+14.8pp 后测掌握度", "−31% 离题重复", "推荐可追溯"]},
            {"heading": "Discussion", "kind": "discussion", "page": 8,
             "summary": "技能图谱课程内先验；跨课程迁移、长期效应与自我报告偏倚未解决。",
             "body": (
                 "局限有三：一是技能图谱基于单一课程先验构建，迁移到其它课程需要重新构建；"
                 "二是我们只观测了 6 周，长期学习效应未知；"
                 "三是动机与主观体验依赖自我报告，可能存在偏倚。"
                 "后续希望把图谱建模与课程内容解耦，并以更大样本验证长期效果。"
             ),
             "key_points": ["课程内先验图谱", "仅 6 周，长期未知", "自我报告动机偏倚"]},
        ],
        "method_steps": METHOD_STEPS,
        "figures": [
            fig(1, 3, "LearnFlow 自适应推荐环路：错因编码器把作答链接到图谱技能，策略选择下一题。",
                sk.pipeline("LearnFlow 自适应环路", METHOD_STEPS, tag="图 1 · 原创"), "high",
                description="推荐环路总览。"),
            fig(2, 6, "研究设计：620 名学生随机分配到 LearnFlow（n=310）或难度自适应对照组（n=310）6 周。",
                sk.architecture("随机对照设计 — 6 周", [
                    {"x": 40, "y": 110, "w": 200, "h": 60, "label": "前测", "color": "#94A3B8"},
                    {"x": 300, "y": 90, "w": 170, "h": 60, "label": "LearnFlow (n=310)", "color": ACCENT},
                    {"x": 300, "y": 180, "w": 170, "h": 60, "label": "对照组 (n=310)", "color": "#64748B"},
                    {"x": 540, "y": 130, "w": 150, "h": 64, "label": "后测", "color": "#22D3EE"},
                ], [
                    {"from": [240, 140], "to": [300, 120], "label": "随机"},
                    {"from": [240, 140], "to": [300, 210], "label": "随机"},
                    {"from": [470, 120], "to": [540, 150], "label": "测量"},
                    {"from": [470, 210], "to": [540, 180], "label": "测量"},
                ], tag="图 2 · 研究设计"), "high", description="RCT 结构。"),
            fig(3, 7, "按基础能力十分位划分的后测掌握度增益。增益集中在中位组。",
                sk.bar_chart("后测掌握度增益 (pp) 按基础分位", ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10"],
                             [6.0, 9.1, 12.3, 16.4, 18.7, 19.2, 16.9, 13.5, 10.2, 6.8], color=ACCENT, tag="图 3 · 增益"),
                "high", description="中位基础水平的学生获益最大。"),
            fig(4, 7, "推荐策略消融：加入错因模型后效果显著。",
                sk.bar_chart("策略消融 (后测掌握度)", ["Baseline", "+KG", "+Error", "Full LearnFlow"],
                             [0.61, 0.68, 0.73, 0.76], color=ACCENT, tag="图 4 · 消融"), "medium",
                description="错因模型是关键。"),
        ],
        "tables": [
            {"table_no": 1, "page": 7,
             "caption": "主要与次要结果（均值±标准差）。",
             "content": [["Outcome", "LearnFlow", "Control", "Δ", "p"],
                         ["Post-test mastery", "0.76", "0.61", "+0.148", "<.001"],
                         ["Off-task repetition", "0.41", "0.72", "-31%", "<.001"],
                         ["Practice time (h/wk)", "2.9", "3.4", "-0.5", ".02"],
                         ["Skill coverage", "38/42", "24/42", "+14", "<.001"]],
             "key_finding": "后测掌握度 +14.8pp、离题重复 −31%，均显著。"},
            {"table_no": 2, "page": 7,
             "caption": "推荐策略消融。",
             "content": [["Policy", "Post-test", "Off-task rep.", "Traceability"],
                         ["Difficulty-adaptive", "0.61", "0.72", "no"],
                         ["+KG link (no error)", "0.68", "0.60", "skill"],
                         ["+error model", "0.73", "0.48", "skill+misconcept"],
                         ["Full LearnFlow", "0.76", "0.41", "skill+misconcept"]],
             "key_finding": "缺一不可：图谱链接 + 错因模型共同作用最佳。"},
        ],
        "claims": [
            {"claim_id": "claim_01", "type": "RESULT", "confidence": 0.96, "rationale": "表 1。",
             "statement": "LearnFlow 把后测掌握度提升 14.8 个百分点。", "evidence": [ev(7, "table_1", "table", "表 1 显示 +0.148。", "+14.8%")]},
            {"claim_id": "claim_02", "type": "RESULT", "confidence": 0.94, "rationale": "表 1。",
             "statement": "离题重复下降 31%。", "evidence": [ev(7, "table_1", "table", "表 1 显示 −31%。", "-31%")]},
            {"claim_id": "claim_03", "type": "METHOD", "confidence": 0.95, "rationale": "方法章节。",
             "statement": "每条推荐都能追溯回知识图谱中的技能（含误解细节）。",
             "evidence": [ev(8, "table_2", "table", "表 2 显示 skill+misconcept 可追溯。", "可追溯")]},
            {"claim_id": "claim_04", "type": "LIMITATION", "confidence": 0.85, "rationale": "讨论章节。",
             "statement": "技能图谱基于单一课程先验构建，跨课程迁移未验证。",
             "evidence": [ev(8, "discussion", "section", "讨论标明课程内图谱、迁移未验证。", "Discussion p.8")]},
            {"claim_id": "claim_05", "type": "LIMITATION", "confidence": 0.84, "rationale": "讨论章节。",
             "statement": "仅 6 周实验，长期学习效应未知。", "evidence": [ev(8, "discussion", "section", "讨论指出仅 6 周、长期未知。", "仅 6 周")]},
            {"claim_id": "claim_06", "type": "METHOD", "confidence": 0.94, "rationale": "方法章节。",
             "statement": "方法是构建技能知识图谱，并把错因建模为潜在误解，再最大化期望掌握增益选题。",
             "evidence": [ev(3, "method", "section", "方法描述图谱 + 错因编码器 + 期望增益。", "Method p.3")]},
            {"claim_id": "claim_07", "type": "LIMITATION", "confidence": 0.83, "rationale": "讨论章节。",
             "statement": "动机与主观体验依赖自我报告，可能存在偏倚。", "evidence": [ev(8, "discussion", "section", "讨论提到自我报告偏倚。", "自我报告")]},
            {"claim_id": "claim_08", "type": "RESULT", "confidence": 0.92, "rationale": "表 1 技能覆盖列。",
             "statement": "技能覆盖从 24/42 提升到 38/42。", "evidence": [ev(7, "table_1", "table", "表 1 显示 38/42 vs 24/42。", "+14")]},
        ],
        "graph": {
            "nodes": [
                {"node_id": "g_problem", "kind": "problem", "label": "问题", "props": {"text": "所有人都推同一道题"}},
                {"node_id": "g_method", "kind": "method", "label": "方法", "props": {"text": "图谱 + 错因编码器 + 期望增益"}},
                {"node_id": "g_dataset", "kind": "experiment", "label": "研究", "props": {"text": "620 人 · 6 周 RCT"}},
                {"node_id": "g_exp", "kind": "experiment", "label": "实验", "props": {"text": "vs 难度自适应"}},
                {"node_id": "g_claim1", "kind": "claim", "label": "断言 01", "props": {"text": "+14.8pp 后测掌握度", "claim_id": "claim_01"}},
                {"node_id": "g_claim2", "kind": "claim", "label": "断言 02", "props": {"text": "−31% 离题重复", "claim_id": "claim_02"}},
                {"node_id": "g_ev_t1", "kind": "evidence", "label": "表 1 · p.7", "props": {"text": "主要结果"}},
                {"node_id": "g_ev_t2", "kind": "evidence", "label": "表 2 · p.7", "props": {"text": "策略消融"}},
            ],
            "edges": [
                {"source": "g_problem", "target": "g_method", "label": "针对"},
                {"source": "g_method", "target": "g_dataset", "label": "研究于"},
                {"source": "g_dataset", "target": "g_exp", "label": "设计"},
                {"source": "g_exp", "target": "g_claim1", "label": "支持"},
                {"source": "g_exp", "target": "g_claim2", "label": "支持"},
                {"source": "g_claim1", "target": "g_ev_t1", "label": "引用"},
                {"source": "g_claim1", "target": "g_ev_t2", "label": "引用"},
            ],
        },
        "presentation": [
            {"order": 1, "kind": "intro", "title": "研究背景", "summary": "练习平台对所有学生推荐同一道题。",
             "steps": [{"label": "千人一面", "detail": "相同下一题"}, {"label": "不针对错因", "detail": "忽视个体差异"}],
             "evidence_refs": ["p.1"], "figure_refs": [],
             "narration": {"script": "主流练习平台对所有学生给的是同一道下一题，最多按难度调整，很难真正做到个性化。",
                           "subtitle": "千人一面的练习。"}},
            {"order": 2, "kind": "problem", "title": "问题", "summary": "既要追踪掌握度，又要理解学生卡在哪一个错误概念。",
             "steps": [{"label": "错因隐藏", "detail": "错误类型未被建模"}, {"label": "技能依赖复杂", "detail": "先验依赖未被利用"}],
             "evidence_refs": ["p.2"], "figure_refs": [],
             "narration": {"script": "难就难在要同时知道学生掌握了没、以及他是卡在哪个错误概念上，而现有知识追踪和知识图谱推荐往往只做到其中一半。",
                           "subtitle": "掌握度 + 错因难兼顾。"}},
            {"order": 3, "kind": "method", "title": "方法", "summary": "知识图谱 + 错因编码器 + 期望掌握增益最大化。",
             "steps": [{"label": "作答记录", "detail": "答题日志"}, {"label": "错因编码", "detail": "误解嵌入"}, {"label": "图谱匹配", "detail": "技能链接"}, {"label": "选题策略", "detail": "期望增益最大化"}, {"label": "个性化路径", "detail": "推荐下一题"}],
             "evidence_refs": ["图 1"], "figure_refs": [1],
             "narration": {"script": "我们用一张技能知识图谱建模技能依赖，再用错因编码器把每次作答的差异编码成误解，最后按期望掌握增益最大化来挑下一题，做到既针对薄弱技能、又针对错误概念。",
                           "subtitle": "图谱 + 错因 + 期望增益。"}},
            {"order": 4, "kind": "experiment", "title": "实验", "summary": "620 人、6 周随机对照。",
             "steps": [{"label": "随机分组", "detail": "620 人"}, {"label": "6 周干预", "detail": "RCT"}, {"label": "后测+日志指标", "detail": "掌握度/重复/时长"}],
             "evidence_refs": ["图 2", "表 1"], "figure_refs": [2],
             "narration": {"script": "我们做了 620 人 6 周的随机对照，对比难度自适应基线，测量后测掌握度和离题重复等日志指标，还做了策略消融。",
                           "subtitle": "6 周随机对照。"}},
            {"order": 5, "kind": "result", "title": "结果", "summary": "后测掌握度 +14.8pp、离题重复 −31%、技能覆盖 +14。",
             "steps": [{"label": "后测提升", "detail": "+14.8pp"}, {"label": "重复下降", "detail": "−31%"}, {"label": "推荐可追溯", "detail": "图谱技能+误解"}],
             "evidence_refs": ["表 1", "表 2"], "figure_refs": [4],
             "narration": {"script": "结果是后测掌握度提升 14.8 个百分点，离题重复下降 31%，技能覆盖从 24/42 提升到 38/42，而且每条推荐都能追溯到具体的技能和误解。",
                           "subtitle": "+14.8pp · −31% · 可追溯。"}},
            {"order": 6, "kind": "limitation", "title": "局限", "summary": "课程内先验图谱；跨课程迁移与长期效应未验证；自我报告偏倚。",
             "steps": [{"label": "课程内图谱", "detail": "跨课程需重建"}, {"label": "仅 6 周", "detail": "长期效应未知"}, {"label": "自我报告", "detail": "动机偏倚"}],
             "evidence_refs": ["p.8 Discussion"], "figure_refs": [],
             "narration": {"script": "局限在于技能图谱基于单一课程先验构建，跨课程要重建；我们只看了 6 周，长期效果未知；动机与体验又是自我报告，可能有偏倚。",
                           "subtitle": "课程内图谱，迁移与长期待验证。"}},
        ],
        "qa_bank": [
            {"q": "这篇论文的方法核心是什么？", "a": "构建技能知识图谱并建模学生错因为潜在误解，再以期望掌握增益最大化策略选择下一题，从而既追踪掌握度又针对错因。",
             "confidence": "High", "evidence_refs": [ev(3, "method", "section", "方法描述图谱 + 错因 + 期望增益策略。", "Method p.3")]},
            {"q": "实验规模与效果如何？", "a": "620 名本科生 6 周随机对照；后测掌握度提升 14.8 个百分点，离题重复下降 31%。", "confidence": "High",
             "evidence_refs": [ev(7, "table_1", "table", "表 1 报告 +14.8pp 与 −31%。", "Table 1 p.7")]},
            {"q": "论文最值得质疑的地方？", "a": "技能图谱基于单一课程先验构建，跨课程迁移、长期效应与自我报告动机偏倚尚未验证，其外部效度值得质疑。",
             "confidence": "High", "evidence_refs": [ev(8, "discussion", "section", "讨论标明课程内图谱、迁移与自我报告偏倚。", "Discussion p.8")]},
            {"q": "与难度自适应基线相比提升多少？", "a": "后测掌握度 +0.148（14.8 个百分点），离题重复 −31%，技能覆盖从 24/42 提升到 38/42。", "confidence": "High",
             "evidence_refs": [ev(7, "table_1", "table", "表 1 对照列显示 Δ 与 p 值。", "Table 1 p.7")]},
        ],
    }
