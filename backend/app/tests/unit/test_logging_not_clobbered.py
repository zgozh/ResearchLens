"""Alembic 的 `fileConfig` 不许吞掉应用自己的日志（否则日志全空，运维看不见）。

## 怎么发现的（不是猜的）

修 D-116 的日志键名时顺手验证"日志到底打不出来"：`provision_real_papers()` 明明
走完了（跳过 1 篇），但 `docker logs researchlens-backend-1` 里**一条 `researchlens.*`
都没有**；worker 容器更明显 —— 总共只有 9 行，全是 alembic 的插件/迁移行，
连 `worker … 启动` 都没有。

根因链（三处合起来才成立）：

1. `migrations/env.py` 在模块级无条件调用 `fileConfig(config.config_file_name)`；
2. `alembic.ini` 的 `[logger_root] level = WARN`；
3. `fileConfig` 默认 **`disable_existing_loggers=True`** —— 它会把**已存在**的
   `researchlens.*` logger 全部 `disabled = True`，并把 root 提到 WARN。

而启动顺序是 `logging.basicConfig(INFO)` → `run_migrations()` → 之后所有应用日志
（含 worker 主循环、seed 自举）**都在被禁用的 logger 上**，所以永远打不出来。

最讽刺的是 `app/core/db.py` 里**已经**写了防线与注释：

    # 不让 alembic 的 fileConfig 覆盖调用方的 logging 配置：
    # 否则 disable_existing_loggers 会吞掉 worker/backend 自己的 log（曾导致 worker 日志全空）。
    cfg.attributes["configure_logger"] = False

—— 但 `env.py` **从来没读这个属性**，防线是死代码，"曾经导致日志全空"的问题一直在。

## 本模块锁住的口径

1. `env.py` 必须**读** `configure_logger` 属性（否则 db.py 的防线形同虚设）；
2. `env.py` 调 `fileConfig` 时必须 `disable_existing_loggers=False`
   （这样命令行直接跑 `alembic upgrade` 也不会把 app logger 打残）；
3. **行为级**：调用一次 `run_migrations()` 之后，`researchlens.*` 的 logger
   仍然 enabled、有效级别 ≤ INFO —— 这是"日志真的还能打出来"的判据。
"""
from __future__ import annotations

import logging
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[4]
ENV_PY = ROOT / "backend" / "migrations" / "env.py"


class TestEnvHonoursTheFlag:
    def test_env_reads_configure_logger_attribute(self):
        src = ENV_PY.read_text(encoding="utf-8")
        assert "configure_logger" in src, (
            "env.py 必须读 config.attributes['configure_logger'] —— "
            "db.py 设了它却没被读，等于没有防线"
        )

    def test_env_passes_disable_existing_loggers_false(self):
        src = ENV_PY.read_text(encoding="utf-8")
        assert "disable_existing_loggers=False" in src, (
            "fileConfig 默认 disable_existing_loggers=True，会把已存在的 app logger 全禁掉"
        )


class TestMigrationsKeepAppLoggingAlive:
    def test_run_migrations_keeps_app_logging_config(self, tmp_path, monkeypatch):
        """行为级判据：**照应用启动的顺序**跑一遍 —— basicConfig(INFO) → run_migrations()，
        之后 root 级别还得是 INFO、`researchlens.*` 还得是 enabled。

        两点说明：
        - 用**全新临时库**跑迁移（`ALEMBIC_DATABASE_URL` 是 env.py 优先读的变量）：
          共享测试库是 conftest 用 `create_all` 建的，直接跑迁移会撞 "table already exists"；
        - 断言"root 级别没变"而不是"≤ INFO"：pytest 自己的 root 默认是 WARNING，
          直接断言级别会被测试框架带偏 —— 这里要测的是"迁移**没有改动**调用方的配置"。
        """
        from app.core.db import run_migrations

        monkeypatch.setenv("ALEMBIC_DATABASE_URL", f"sqlite:///{(tmp_path / 'mig.db').as_posix()}")
        root = logging.getLogger()
        app_log = logging.getLogger("researchlens.logging_probe")
        old_level = root.level
        root.setLevel(logging.INFO)  # 模拟 app 入口的 logging.basicConfig(level=INFO)
        try:
            run_migrations()

            assert app_log.disabled is False, (
                "run_migrations() 之后 researchlens.* logger 被禁用了 —— "
                "说明 alembic 的 fileConfig 又把日志吞了（worker/seed 日志会全空）"
            )
            assert root.level == logging.INFO, (
                f"迁移把 root 级别从 INFO 改成了 {logging.getLevelName(root.level)} —— "
                "这是 alembic.ini 的 [logger_root] level = WARN 盖到了应用配置上"
            )
        finally:
            root.setLevel(old_level)
