"""Global configuration — dataclass + dotenv.

Decision D-06 / D-12: all LLM / storage / mode settings live here and are read
from `.env` once. 主链路（DEMO 模式）零 key、零 GPU、零本地模型。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env relative to backend/ (parent of app/)
_BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv()  # also honor ambient env


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_bool(key: str, default: bool) -> bool:
    v = _env(key, "").lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    # --- mode ---
    demo_mode: bool = _env_bool("DEMO_MODE", True)
    app_name: str = _env("APP_NAME", "ResearchLens API")
    version: str = _env("VERSION", "1.0.0")

    # --- storage ---
    database_url: str = _env(
        "DATABASE_URL", "sqlite:///./data/researchlens.db"
    )

    # --- ports / cors ---
    backend_port: int = _env_int("BACKEND_PORT", 8000)
    frontend_port: int = _env_int("FRONTEND_PORT", 3000)
    cors_origins: List[str] = field(
        default_factory=lambda: [
            o
            for o in _env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
            if o.strip()
        ]
    )

    # --- LLM (LIVE mode) ---
    llm_api_key: str = _env("LLM_API_KEY")
    llm_base_url: str = _env("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = _env("LLM_MODEL", "gpt-4o-mini")
    vision_model: str = _env("VISION_MODEL", "gpt-4o")
    embedding_model: str = _env("EMBEDDING_MODEL", "text-embedding-3-small")
    llm_fallbacks: str = _env("LLM_FALLBACKS")

    # --- TTS (optional) ---
    tts_api_key: str = _env("TTS_API_KEY")
    tts_base_url: str = _env("TTS_BASE_URL")
    tts_voice: str = _env("TTS_VOICE", "zh-CN-XiaoxiaoNeural")

    # --- limits ---
    max_upload_mb: int = _env_int("MAX_UPLOAD_MB", 40)

    # --- seed dir ---
    seed_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "seed"
    )

    @property
    def is_live(self) -> bool:
        return not self.demo_mode

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
