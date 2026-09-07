"""应用运行时设置（持久化到 data/runtime.json）。目前用于「用户选择的模型」。

默认从 .env 的 LLM_MODEL；可运行时切换（DashScope 模型），重启后仍生效（读回 json）。
"""
from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings

_RUNTIME = Path(__file__).resolve().parents[2] / "data" / "runtime.json"


def _load() -> dict:
    try:
        return json.loads(_RUNTIME.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _dump(d: dict) -> None:
    _RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def get_active_model() -> str:
    d = _load()
    return d.get("active_model") or settings.llm_model or "qwen-plus"


def set_active_model(model: str) -> None:
    d = _load()
    d["active_model"] = model
    _dump(d)


# DashScope（百炼）常用模型供选择
DASHSCOPE_MODELS = [
    "qwen-turbo", "qwen-plus", "qwen-max", "qwen-long",
    "qwen-vl-plus", "qwen-vl-max", "text-embedding-v3",
]
