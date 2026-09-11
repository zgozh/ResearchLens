"""M00 — 运行时设置（持久化到 data/runtime.json）。

修复 §1.5 / D27：
- 配置文件写入具备原子性（临时文件 + os.replace），并发写不破损；
- 模型切换做能力限制：不允许把 embedding-only 模型设为 chat 模型；
- 运行中的 job 使用自己的 ModelSnapshot，不随 runtime 修改漂移。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import settings
from .errors import invalid_input, internal_error

_RUNTIME = Path(settings.data_dir) / "runtime.json"

# DashScope（百炼）常用模型供选择
DASHSCOPE_MODELS: List[str] = [
    "qwen-turbo", "qwen-plus", "qwen-max", "qwen-long",
    "qwen-vl-plus", "qwen-vl-max", "text-embedding-v3",
]

# 明确只支持 embedding 的模型：不得作为 chat 模型（§5.10 M05）
_EMBEDDING_ONLY = {"text-embedding-v1", "text-embedding-v2", "text-embedding-v3",
                   "text-embedding-ada-002", "text-embedding-3-small", "text-embedding-3-large"}

# 已知可用作 chat 的模型前缀（未知模型需显式允许）
_CHAT_PREFIXES = ("qwen", "gpt", "claude", "deepseek", "glm", "moonshot", "kimi", "hunyuan")


def _load() -> Dict[str, Any]:
    try:
        return json.loads(_RUNTIME.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001  损坏文件不阻断运行，视为空配置
        return {}


def _atomic_dump(data: Dict[str, Any]) -> None:
    """原子写：同目录临时文件 + fsync + os.replace。"""
    directory = _RUNTIME.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".runtime-", suffix=".json", dir=str(directory))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, _RUNTIME)
    except Exception as exc:  # noqa: BLE001
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise internal_error("运行时配置写入失败") from exc


def _update(**patch: Any) -> Dict[str, Any]:
    data = _load()
    data.update(patch)
    _atomic_dump(data)
    return data


# ---------------------------------------------------------------- 模型治理


def is_chat_capable(model: str) -> bool:
    """判断模型是否可作为 chat 模型。

    显式黑名单优先；未知模型按前缀白名单宽松放行（候选在调用时再探测能力）。
    绝不凭模型名猜测具体能力开关（§5.6 ModelCapabilities 中 null 表示未知）。
    """
    name = (model or "").strip()
    if not name:
        return False
    lowered = name.lower()
    if lowered in _EMBEDDING_ONLY or "embedding" in lowered:
        return False
    return True


def get_active_model() -> str:
    d = _load()
    return d.get("active_model") or settings.llm_model or "qwen-plus"


def set_active_model(model: str, *, actor: Any = None) -> str:
    """设置 chat 模型；embedding-only 模型一律拒绝。"""
    name = (model or "").strip()
    if not name:
        raise invalid_input("模型名不能为空", field="model")
    if not is_chat_capable(name):
        raise invalid_input(f"模型 {name} 不支持对话用途", field="model")
    _update(active_model=name)
    return name


def get_embedding_model() -> str:
    d = _load()
    return d.get("embedding_model") or settings.embedding_model


def set_embedding_model(model: str) -> str:
    name = (model or "").strip()
    if not name:
        raise invalid_input("模型名不能为空", field="embedding_model")
    _update(embedding_model=name)
    return name


def get_model_snapshot() -> Dict[str, Any]:
    """返回当前模型快照（不含密钥），用于创建 Job / 请求级冻结。

    结构对齐 §5.6 ModelSnapshot；``id`` 由持久化层补充。
    """
    chat = get_active_model()
    embedding: Optional[str] = get_embedding_model()
    return {
        "provider": "dashscope",
        "base_url": settings.llm_base_url,
        "chat_model": chat,
        "embedding_model": embedding,
        "embedding_dimension": None,
        "capability_version": _load().get("capability_version", "rl.capabilities/1"),
        "temperature": float(_load().get("temperature", 0.2)),
    }


def set_capability_version(version: str) -> None:
    _update(capability_version=version)


def snapshot_key(snapshot: Dict[str, Any]) -> str:
    """用于缓存 key / 幂等键的稳定指纹。"""
    return "|".join(
        [
            str(snapshot.get("provider", "")),
            str(snapshot.get("chat_model", "")),
            str(snapshot.get("embedding_model") or ""),
            str(snapshot.get("capability_version", "")),
        ]
    )


def reset_for_tests(data_dir: Path | None = None) -> None:
    """测试辅助：重定向 runtime 文件位置。"""
    global _RUNTIME
    if data_dir is not None:
        _RUNTIME = Path(data_dir) / "runtime.json"


__all__ = [
    "DASHSCOPE_MODELS",
    "get_active_model",
    "set_active_model",
    "get_embedding_model",
    "set_embedding_model",
    "get_model_snapshot",
    "set_capability_version",
    "snapshot_key",
    "is_chat_capable",
    "reset_for_tests",
]
