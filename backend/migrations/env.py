"""Alembic 环境：复用应用配置与元数据。"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.core.db import Base  # noqa: E402
from app import models  # noqa: F401,E402  (注册全部 ORM)

config = context.config

# 日志配置：**必须**尊重 `configure_logger` 属性，并关掉 disable_existing_loggers。
#
# 为什么（实测，不是理论）：`app/core/db.py` 的 run_migrations() 会设
# `cfg.attributes["configure_logger"] = False`，本意是"别让 alembic 的 fileConfig
# 覆盖应用日志"——但本文件此前**从不读这个属性**，防线是死代码。于是启动链
# `logging.basicConfig(INFO)` → `run_migrations()` 里 fileConfig 以默认
# `disable_existing_loggers=True` 执行：**已存在的 `researchlens.*` logger 被全部
# disabled=True**，root 被 alembic.ini 的 `[logger_root] level = WARN` 抬高。
# 后果：worker 主循环、seed 自举、pipeline 的应用日志**一条都打不出来**
# （实测 worker 容器日志只有 9 行 alembic）。
# 两处一起修：读属性（命令行 `alembic upgrade` 时仍配置日志）+ 不吞既有 logger。
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# 优先使用环境变量（测试/CI）→ 应用配置
_db_url = os.environ.get("ALEMBIC_DATABASE_URL") or settings.database_url
config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,   # SQLite 需要 batch 模式才能 ALTER
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
