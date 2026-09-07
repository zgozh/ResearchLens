"""modules/pipeline — 流水线编排模块（Spec §B.10）。

将解析→结构→断言→证据→图谱→场景→问答→评测串成有状态、可降级的 Pipeline，
并记录每个 stage 的状态（任务追踪/可观测）。
API: run_pipeline / PIPELINE_STAGES / stage_label
"""
from app.services.pipeline import run_pipeline, _stage_parse, _stage_claims  # noqa: F401

PIPELINE_STAGES = ["parse", "structure", "claims", "evidence", "graph", "scene", "qa", "eval"]

_STAGE_LABEL = {
    "parse": "正在解析论文…",
    "structure": "正在抽取章节结构…",
    "claims": "正在提取可验证断言…",
    "evidence": "正在链接证据（Evidence Gate）…",
    "graph": "正在构建研究图谱…",
    "scene": "正在生成场景与讲解词…",
    "qa": "正在准备证据问答…",
    "eval": "正在计算自动评测…",
    "evaluate": "正在计算自动评测…",
    "done": "已完成",
    "failed": "失败",
    "running": "处理中",
    "pending": "等待中",
}

def stage_label(stage: str) -> str:
    return _STAGE_LABEL.get(stage, stage)
