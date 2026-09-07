from __future__ import annotations

from . import svgkit as sk
from .common import accent, ev, fig

# --------------------------------------------------------------------------
# Demo Paper C — Education AI
# "LearnFlow: A Knowledge-Graph Tutor that Personalizes Adaptive Practice from
#  Mistake Patterns"
# --------------------------------------------------------------------------
SLUG = "learnflow"
ACCENT = accent.emerald

METHOD_STEPS = [
    {"id": "s1", "label": "Attempt", "phase": "input", "detail": "Student answer log", "color": "#34D399"},
    {"id": "s2", "label": "Error Model", "phase": "encoder", "detail": "Mistake-pattern encoder", "color": "#8B5CF6"},
    {"id": "s3", "label": "KG Match", "phase": "module", "detail": "Knowledge-graph linking", "color": "#6366F1"},
    {"id": "s4", "label": "Policy", "phase": "decoder", "detail": "Adaptive next-exercise policy", "color": "#22D3EE"},
    {"id": "s5", "label": "Practice", "phase": "output", "detail": "Personalized path", "color": "#F59E0B"},
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
            "Generic practice platforms give every student the same next exercise. LearnFlow builds a "
            "knowledge graph of skills and models each learner's mistake patterns as latent misconceptions, "
            "then chooses the next exercise that maximizes expected mastery gain. In a 6-week randomized study "
            "with 620 undergraduates, LearnFlow raised post-test mastery by 14.8% and reduced off-task "
            "repetition by 31% compared with a difficulty-adaptive baseline. All recommendations are traceable "
            "to the linked skill in the knowledge graph."
        ),
        "map": {
            "problem": "练习平台对所有学生给同一道题，无法针对错因做个性化。",
            "method": "知识图谱建模技能依赖 + 错因(误解)嵌入 + 期望掌握增益最大化的选题策略。",
            "dataset": "6 周随机对照，620 名本科生，128k 作答，覆盖 42 个技能的图谱。",
            "experiment": "后测掌握度 / 掌握增益 / 离题重复 / 学习时长，对比难度自适应基线。",
            "result": "后测掌握度 +14.8%，离题重复 −31%，推荐可追溯到图谱技能。",
            "limitation": "技能图谱为课程内先验构建，跨课程迁移与大样本长期效应未验证；自我报告动机存在偏倚。",
        },
        "sections": [
            {"heading": "Introduction", "kind": "intro", "page": 1,
             "summary": "Practice platforms fail to personalize to mistakes; tracing misconceptions is hard."},
            {"heading": "Related Work", "kind": "intro", "page": 2,
             "summary": "Knowledge tracing vs. knowledge-graph recommendation; neither models misconceptions jointly."},
            {"heading": "Method", "kind": "method", "page": 3,
             "summary": "Skill KG + mistake-pattern encoder + expected mastery gain policy."},
            {"heading": "Study Design", "kind": "experiment", "page": 6,
             "summary": "6-week RCT with 620 undergraduates; outcomes measured post-test and log-based."},
            {"heading": "Results", "kind": "result", "page": 7,
             "summary": "+14.8% post-test mastery, −31% off-task repetition, traceable recommendations."},
            {"heading": "Discussion", "kind": "discussion", "page": 8,
             "summary": "Course-specific KG, transfer and long-term effects, and self-report bias are the limits."},
        ],
        "method_steps": METHOD_STEPS,
        "figures": [
            fig(1, 3, "Adaptive recommendation loop. A mistake-pattern encoder links attempts to knowledge-graph skills; a policy picks the next exercise.",
                sk.pipeline("LearnFlow Adaptive Loop", METHOD_STEPS, tag="Fig. 1 · Original"), "high"),
            fig(2, 6, "Study design: 620 students randomized to LearnFlow (n=310) or a difficulty-adaptive control (n=310) for 6 weeks.",
                sk.architecture("RCT Design — 6 Weeks", [
                    {"x": 40, "y": 110, "w": 200, "h": 60, "label": "Pre-test", "color": "#94A3B8"},
                    {"x": 300, "y": 90, "w": 170, "h": 60, "label": "LearnFlow (n=310)", "color": ACCENT},
                    {"x": 300, "y": 180, "w": 170, "h": 60, "label": "Control (n=310)", "color": "#64748B"},
                    {"x": 540, "y": 130, "w": 150, "h": 64, "label": "Post-test", "color": "#22D3EE"},
                ], [
                    {"from": [240, 140], "to": [300, 120], "label": "randomize"},
                    {"from": [240, 140], "to": [300, 210], "label": "randomize"},
                    {"from": [470, 120], "to": [540, 150], "label": "measure"},
                    {"from": [470, 210], "to": [540, 180], "label": "measure"},
                ], tag="Fig. 2 · Study"), "medium"),
            fig(3, 7, "Post-test mastery gains by decile of baseline ability. LearnFlow gains concentrate in the middle deciles.",
                sk.bar_chart("Post-test Mastery Gain (pp) by Baseline Decile",
                             ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10"],
                             [6.0, 9.1, 12.3, 16.4, 18.7, 19.2, 16.9, 13.5, 10.2, 6.8], color=ACCENT, tag="Fig. 3 · Gains"), "medium"),
        ],
        "tables": [
            {
                "table_no": 1, "page": 7,
                "caption": "Primary and secondary outcomes (mean ± sd).",
                "headers": ["Outcome", "LearnFlow", "Control", "Δ", "p"],
                "content": [
                    ["Post-test mastery", "0.76", "0.61", "+0.148", "<.001"],
                    ["Off-task repetition", "0.41", "0.72", "-31%", "<.001"],
                    ["Practice time (h/wk)", "2.9", "3.4", "-0.5", ".02"],
                    ["Skill coverage", "38/42", "24/42", "+14", "<.001"],
                ],
            },
            {
                "table_no": 2, "page": 7,
                "caption": "Ablation of the recommendation policy.",
                "headers": ["Policy", "Post-test", "Off-task rep.", "Traceability"],
                "content": [
                    ["Difficulty-adaptive", "0.61", "0.72", "no"],
                    ["+KG link (no error)", "0.68", "0.60", "skill"],
                    ["+error model", "0.73", "0.48", "skill+misconcept"],
                    ["Full LearnFlow", "0.76", "0.41", "skill+misconcept"],
                ],
            },
        ],
        "claims": [
            {"claim_id": "claim_01", "type": "RESULT", "confidence": 0.96, "statement": "LearnFlow raised post-test mastery by 14.8% relative to a difficulty-adaptive baseline.",
             "evidence": [ev(7, "table_1", "table", "Table 1 shows +0.148 post-test mastery (p<.001).", "+14.8%")]},
            {"claim_id": "claim_02", "type": "RESULT", "confidence": 0.94, "statement": "Off-task repetition decreased by 31%.",
             "evidence": [ev(7, "table_1", "table", "Table 1 lists a 31% reduction in off-task repetition.", "-31%")]},
            {"claim_id": "claim_03", "type": "METHOD", "confidence": 0.95, "statement": "Every recommendation is traceable to a skill in the knowledge graph (with misconception detail).",
             "evidence": [ev(8, "table_2", "table", "Table 2 reports skill+misconcept traceability for the full model.", "traceable")]},
            {"claim_id": "claim_04", "type": "LIMITATION", "confidence": 0.85, "statement": "The skill graph is course-specific; cross-course transfer, long-term effects, and self-report bias are unresolved.",
             "evidence": [ev(8, "discussion", "section", "Discussion flags course-specific KG, transfer, and self-report bias.", "Discussion p.8")]},
        ],
        "graph": {
            "nodes": [
                {"node_id": "g_problem", "kind": "problem", "label": "Problem", "props": {"text": "Same next exercise for every student"}},
                {"node_id": "g_method", "kind": "method", "label": "Method", "props": {"text": "KG + mistake encoder + E[gain] policy"}},
                {"node_id": "g_dataset", "kind": "experiment", "label": "Study", "props": {"text": "620 students · 6-week RCT"}},
                {"node_id": "g_exp", "kind": "experiment", "label": "Experiment", "props": {"text": "vs difficulty-adaptive"}},
                {"node_id": "g_claim1", "kind": "claim", "label": "Claim 01", "props": {"text": "+14.8% post-test mastery", "claim_id": "claim_01"}},
                {"node_id": "g_claim2", "kind": "claim", "label": "Claim 02", "props": {"text": "−31% off-task repetition", "claim_id": "claim_02"}},
                {"node_id": "g_ev_t1", "kind": "evidence", "label": "Table 1 · p.7", "props": {"text": "Primary outcomes"}},
                {"node_id": "g_ev_t2", "kind": "evidence", "label": "Table 2 · p.7", "props": {"text": "Policy ablation"}},
            ],
            "edges": [
                {"source": "g_problem", "target": "g_method", "label": "addresses"},
                {"source": "g_method", "target": "g_dataset", "label": "evaluated in"},
                {"source": "g_dataset", "target": "g_exp", "label": "design"},
                {"source": "g_exp", "target": "g_claim1", "label": "supports"},
                {"source": "g_exp", "target": "g_claim2", "label": "supports"},
                {"source": "g_claim1", "target": "g_ev_t1", "label": "cited to"},
                {"source": "g_claim1", "target": "g_ev_t2", "label": "cited to"},
            ],
        },
        "presentation": [
            {"order": 1, "kind": "intro", "title": "研究背景", "summary": "练习平台对所有学生给上一道题。",
             "evidence_refs": ["p.1"],
             "steps": ["千人一面", "不针对错因"],
             "narration": {"script": "主流练习平台对所有学生给出相同的下一题，很难针对每个人的错因做到个性化。", "subtitle": "千人一面的练习。"}},
            {"order": 2, "kind": "problem", "title": "问题", "summary": "很难建模并追踪学生的误解。",
             "evidence_refs": ["p.2"],
             "steps": ["错因隐藏", "技能依赖复杂"],
             "narration": {"script": "难点在于既要追踪掌握度，又要理解学生卡在哪一个错误概念上。", "subtitle": "错因难以建模。"}},
            {"order": 3, "kind": "method", "title": "方法", "summary": "知识图谱 + 错因嵌入 + 期望掌握增益策略。",
             "evidence_refs": ["图1"],
             "steps": ["作答日志", "错因编码", "图谱链接", "选题策略", "个性化路径"],
             "narration": {"script": "我们用知识图谱建模技能依赖，用错因编码器识别误解，再选期望掌握增益最大的下一题。", "subtitle": "图谱 + 错因 + 期望增益。"}},
            {"order": 4, "kind": "experiment", "title": "实验", "summary": "620 名学生 6 周随机对照。",
             "evidence_refs": ["图2", "表1"],
             "steps": ["随机分组", "6 周干预", "后测与日志指标"],
             "narration": {"script": "我们做了 6 周随机对照，对比难度自适应基线，测量后测掌握度与离题重复等指标。", "subtitle": "6 周随机对照。"}},
            {"order": 5, "kind": "result", "title": "结果", "summary": "掌握度 +14.8%，离题重复 −31%。",
             "evidence_refs": ["表1", "表2"],
             "steps": ["后测提升", "重复下降", "推荐可溯源"],
             "narration": {"script": "结果是后测掌握度提升 14.8%，离题重复下降 31%，且每条推荐都能追溯到图谱技能。", "subtitle": "+14.8% · −31% · 可溯源。"}},
            {"order": 6, "kind": "limitation", "title": "局限", "summary": "技能图谱课程内先验，跨课程与长效应未验证。",
             "evidence_refs": ["p.8 Discussion"],
             "steps": ["图谱课程内先验", "跨课程迁移未验证", "自我报告动机偏倚"],
             "narration": {"script": "局限在于技能图谱是课程内的先验构建，跨课程迁移、长期效应与自我报告偏倚都未解决。", "subtitle": "课程内图谱，迁移待验证。"}},
        ],
        "qa_bank": [
            {"q": "这篇论文的方法核心是什么？", "a": "构建技能知识图谱并建模学生错因为潜在误解，再以期望掌握增益最大化策略选择下一题，从而既追踪掌握度又针对错因。",
             "confidence": "High", "evidence_refs": [ev(3, "method", "section", "Method 描述 KG + 错因嵌入 + E[mastery gain] 策略。", "Method p.3")]},
            {"q": "实验规模与效果如何？", "a": "620 名本科生 6 周随机对照；后测掌握度提升 14.8%，离题重复下降 31%。", "confidence": "High",
             "evidence_refs": [ev(7, "table_1", "table", "Table 1 报告 +14.8% 与 -31%。", "Table 1 p.7")]},
            {"q": "论文最值得质疑的地方？", "a": "技能图谱基于单一课程先验构建，跨课程迁移、大样本长期效应与自我报告动机的偏倚尚未验证，其外部效度值得质疑。",
             "confidence": "High", "evidence_refs": [ev(8, "discussion", "section", "Discussion 标明课程内图谱、迁移与自我报告偏倚。", "Discussion p.8")]},
            {"q": "与难度自适应基线相比提升多少？", "a": "后测掌握度 +0.148（14.8pp），离题重复 −31%，技能覆盖从 24/42 提升到 38/42。", "confidence": "High",
             "evidence_refs": [ev(7, "table_1", "table", "Table 1 对照列显示 Δ 与 p 值。", "Table 1 p.7")]},
        ],
    }
