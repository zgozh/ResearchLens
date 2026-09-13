"""M10 — 证据问答模块（REFACTOR_SPEC §3.2、§5.7、§5.10、§6.12）。

流程固定：``retrieve → 可选 rerank → draft → 逐句 gate``。
``grounded=true`` 仅当答案有实质内容 + 所有事实句有验证通过的证据 + 无未支持推断；
**没有"拒答"这一档**（R4-M3 / ADR D-104）：所有问题都有回答，靠 ``confidence`` 表达可靠度；
**绝不按「未出现拒答词」判定**；**绝不从 Section.summary 补造证据**。
事件顺序：先 citation 后 sentence，最后恰好一个 final 或 error。

API:
- ``answer(scope, request, ctx) -> AnswerRecord``（canonical）
- ``stream(scope, request, ctx) -> AsyncIterator[bytes]``（canonical SSE）
- ``build_bank(scope, questions, ctx) -> List[AnswerRecord]``
- ``answer_question(db, paper_id, question, top_k) -> AskResponse``（旧 HTTP 兼容）
"""
from .answer_gate import assess, publishable_sentences  # noqa: F401
from .legacy import answer_question  # noqa: F401
from .service import (  # noqa: F401
    ALGORITHM_VERSION,
    UNGROUNDED_NOTE,
    answer,
    build_bank,
)
from .stream import EventEncoder, encode_from_records, heartbeat_stream, stream  # noqa: F401

__all__ = [
    "answer",
    "build_bank",
    "answer_question",
    "stream",
    "heartbeat_stream",
    "encode_from_records",
    "EventEncoder",
    "assess",
    "publishable_sentences",
    "UNGROUNDED_NOTE",
    "ALGORITHM_VERSION",
]
