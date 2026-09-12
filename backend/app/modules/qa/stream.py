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

from . import answer_gate as gate, service as svc

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


async def stream(
    scope: Scope,
    request: QARequest,
    ctx: Optional[CallContext] = None,
) -> AsyncIterator[bytes]:
    """产出 SSE 字节流。**final 只在 Answer 完整持久化后发送**。

    生成过程在取消令牌触发时提前结束，并尽量发出唯一终态。
    """
    encoder = EventEncoder()
    terminal = _Terminal()
    request_id = _request_id(ctx)

    # meta：先声明本次回答的身份与截止时间
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
        if terminal.claim("error"):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "error",
                QAError(error=_cancelled_error(), partial=False),
            ))
        return

    loop = asyncio.get_event_loop()
    try:
        record = await loop.run_in_executor(None, svc.answer, scope, request, ctx)
    except DomainError as exc:
        if terminal.claim("error"):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "error",
                QAError(error=exc.to_dict(), partial=False),
            ))
        return
    except Exception as exc:  # noqa: BLE001  未知异常也必须给唯一终态
        if terminal.claim("error"):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "error",
                QAError(error=_internal_error(exc), partial=False),
            ))
        return

    if _cancelled(ctx):
        if terminal.claim("error"):
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "error",
                QAError(error=_cancelled_error(), partial=False),
            ))
        return

    # status：告知已进入验证/降级/通用回答（ADR-0057）
    mode = str(getattr(record, "mode", "") or "")
    if mode == "general":
        stage, message = "drafting", "通用回答（未使用论文证据）"
    elif record.grounded:
        stage, message = "verifying", "正在逐句核验证据"
    else:
        stage, message = "degraded", "按拒答返回"
    yield encoder.encode(_event(
        encoder.next_id(), request_id, "status",
        QAStatus(stage=stage, message=message),
    ))

    sent_evidence: List[str] = []

    # 先发全部 citation（保证 sentence 引用它时已被发送过）
    for st in record.statements:
        for ev in _evidence_for(record, st):
            if ev.id in sent_evidence:
                continue
            sent_evidence.append(ev.id)
            yield encoder.encode(_event(
                encoder.next_id(), request_id, "citation",
                _citation_payload(ev),
            ))

    # 再发 sentence（只发可发布句子，unverified 草稿不发）
    for st in gate.publishable_sentences(record.statements):
        yield encoder.encode(_event(
            encoder.next_id(), request_id, "sentence",
            QASentence(statement=st),
        ))

    # 唯一终态：final（AnswerRecord 已在上一步持久化完成）
    if terminal.claim("final"):
        yield encoder.encode(_event(
            encoder.next_id(), request_id, "final",
            _final_payload(record),
        ))


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
    return DomainError(
        ErrorCode.INTERNAL_ERROR, f"内部错误：{type(exc).__name__}"
    ).to_dict()


__all__ = [
    "HEARTBEAT_SECONDS",
    "EventEncoder",
    "stream",
    "heartbeat_stream",
    "encode_from_records",
]
