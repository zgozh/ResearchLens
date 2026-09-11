"""ResearchLens 独立 worker 入口（REFACTOR_SPEC §5.8、§6.13）。

循环：``claim_next`` → ``heartbeat``（独立线程/短事务）→ ``run_stage`` → 提交，
支持优雅停止（SIGINT/SIGTERM）。**不新增 Redis/Celery**：队列就是数据库表。

用法::

    python -m app.worker                 # 前台运行
    python -m app.worker --once          # 处理一个 job 后退出（测试/CI）
    python -m app.worker --idle-exit 5   # 连续 5 次无工作后退出

设计要点：
- 租约默认 60 秒、心跳 20 秒；长外部调用由**独立心跳线程**维持；
- 心跳**不复用业务 Session**（每次新开短事务）；
- worker 掉线后租约过期即可被其他 worker 领取（at-least-once）；
- 取消请求不打断已提交产物，但**未完成产物不发布**。
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time
from typing import Optional

from app.contracts.common import CallContext, Scope, new_ctx
from app.contracts.jobs import STAGE_ORDER, JobLease
from app.core.config import settings
from app.core.db import check_schema, run_migrations, session_scope
from app.core.errors import DomainError

log = logging.getLogger("researchlens.worker")


class Worker:
    """单进程 worker。SQLite 下建议单 worker（见 §5.8）。"""

    def __init__(self, worker_id: Optional[str] = None, once: bool = False,
                 idle_exit: int = 0, poll_interval: float = 1.0) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.once = once
        self.idle_exit = idle_exit
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._lease: Optional[JobLease] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------- 生命周期

    def stop(self) -> None:
        """优雅停止：设置标志，等当前阶段提交后退出。"""
        log.info("worker %s 收到停止请求，等待当前阶段结束…", self.worker_id)
        self._stop.set()

    def _install_signals(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: self.stop())
            except (ValueError, OSError):  # pragma: no cover - 非主线程
                pass

    # ---------------------------------------------------------- 主循环

    def run(self) -> int:
        from app.modules.pipeline import service as svc

        self._install_signals()
        idle_rounds = 0
        processed = 0
        log.info("worker %s 启动（lease=%ss heartbeat=%ss）",
                 self.worker_id, settings.job_lease_seconds, settings.job_heartbeat_seconds)

        while not self._stop.is_set():
            try:
                lease = svc.claim_next(self.worker_id)
            except DomainError as exc:
                log.warning("领取任务失败：%s", exc.message)
                lease = None

            if lease is None:
                idle_rounds += 1
                if self.once:
                    break
                if self.idle_exit and idle_rounds >= self.idle_exit:
                    log.info("连续 %d 次无工作，退出", idle_rounds)
                    break
                self._stop.wait(self.poll_interval)
                continue

            idle_rounds = 0
            try:
                self._process(lease)
                processed += 1
            except DomainError as exc:
                log.warning("job %s 处理失败：%s", lease.job_id, exc.message)
            except Exception as exc:  # noqa: BLE001 - worker 不得因单个 job 崩溃
                log.exception("job %s 未捕获异常：%s", lease.job_id, exc)

            if self.once:
                break

        log.info("worker %s 退出（处理 %d 个 job）", self.worker_id, processed)
        return 0

    def _process(self, lease: JobLease) -> None:
        from app.modules.pipeline import service as svc

        self._lease = lease
        self._start_heartbeat(lease)
        try:
            for _ in range(len(STAGE_ORDER) + 2):
                if self._stop.is_set():
                    log.info("worker 停止中：job %s 在阶段边界退出", lease.job_id)
                    break
                stage = svc._current_stage(lease.job_id)
                if stage is None:
                    break
                try:
                    result = svc.run_stage(lease, stage)
                except DomainError as exc:
                    # fence 过期 / 已取消：当前 worker 必须立即停止该 job
                    log.info("job %s 阶段 %s 停止：%s", lease.job_id, stage, exc.message)
                    break
                if result.status == "failed":
                    break
        finally:
            self._stop_heartbeat()
            self._lease = None

    # ---------------------------------------------------------- 心跳

    def _start_heartbeat(self, lease: JobLease) -> None:
        interval = max(1, settings.job_heartbeat_seconds)

        def _beat() -> None:
            from app.modules.pipeline import service as svc

            while not self._stop.is_set():
                if self._stop.wait(interval):
                    return
                try:
                    svc.heartbeat(lease)
                except DomainError:
                    # fence 过期：放弃续租（别人已接管），本轮不再写库
                    return
                except Exception:  # noqa: BLE001
                    continue

        thread = threading.Thread(target=_beat, name=f"hb-{lease.job_id}", daemon=True)
        thread.start()
        self._heartbeat_thread = thread

    def _stop_heartbeat(self) -> None:
        thread = self._heartbeat_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._heartbeat_thread = None


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="ResearchLens pipeline worker")
    parser.add_argument("--id", dest="worker_id", default=None, help="worker 标识")
    parser.add_argument("--once", action="store_true", help="处理一个 job 后退出")
    parser.add_argument("--idle-exit", type=int, default=0,
                        help="连续 N 次无工作后退出（0=永不）")
    parser.add_argument("--skip-schema-check", action="store_true",
                        help="跳过启动 schema 检查（不推荐）")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.skip_schema_check:
        try:
            # 先跑迁移（幂等，checkfirst），再校验版本——worker 独立启动不依赖 backend 先迁移。
            run_migrations()
            check_schema(strict=True)
        except DomainError as exc:
            # schema 不符不得静默降级：worker 直接失败退出
            log.error("worker 启动失败：%s", exc.message)
            return 2

    worker = Worker(worker_id=args.worker_id, once=args.once, idle_exit=args.idle_exit)
    return worker.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
