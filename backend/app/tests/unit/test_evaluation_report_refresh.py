"""评测报告**必须能被重算刷新**（否则界面永远显示过期数字）。

## 实测到的真 bug（用户 2026-09-13 报的"四个指标为 0 + 两项数据源不一致"）

`exhibits.evaluation`（canonical）与 `/evaluation`（现算）给出**两套不同的数**：

| 指标 | 持久化报告（exhibits） | 现算（/evaluation） |
|---|---|---|
| support_precision | **0.0**（measured，0/4） | 0.8571（AI 裁判 6/7） |
| support_recall | **0.0**（measured，0/12） | 0.5455（6/11） |
| quote_exact_rate | 1.0（n=4） | 0.973 |
| input_tokens / output_tokens | 3459 / 723 | 21573 / 6252 |
| unanswerable_honesty_rate | 报告未包含该指标 | 1.0 |
| 报告 version | **rl.eval/1** | rl.eval/2 |

前端按"canonical 有值即权威"取数 → 用户看到的就是**过期的 0**。

### 根因：`insert_report` 只能插一次，第二次冲突又被静默吞掉

1. `repository.insert_report()` 是纯 `db.add(EvaluationReportORM(id=report_id, ...))`；
2. 而 `report_id = _report_id(revision_id, golden_id)` —— 对同一 (revision, golden)
   **是确定性的**（同一个字符串）；
3. 于是**第一次**写成功，之后每次 `svc.compute()` 走到 `_persist()` 都在主键上冲突；
4. `_persist()` 里是 `except Exception: pass`（"持久化失败不回滚已算好的报告"）——
   **静默吞掉**，没有任何日志。

结果：canonical 报告永远停在第一次（rl.eval/1，2026-09-12T07:41），
后面所有重算（含 `/evaluation` 每次 GET 都算的那次）都只更新了 legacy `evaluations` 行。

## 本模块锁住的口径

1. 同一 scope **重算两次，`get()` 必须读到第二次的结果**（写不进去就算 bug）；
2. `computed_at` 必须随重算推进（不能停在第一次）；
3. 落库失败**不许静默**（要有日志，便于下次一眼看到）。
"""
from __future__ import annotations

import pytest


@pytest.fixture
def scope():
    """最小可用 scope：demo 论文 + synthetic revision（不需要源文件）。"""
    from app.contracts.common import Scope
    from app.contracts.documents import PaperCreate
    from app.modules import papers as papers_mod

    paper = papers_mod.create_paper(
        PaperCreate(title="评测刷新测试", source_mode="demo", provenance_class="synthetic")
    )
    revision = papers_mod.create_revision(paper.id, None, "synthetic")
    return Scope(paper_id=paper.id, revision_id=revision.id)


def _nav_check(anchor_id: str = "anchor-1"):
    from app.contracts.evaluation import NavigationCheck

    return NavigationCheck(anchor_id=anchor_id, page_correct=True, latency_ms=1)


class TestRecomputeRefreshesPersistedReport:
    def test_second_compute_is_what_get_returns(self, scope):
        """核心回归：第二次计算的结果必须能被 `get()` 读到。"""
        from app.contracts.common import new_ctx
        from app.contracts.evaluation import EvaluationInput
        from app.modules import evaluation as ev

        first = ev.compute(EvaluationInput(scope=scope), new_ctx(scope))
        assert first.metric("anchor_page_accuracy").numerator in (None, 0.0), (
            "第一次（无导航检查）不该算出锚点页准确率"
        )

        second = ev.compute(
            EvaluationInput(scope=scope, navigation_checks=[_nav_check()]),
            new_ctx(scope),
        )
        assert second.metric("anchor_page_accuracy").numerator == 1.0

        got = ev.get(scope)
        assert got.metric("anchor_page_accuracy").numerator == 1.0, (
            "`get()` 读回的仍是**过期**报告：第二次 compute 的持久化失败被吞掉了"
            "（旧实现 = insert_report 重复主键 + _persist 里 except pass）"
        )

    def test_version_and_computed_at_advance(self, scope):
        """`version` 要跟上算法版本，`computed_at` 要随重算推进。"""
        from app.contracts.common import new_ctx
        from app.contracts.evaluation import EvaluationInput
        from app.modules import evaluation as ev

        ev.compute(EvaluationInput(scope=scope), new_ctx(scope))
        got1 = ev.get(scope)

        ev.compute(
            EvaluationInput(scope=scope, navigation_checks=[_nav_check(), _nav_check("anchor-2")]),
            new_ctx(scope),
        )
        got2 = ev.get(scope)

        assert got1.version == ev.ALGORITHM_VERSION, (
            f"持久化报告的 version 落在旧算法版本上（{got1.version} ≠ {ev.ALGORITHM_VERSION}）"
            " —— 这正是界面显示过期 0 的原因"
        )
        assert got2.computed_at is not None and got1.computed_at is not None
        assert got2.computed_at >= got1.computed_at, "重算后 computed_at 必须推进（不是停在第一次）"


class TestGetCurrentRecomputesStaleReport:
    def _stamp_stale(self, scope, *, version: str = "rl.eval/1", drop: tuple = ()) -> None:
        """把已落库报告伪造成"旧版本/缺指标"，模拟线上那份 2026-09-12 的报告。"""
        from sqlalchemy import select

        from app.core.db import session_scope
        from app.models.audit import EvaluationReportORM

        with session_scope() as db:
            row = db.execute(
                select(EvaluationReportORM).where(
                    EvaluationReportORM.revision_id == scope.revision_id
                )
            ).scalars().first()
            assert row is not None, "先 compute 一次才有可伪造的行"
            row.version = version
            row.metrics = [m for m in (row.metrics or []) if m.get("name") not in drop]

    def test_stale_version_is_recomputed(self, scope):
        """版本对不上 → `get_current` 必须重算，而不是把旧数字当权威。"""
        from app.contracts.common import new_ctx
        from app.contracts.evaluation import EvaluationInput
        from app.modules import evaluation as ev

        ev.compute(EvaluationInput(scope=scope), new_ctx(scope))
        self._stamp_stale(scope)

        got = ev.get_current(scope)
        assert got.version == ev.ALGORITHM_VERSION, (
            "读到旧版本报告必须就地重算 —— 否则界面继续显示过期数字"
        )

    def test_missing_metric_triggers_recompute(self, scope):
        """报告缺新指标（如 recovery_success_rate）同样算过期。"""
        from app.contracts.common import new_ctx
        from app.contracts.evaluation import EvaluationInput
        from app.modules import evaluation as ev

        ev.compute(EvaluationInput(scope=scope), new_ctx(scope))
        self._stamp_stale(scope, version=ev.ALGORITHM_VERSION, drop=("recovery_success_rate",))

        got = ev.get_current(scope)
        names = {e.name for e in got.metrics}
        assert "recovery_success_rate" in names, (
            "缺指标的旧报告必须重算补齐，否则界面显示「报告未包含该指标」"
        )

    def test_current_report_is_not_recomputed(self, scope, monkeypatch):
        """已经是当前版本 → 不再重算（省掉无谓计算）。"""
        from app.contracts.common import new_ctx
        from app.contracts.evaluation import EvaluationInput
        from app.modules import evaluation as ev
        from app.modules.evaluation import legacy as legacy_mod

        ev.compute(EvaluationInput(scope=scope), new_ctx(scope))

        def _boom(*a, **k):
            raise AssertionError("当前报告不该触发重算")

        monkeypatch.setattr(legacy_mod, "_input_for", _boom)
        got = ev.get_current(scope)
        assert got.version == ev.ALGORITHM_VERSION


class TestPersistFailureIsNotSilent:
    def test_persist_logs_when_write_fails(self, scope, monkeypatch, caplog):
        """落库失败要留痕：旧实现 `except Exception: pass` 把主键冲突藏了两天。"""
        import logging

        from app.contracts.common import new_ctx
        from app.contracts.evaluation import EvaluationInput
        from app.modules import evaluation as ev
        from app.modules.evaluation import repository as repo

        def _boom(*a, **k):
            raise RuntimeError("模拟落库失败")

        monkeypatch.setattr(repo, "upsert_report", _boom, raising=False)
        monkeypatch.setattr(repo, "insert_report", _boom, raising=False)

        with caplog.at_level(logging.WARNING, logger="researchlens.evaluation"):
            report = ev.compute(EvaluationInput(scope=scope), new_ctx(scope))

        assert report is not None, "落库失败不该影响已算好的报告"
        assert any("评测" in r.message or "persist" in r.message.lower() for r in caplog.records), (
            "落库失败必须留下 warning 日志（静默吞异常让这个 bug 藏了很久）"
        )
