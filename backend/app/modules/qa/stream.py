"""M10 — 问答流式协议（REFACTOR_SPEC §5.7、§6.12）。

协议要点：
- 传输：``POST + fetch + ReadableStream``（不是 EventSource）；
- 每帧含 ``id`` / ``event`` / ``data`` 三行，**JSON 在 data 行**，空行分隔；
- **UTF-8 跨 chunk 解码**：字节流可能把多字节汉字切断，必须用增量解码器；
- **事件顺序**：先 ``citation`` 后引用它的 ``sentence``；最后**恰好一个**
  ``final`` 或 ``error``（二者不得同时出现）；
- **heartbeat 用注释帧**（``: ping``）且**不占事件序号**；
- 客户端断开触发取消（``cancel_token``）。

终态唯一性由 ``_Terminal`` 守卫强制：一旦发出 final/error，后续任何事件都被丢弃。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional

from app.contracts.common import CallContext, Scope
from app.contracts.evidence import EvidenceRecord, VerifiedStatement
from app.contracts.qa import (
    AnswerRecord,
    QAError,
    QAMeta,
    QARequest,
    QASentence,
    QAStatus,
    QAStreamEvent,
)
from app.core.errors import DomainError, ErrorCode

from . import answer_gate as gate, audit as audit_mod, service as svc

#: heartbeat 间隔（秒）；注释帧不占事件序号
HEARTBEAT_SECONDS = 10.0


@dataclass
class _Terminal:
    """终态守卫：保证 final / error 恰好其一。"""

    sent: Optional[str] = None

    def claim(self, kind: str) -> bool:
        if self.sent is not None:
            return False
        self.sent = kind
        return True


class EventEncoder:
    """把 ``QAStreamEvent`` 编成 SSE 帧（``id/event/data`` + 空行）。"""

    def __init__(self) -> None:
        self._seq = 0

    def next_id(self) -> int:
        self._seq += 1
        return self._seq

    @property
    def last_id(self) -> int:
        return self._seq

    def encode(self, event: QAStreamEvent) -> bytes:
        payload = event.model_dump(mode="json")
        data = payload.get("data")
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        lines = [
            f"id: {event.event_id}",
            f"event: {event.type}",
            f"data: {body}",
            "",
            "",
        ]
        return "\n".join(lines).encode("utf-8")

    def comment(self, text: str = "ping") -> bytes:
        """注释帧：**不改变事件序号**，客户端应忽略。"""
        return f": {text}\n\n".encode("utf-8")

    def retry(self, ms: int = 3000) -> bytes:
        return f"retry: {int(ms)}\n\n".encode("utf-8")


class _AuditedEncoder(EventEncoder):
    """记录事件类型序列（M7 审计）：`encode` 是**唯一**出口，挂这里不会漏事件。

    只记类型名、不记正文 —— 审计表体积可控，也避免把答案正文复制一份。
    """

    def __init__(self) -> None:
        super().__init__()
        self.types: List[str] = []

    def encode(self, event: QAStreamEvent) -> bytes:
        self.types.append(str(event.type))
        return super().encode(event)


async def stream(
    scope: Scope,
    request: QARequest,
    ctx: Optional[CallContext] = None,
) -> AsyncIterator[bytes]:
    """产出 SSE 字节流。**final 只在 Answer 完整持久化后发送**。

    真实缺陷与修复（REFACTOR_PLAN M6）：以前只有 ``svc.answer(...)`` 那一句在
    try/except 里，**发事件的那一段在保护之外**——那里一旦抛异常（投影字段不合法、
    `QAFinal` 构造失败…），生成器直接死掉、连接关闭，**既没有 final 也没有 error**，
    前端只能显示"本次回答被中断"。现在**所有**事件都在保护区里，任何异常都收敛成
    ``error`` 终结事件；等待生成期间每 ``HEARTBEAT_SECONDS`` 发一个注释帧保活。
    """
    encoder = _AuditedEncoder()
    timer = audit_mod.AuditTimer()
    failure: dict = {"code": None, "exc": None}
    mode_seen = ""
    terminal = _Terminal()
    request_id = _request_id(ctx)

    try:
        # meta：先声明本次回答的身份（answer_id 是断流恢复的凭据）与截止时间。
        # **必须在 try 内**：客户端只收到 meta 就断开的场景，只有这样才能走到 finally 的
        # 审计写入（`terminal='none'` 正是"前端显示被中断"的对账数据）。
        yield encoder.encode(_event(
            encoder.next_id(), request_id, "meta",
            QAMeta(
                scope=scope,
                answer_id=_answer_id(scope, request),
                deadline_at=getattr(ctx, "deadline_at", None),
            ),
        ))

        yield encoder.encode(_event(
            encoder.next_id(), request_id, "status",
            QAStatus(stage="retrieving", message="正在检索论文原文"),
        ))

        if _cancelled(ctx):
            raise _StreamCancelled()

        holder: dict = {}
        async for ping in _answer_with_heartbeat(holder, scope, request, ctx, encoder):
            yield ping
        record = holder.get("record")
        if record is None:  # 防御：不应发生
            raise RuntimeError("answer 未返回结果")
        # 兜底不变量：**空正文不许下发**（空白气泡就是用户眼里的"问答坏了"）。
        # 正常情况下 service.answer 已经保证了，这里防的是"上游被替换/回归"。
        record = svc._ensure_readable(record, request.question, ())

        # status：告知已进入验证/降级/通用回答（ADR-0057）
        mode = str(getattr(record, "mode", "") or "")
        mode_seen = mode  # M7 审计：本次回答最终落到哪个模式
        if mode in ("general",):
            stage, message = "drafting", "通用回答（未使用论文证据）"
        elif mode in ("abstained", "not_mentioned"):
            stage, message = "degraded", "论文中没有可支撑回答的证据，按如实说明返回"
        elif record.grounded:
            stage, message = "verifying", "正在逐句核验证据"
        else:
            stage, message = "degraded", "按拒答返回"
        yield encoder.encode(_event(
            encoder.next_id(), request_id, "status", QAStatus(stage=stage, message=message),
        ))

        sent_evidence: List[str] = []

        # 先发全部 citation（保证 sentence 引用它时已被发送过）
        for st in record.statements:
            for ev in _evidence_for(record, st):
                if ev.id in sent_evidence:
                    continue
                sent_evidence.append(ev.id)
                yield encoder.encode(_event(
                    encoder.next_id(), request_id, "citation", _citation_payload(ev),
                ))

        # 再发 sentence（只发可发布句子，unverified 草稿不发）
        for st in gate.publishable_sentences(record.statements):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "sentence", QASentence(statement=st),
            ))

        # 唯一终态：final（AnswerRecord 已在上一步持久化完成）
        # **先投影再占位**：`_final_payload` 可能抛（投影字段不合法）。若先 claim 后投影，
        # 异常时终态已被占，error 事件发不出去 → 客户端又看到"被中断"（实测回归）。
        final_payload = _final_payload(record)
        if terminal.claim("final"):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "final", final_payload,
            ))
    except _StreamCancelled:
        failure["code"] = "CANCELLED"
        if terminal.claim("error"):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "error",
                QAError(error=_cancelled_error(), partial=False),
            ))
    except DomainError as exc:
        failure["code"] = str(getattr(exc.code, "value", exc.code))
        if terminal.claim("error"):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "error",
                QAError(error=exc.to_dict(), partial=False),
            ))
    except Exception as exc:  # noqa: BLE001  未知异常也必须给唯一终态
        failure["exc"] = type(exc).__name__
        if terminal.claim("error"):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "error",
                QAError(error=_internal_error(exc), partial=False),
            ))
    finally:
        # M7 审计：**一次流只写一行**，且**只记日志不改变流**。
        # 放在 finally 里 → 客户端中途断开（GeneratorExit）也能留下 terminal='none' 的对账行，
        # 这正是"前端显示被中断"最需要的那条数据。
        audit_mod.record(
            paper_id=scope.paper_id,
            revision_id=scope.revision_id,
            answer_id=_answer_id(scope, request),
            mode=mode_seen,
            events=list(encoder.types),
            terminal=terminal.sent or "none",
            error_code=failure["code"],
            exception_type=failure["exc"],
            elapsed_ms=timer.elapsed_ms,
        )

    if terminal.sent is None:  # pragma: no cover - 防御性兜底
        terminal.claim("error")
        yield encoder.encode(_event(
            encoder.next_id(), request_id, "error",
            QAError(error=_missing_terminal_error(), partial=False),
        ))


class _StreamCancelled(Exception):
    """客户端已断开（内部信号，不对外暴露）。"""


async def _answer_with_heartbeat(
    holder: dict,
    scope: Scope,
    request: QARequest,
    ctx: Optional[CallContext],
    encoder: EventEncoder,
) -> AsyncIterator[bytes]:
    """在线程池里跑同步 ``svc.answer``，等待期间发注释帧保活并守住 deadline。

    为什么要保活：一次草稿实测可长达 100s+，期间一个字节都不发；虽然本机没有反向代理，
    但浏览器/中间件/容器网络都可能在静默连接上动手脚，用户看到的就是"一直在转"。
    为什么要有流级 deadline：``ai.complete`` 的截止时间只在**模型调用**那一层生效，
    检索/闸门/持久化不受它约束；这里按 ``ctx.deadline_at`` 兜一层总闸。
    """
    loop = asyncio.get_event_loop()
    task = loop.run_in_executor(None, svc.answer, scope, request, ctx)
    deadline = _deadline_ts(ctx)
    while True:
        timeout = _heartbeat_seconds()
        if deadline is not None:
            # 注意：deadline 是 datetime，相减得到 timedelta —— 必须 total_seconds()，
            # 否则 min(float, timedelta) 直接 TypeError，**每一次真实 SSE 都会变成 error**。
            remaining = (deadline - _now_ts()).total_seconds()
            if remaining <= 0:
                raise DomainError(
                    ErrorCode.DEADLINE_EXCEEDED,
                    "回答超过约定截止时间仍未完成，已中断（可重试或换一种问法）",
                )
            timeout = min(timeout, remaining)
        done, _pending = await asyncio.wait({task}, timeout=timeout)
        if done:
            break
        yield encoder.comment()
    holder["record"] = task.result()


def _heartbeat_seconds() -> float:
    """读模块级常量（测试可 monkeypatch ``stream.HEARTBEAT_SECONDS``）。"""
    return float(globals().get("HEARTBEAT_SECONDS", 10.0))


def _deadline_ts(ctx: Optional[CallContext]):
    value = getattr(ctx, "deadline_at", None) if ctx is not None else None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _now_ts() -> datetime:
    return datetime.now(timezone.utc)


async def heartbeat_stream(
    source: AsyncIterator[bytes],
    interval: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[bytes]:
    """在长时间静默时插入注释帧保活；不改动事件帧与其序号。"""
    encoder = EventEncoder()
    iterator = source.__aiter__()
    pending: Optional[asyncio.Task] = None

    while True:
        if pending is None:
            pending = asyncio.ensure_future(iterator.__anext__())
        try:
            chunk = await asyncio.wait_for(asyncio.shield(pending), timeout=interval)
        except asyncio.TimeoutError:
            yield encoder.comment()
            continue
        except StopAsyncIteration:
            return
        finally:
            if pending is not None and pending.done():
                pending = None
        yield chunk


def encode_from_records(
    record: AnswerRecord,
    request_id: str = "sync",
) -> List[bytes]:
    """把已完成的 AnswerRecord 编成同一套事件序列（非流式共用同一 gate 输出）。"""
    encoder = EventEncoder()
    events: List[bytes] = [
        encoder.encode(_event(
            encoder.next_id(), request_id, "meta",
            QAMeta(scope=record.scope, answer_id=record.id, deadline_at=None),
        )),
    ]
    for ev in record.evidence:
        events.append(encoder.encode(_event(
            encoder.next_id(), request_id, "citation", _citation_payload(ev),
        )))
    for st in gate.publishable_sentences(record.statements):
        events.append(encoder.encode(_event(
            encoder.next_id(), request_id, "sentence",
            QASentence(statement=st),
        )))
    events.append(encoder.encode(_event(
        encoder.next_id(), request_id, "final", _final_payload(record),
    )))
    return events


# =============================================================== 内部


def _event(event_id: int, request_id: str, type_: str, data: Any) -> QAStreamEvent:
    return QAStreamEvent(
        event_id=event_id, request_id=request_id, type=type_,
        data=data.model_dump(mode="json") if hasattr(data, "model_dump") else data,
    )


def _citation_payload(ev: EvidenceRecord):
    from app.contracts.qa import QACitation

    return QACitation(evidence=ev).model_dump(mode="json")


def _final_payload(record: AnswerRecord) -> dict:
    from app.contracts.qa import QAFinal

    return QAFinal(legacy=_legacy_answer(record), answer=record).model_dump(mode="json")


def _legacy_answer(record: AnswerRecord) -> dict:
    """``AskResponse`` 兼容投影：旧字段保持，**不伪造证据**。"""
    return {
        "answer": record.text.text if record.text else "",
        "grounded": record.grounded,
        "confidence": record.confidence,
        "evidence": [
            {
                "id": ev.legacy_id,
                "page": ev.source_page,
                "region": _region_of(ev),
                "region_type": "text",
                "text": ev.source_text,
                "quote": _quote_of(ev),
                "confidence": (ev.confidence if ev.confidence is not None else 0.0),
            }
            for ev in record.evidence
        ],
        "note": record.note,
    }


def _region_of(ev: EvidenceRecord) -> str:
    seg = (ev.source_region or [None])[0]
    if seg is None:
        return ""
    return f"p.{ev.source_page}"


def _quote_of(ev: EvidenceRecord) -> str:
    if ev.quote_spans:
        return "".join(span.source_text or "" for span in ev.quote_spans)
    return ""


def _evidence_for(record: AnswerRecord, st: VerifiedStatement) -> List[EvidenceRecord]:
    ids = set(getattr(st, "evidence_ids", []) or [])
    if not ids:
        return []
    return [ev for ev in record.evidence if ev.id in ids]


def _request_id(ctx: Optional[CallContext]) -> str:
    rid = getattr(ctx, "request_id", None) if ctx is not None else None
    return str(rid) if rid else "qa-stream"


def _answer_id(scope: Scope, request: QARequest) -> str:
    return svc._answer_id(scope.revision_id, request.question)


def _cancelled(ctx: Optional[CallContext]) -> bool:
    """客户端断开触发取消（令牌由适配层注入）。"""
    if ctx is None:
        return False
    try:
        return bool(ctx.is_cancelled())
    except Exception:  # noqa: BLE001
        return False


def _cancelled_error() -> dict:
    return DomainError(ErrorCode.CANCELLED, "客户端已断开，回答已取消").to_dict()


def _internal_error(exc: Exception) -> dict:
    # 带上异常正文：这类"未知异常"以前只有类型名，线上排查只能靠猜（实测吃过一次亏）
    return DomainError(
        ErrorCode.INTERNAL_ERROR, f"内部错误：{type(exc).__name__}: {exc}"
    ).to_dict()


def _missing_terminal_error() -> dict:
    """防御性兜底：走到这里说明有代码路径没发终结事件（理论不可达）。"""
    return DomainError(
        ErrorCode.STREAM_NO_TERMINAL_EVENT,
        "本次回答没有产生完整结果（服务端自检触发），请重试一次",
    ).to_dict()


__all__ = [
    "HEARTBEAT_SECONDS",
    "EventEncoder",
    "stream",
    "heartbeat_stream",
    "encode_from_records",
]
