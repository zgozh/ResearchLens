"""M00 — 全局配置（REFACTOR_SPEC §5.10 Settings + 现有 `.env` 兼容）。

- 保留原有全部字段（llm_* / mineru_* / tts_* / max_upload_mb ...），
  现有调用方 `from app.core.config import settings` 继续可用。
- 新增 canonical 字段：data_dir / max_download_bytes / allowed_source_hosts /
  public_deployment / admin_token_configured / job_lease_seconds / qa_deadline_ms /
  mineru_enabled。
- 配置错误必须在启动阶段显式失败（不静默降级），见 `load_settings()`。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from .errors import DomainError, ErrorCode

# Load .env relative to backend/ (parent of app/)
_BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv()  # also honor ambient env

_DEFAULT_DATA_DIR = _BACKEND_DIR / "data"


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


def _env_list(key: str, default: str = "") -> List[str]:
    return [x.strip() for x in _env(key, default).split(",") if x.strip()]


@dataclass
class Settings:
    # --- mode ---
    # R4：**DEMO_MODE 开关已彻底删除**（用户要求"让整个项目都是完整模型"）。
    # 留着双态开关的坏处：`cp .env.example .env` 后忘了改 → 上传被 400 拦掉，
    # 而界面提示只在失败之后才出现，用户看到的是"处理失败"。
    # 真值只有一个：有 LLM 就调 LLM；没配就**运行期降级**（`has_llm=False` 走抽取式），
    # 后者是降级能力，不是"演示模式"，两者不是一回事。
    app_name: str = _env("APP_NAME", "ResearchLens API")
    version: str = _env("VERSION", "1.0.0")

    # --- storage ---
    database_url: str = _env("DATABASE_URL", "sqlite:///./data/researchlens.db")
    data_dir: Path = field(
        default_factory=lambda: Path(_env("DATA_DIR", str(_DEFAULT_DATA_DIR))).resolve()
    )

    # --- ports / cors ---
    backend_port: int = _env_int("BACKEND_PORT", 8000)
    frontend_port: int = _env_int("FRONTEND_PORT", 3000)
    cors_origins: List[str] = field(
        default_factory=lambda: _env_list(
            "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
        )
    )

    # --- LLM (LIVE mode) ---
    llm_api_key: str = _env("LLM_API_KEY")
    llm_base_url: str = _env("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_model: str = _env("LLM_MODEL", "qwen-plus")
    vision_model: str = _env("VISION_MODEL", "qwen-vl-max")
    embedding_model: str = _env("EMBEDDING_MODEL", "text-embedding-v3")
    llm_fallbacks: str = _env("LLM_FALLBACKS")

    # --- MinerU 文档解析（可选）---
    mineru_token: str = _env("MINERU_TOKEN")
    mineru_base_url: str = _env("MINERU_BASE_URL", "https://mineru.net")

    # --- TTS (optional) ---
    tts_api_key: str = _env("TTS_API_KEY")
    tts_base_url: str = _env("TTS_BASE_URL")
    tts_voice: str = _env("TTS_VOICE", "zh-CN-XiaoxiaoNeural")

    # --- limits（canonical，字节口径）---
    max_upload_bytes: int = _env_int("MAX_UPLOAD_BYTES", 0) or (
        _env_int("MAX_UPLOAD_MB", 40) * 1024 * 1024
    )
    max_download_bytes: int = _env_int("MAX_DOWNLOAD_BYTES", 0) or (
        _env_int("MAX_DOWNLOAD_MB", 80) * 1024 * 1024
    )

    # --- 安全 ---
    allowed_source_hosts: List[str] = field(
        default_factory=lambda: _env_list("ALLOWED_SOURCE_HOSTS", "")
    )
    public_deployment: bool = _env_bool("PUBLIC_DEPLOYMENT", False)
    admin_token: str = _env("ADMIN_TOKEN")

    # --- pipeline / qa ---
    job_lease_seconds: int = _env_int("JOB_LEASE_SECONDS", 60)
    job_heartbeat_seconds: int = _env_int("JOB_HEARTBEAT_SECONDS", 20)
    qa_deadline_ms: int = _env_int("QA_DEADLINE_MS", 30000)
    ingest_budget_calls: int = _env_int("INGEST_BUDGET_CALLS", 60)
    ingest_budget_input_tokens: int = _env_int("INGEST_BUDGET_INPUT_TOKENS", 180000)
    ingest_budget_output_tokens: int = _env_int("INGEST_BUDGET_OUTPUT_TOKENS", 30000)
    ingest_budget_wall_ms: int = _env_int("INGEST_BUDGET_WALL_MS", 600000)
    mineru_enabled: bool = _env_bool("MINERU_ENABLED", True)

    # --- seed dir ---
    seed_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[1] / "seed"
    )

    # ------------------------------------------------------------ derived
    @property
    def has_llm(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def has_mineru(self) -> bool:
        return bool(self.mineru_token) and self.mineru_enabled

    @property
    def admin_token_configured(self) -> bool:
        return bool(self.admin_token)

    # 兼容旧命名
    @property
    def max_upload_mb(self) -> int:
        return max(1, self.max_upload_bytes // (1024 * 1024))

    @property
    def sources_dir(self) -> Path:
        return self.data_dir / "sources"

    @property
    def parser_raw_dir(self) -> Path:
        return self.data_dir / "parser-raw"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    def validate(self) -> None:
        """启动期校验；不通过直接失败（§5.10 M00）。"""
        problems: List[str] = []
        if not self.database_url:
            problems.append("DATABASE_URL 为空")
        if self.max_upload_bytes <= 0:
            problems.append("MAX_UPLOAD_BYTES 必须为正整数")
        if self.max_download_bytes <= 0:
            problems.append("MAX_DOWNLOAD_BYTES 必须为正整数")
        if self.job_lease_seconds <= 0:
            problems.append("JOB_LEASE_SECONDS 必须为正整数")
        if self.qa_deadline_ms <= 0:
            problems.append("QA_DEADLINE_MS 必须为正整数")
        if self.public_deployment and not self.admin_token:
            problems.append("PUBLIC_DEPLOYMENT=true 时必须配置 ADMIN_TOKEN")
        if problems:
            raise DomainError(
                ErrorCode.INTERNAL_ERROR,
                "配置错误：" + "；".join(problems),
                retryable=False,
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_settings() -> Settings:
    """启动入口：读取并校验配置，配置错误直接抛出 DomainError。"""
    s = Settings()
    s.validate()
    return s


settings = get_settings()


__all__ = ["Settings", "get_settings", "load_settings", "settings"]
