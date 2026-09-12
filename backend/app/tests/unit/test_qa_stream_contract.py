"""问答 SSE 契约：**终结事件保证**与心跳（REFACTOR_PLAN M6）。

现状（`modules/qa/stream.py`）：只有 ``svc.answer(...)`` 那一句被 try/except 包住，
**发出事件的那一段（status/citation/sentence/final）在 try 之外**。只要那里抛异常
（例如 `QAFinal` 构造失败、证据投影字段不合法），生成器直接死掉、连接关闭、
**既没有 final 也没有 error** —— 前端只能显示"本次回答被中断"。

本文件锁住：
1. 任何退出路径（成功 / 生成异常 / 发事件时异常 / 取消）都**恰好一个**终结事件；
2. `meta` 是第一个事件，且带 `answer_id`（断流恢复凭据）；
3. 生成期间有空闲心跳（注释帧 `: ping`），不让连接静默几十秒；
4. 终结事件之后不再发任何事件。
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

# 注意：``app.modules.qa.__init__`` 把 ``stream`` 函数重导出成**同名属性**，
# ``from app.modules.qa import stream`` 与 ``import app.modules.qa.stream as stream_mod``
# 拿到的都是那个**函数**（属性遮蔽了子模块）。必须从 sys.modules 取模块本体，
# 否则 monkeypatch 模块级常量（HEARTBEAT_SECONDS）无从下手。
import sys  # noqa: E402

import app.modules.qa.stream  # noqa: E402,F401

stream_mod = sys.modules["app.modules.qa.stream"]


SCOPE = Scope(paper_id=7, revision_id="rev-stream")


def _frames(chunks) -> list[tuple[str, dict | None]]:
    text = b"".join(chunks).decode("utf-8")
    out: list[tuple[str, dict | None]] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        if block.startswith(":"):
            out.append((":ping", None))
            continue
        event = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        out.append((event or "message", json.loads(data) if data else None))
    return out


def _drive(gen) -> list[tuple[str, dict | None]]:
    async def collect():
        return [chunk async for chunk in gen]

    return _frames(asyncio.run(collect()))


def _record(*, mode: str = "generated", text: str = "结论句。"):
    from app.contracts.evidence import ArtifactText
    from app.contracts.qa import AnswerRecord

    return AnswerRecord(
        scope=SCOPE, id="ans-1", question="主要贡献是什么？",
        text=ArtifactText(text=text, spans=[]),
        statements=[], evidence=[], grounded=False, confidence="Low",
        note="", mode=mode,
    )


def _terminal(frames):
    return [f for f in frames if f[0] in ("final", "error")]


def test_meta_is_first_and_carries_answer_id(monkeypatch):
    from app.modules.qa import service as svc

    monkeypatch.setattr(svc, "answer", lambda *a, **k: _record())
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="主要贡献是什么？"), new_ctx(SCOPE)))

    assert frames[0][0] == "meta", frames[0]
    assert frames[0][1]["answer_id"], "meta 必须带 answer_id（断流恢复凭据）"


def test_success_path_emits_exactly_one_final(monkeypatch):
    from app.modules.qa import service as svc

    monkeypatch.setattr(svc, "answer", lambda *a, **k: _record())
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))
    terminii = _terminal(frames)
    assert len(terminii) == 1 and terminii[0][0] == "final", terminii
    assert frames[-1][0] == "final", "终结事件之后不得再发事件"


def test_generation_failure_emits_error(monkeypatch):
    from app.modules.qa import service as svc

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc, "answer", boom)
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))
    terminii = _terminal(frames)
    assert len(terminii) == 1 and terminii[0][0] == "error", terminii


def test_emission_failure_still_emits_terminal(monkeypatch):
    """回归锁：**发事件阶段**抛异常也必须给终结事件（当前会静默断流）。"""
    from app.modules.qa import service as svc

    monkeypatch.setattr(svc, "answer", lambda *a, **k: _record())

    def boom(*a, **k):
        raise ValueError("publishable_sentences 炸了")

    monkeypatch.setattr(stream_mod.gate, "publishable_sentences", boom)
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))
    terminii = _terminal(frames)
    assert len(terminii) == 1, f"必须恰好一个终结事件，实际 {frames}"
    assert terminii[0][0] == "error", terminii


def test_final_payload_failure_still_emits_terminal(monkeypatch):
    from app.modules.qa import service as svc

    monkeypatch.setattr(svc, "answer", lambda *a, **k: _record())

    def boom(*a, **k):
        raise ValueError("投影炸了")

    monkeypatch.setattr(stream_mod, "_final_payload", boom)
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))
    terminii = _terminal(frames)
    assert len(terminii) == 1 and terminii[0][0] == "error", terminii


def test_heartbeat_while_generating(monkeypatch):
    """生成慢时必须发注释帧保活（实测一次草稿可长达 100s+）。"""
    import time

    from app.modules.qa import service as svc

    monkeypatch.setattr(stream_mod, "HEARTBEAT_SECONDS", 0.2)

    def slow(*a, **k):
        time.sleep(0.7)
        return _record()

    monkeypatch.setattr(svc, "answer", slow)
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))
    assert any(f[0] == ":ping" for f in frames), f"没有心跳帧：{frames}"
    assert frames[-1][0] == "final"


def test_empty_answer_text_is_reported_not_silent(monkeypatch):
    """拒答模型也必须给出可读文本：空正文会被前端当成"没有内容"。"""
    from app.modules.qa import service as svc

    monkeypatch.setattr(svc, "answer", lambda *a, **k: _record(mode="abstained", text=""))
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))
    final = [f for f in frames if f[0] == "final"]
    assert len(final) == 1, frames
    legacy = final[0][1]["legacy"]
    assert legacy["answer"].strip(), "final.legacy.answer 不得为空（拒答要有话说）"
    assert legacy["note"].strip(), "空正文时 note 必须解释原因"


def test_cancelled_before_work_emits_error(monkeypatch):
    from app.modules.qa import service as svc

    monkeypatch.setattr(svc, "answer", lambda *a, **k: _record())
    # CallContext 是 pydantic 模型（extra=forbid），塞不进假方法 → 用鸭子类型的替身
    ctx = SimpleNamespace(request_id="t", deadline_at=None, is_cancelled=lambda: True)
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="q"), ctx))
    terminii = _terminal(frames)
    assert len(terminii) == 1 and terminii[0][0] == "error", terminii


def test_domain_error_is_surfaced_with_code(monkeypatch):
    from app.core.errors import DomainError, ErrorCode
    from app.modules.qa import service as svc

    def boom(*a, **k):
        raise DomainError(ErrorCode.DEADLINE_EXCEEDED, "超时")

    monkeypatch.setattr(svc, "answer", boom)
    frames = _drive(stream_mod.stream(SCOPE, QARequest(question="q"), new_ctx(SCOPE)))
    err = [f for f in frames if f[0] == "error"]
    assert len(err) == 1
    assert err[0][1]["error"]["code"], err[0][1]
