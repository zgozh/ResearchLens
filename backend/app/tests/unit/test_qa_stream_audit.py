"""M7 流式问答审计（REFACTOR_PLAN_R3）。

为什么需要：用户报"三条默认问题都显示本次回答被中断"，但我用完全相同的 POST 复现时
服务端**每次都发了 final**（`meta → status → status → final`）。问题在客户端侧 ——
可**线上没有任何对账数据**：事件序列、终结事件到底发出去没有、客户端是否断开，事后查不到。

本文件锁住：
1. 一次流 = **一行**审计（不多写、不漏写）；
2. 成功 → `terminal='final'`；异常 → `terminal='error'` + 错误码/异常类型；
   客户端中途断开（生成器被 close）→ `terminal='none'`（这是"被中断"的对账口径）；
3. `events` 只存**类型名**序列（不存正文）；
4. 审计写库失败**不得**影响流的终结行为。
"""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""

from app.contracts.common import Scope, new_ctx  # noqa: E402
from app.contracts.qa import QARequest  # noqa: E402

# ``app.modules.qa.__init__`` 把 ``stream`` 函数重导出成同名属性 → 必须从 sys.modules 取模块
import sys  # noqa: E402

import app.modules.qa.stream  # noqa: E402,F401

stream_mod = sys.modules["app.modules.qa.stream"]

SCOPE = Scope(paper_id=7, revision_id="rev-audit")


def _record(*, mode: str = "generated", text: str = "结论句。"):
    from app.contracts.evidence import ArtifactText
    from app.contracts.qa import AnswerRecord

    return AnswerRecord(
        scope=SCOPE, id="ans-audit", question="q", text=ArtifactText(text=text, spans=[]),
        statements=[], evidence=[], grounded=False, confidence="Low", note="", mode=mode,
    )


def _drive(gen):
    async def collect():
        return [c async for c in gen]

    return asyncio.run(collect())


@pytest.fixture
def audits(monkeypatch):
    """把审计落库换成内存记录（避免依赖 DB，同时便于计数与断言）。"""
    from app.modules.qa import audit as audit_mod

    rows: list[dict] = []

    def _record_audit(**kw):
        rows.append(kw)

    monkeypatch.setattr(audit_mod, "record", _record_audit)
    return rows


class TestAuditRecordsTerminal:
    def test_success_path_records_final_once(self, audits, monkeypatch):
        from app.modules.qa import service as svc

        monkeypatch.setattr(svc, "answer", lambda *a, **k: _record())
        _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))

        assert len(audits) == 1, f"一次流只应写一行审计，实际 {len(audits)}"
        row = audits[0]
        assert row["terminal"] == "final"
        assert row["events"][0] == "meta"
        assert row["events"][-1] == "final"
        assert row["elapsed_ms"] is not None and row["elapsed_ms"] >= 0
        assert row["answer_id"], "审计要带 answer_id 才能和前端对账"

    def test_events_hold_type_names_only(self, audits, monkeypatch):
        from app.modules.qa import service as svc

        monkeypatch.setattr(svc, "answer", lambda *a, **k: _record())
        _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))
        events = audits[0]["events"]
        assert all(isinstance(e, str) and len(e) < 32 for e in events), events
        # 不存正文：事件名里不该出现答案文本
        assert "结论句" not in json.dumps(events, ensure_ascii=False)

    def test_exception_path_records_error_with_context(self, audits, monkeypatch):
        from app.modules.qa import service as svc

        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(svc, "answer", boom)
        _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))

        assert len(audits) == 1
        row = audits[0]
        assert row["terminal"] == "error"
        assert row["exception_type"] == "RuntimeError"

    def test_domain_error_records_its_code(self, audits, monkeypatch):
        from app.core.errors import DomainError, ErrorCode
        from app.modules.qa import service as svc

        def boom(*a, **k):
            raise DomainError(ErrorCode.DEADLINE_EXCEEDED, "超时")

        monkeypatch.setattr(svc, "answer", boom)
        _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))

        row = audits[0]
        assert row["terminal"] == "error"
        assert row["error_code"] == "DEADLINE_EXCEEDED"

    def test_client_disconnect_records_none(self, audits, monkeypatch):
        """客户端中途断开 → `terminal='none'`（这正是"前端被中断"的对账口径）。"""
        from app.modules.qa import service as svc

        monkeypatch.setattr(svc, "answer", lambda *a, **k: _record())

        async def consume_then_close():
            gen = stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE))
            first = await gen.__anext__()  # 只取 meta，然后关闭
            assert first
            await gen.aclose()

        asyncio.run(consume_then_close())
        assert len(audits) == 1, f"断开也要留一行，实际 {len(audits)}"
        assert audits[0]["terminal"] == "none"
        assert audits[0]["events"] == ["meta"]

    def test_audit_record_swallows_its_own_failure(self, monkeypatch):
        """`audit.record` 内部必须自己吞掉异常（审计表挂了不能反过来打断回答）。"""
        from app.modules.qa import audit as audit_mod

        import app.core.db as db_mod

        def boom():
            raise RuntimeError("审计表挂了")

        monkeypatch.setattr(db_mod, "session_scope", boom)
        # 不得抛出
        audit_mod.record(paper_id=1, revision_id="r", answer_id="a", events=["meta"])
