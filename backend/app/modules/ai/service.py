"""M05 — AI 调用与模型治理（REFACTOR_SPEC §5.10 M05、§5.6、§6.7）。

公共入口：

- ``complete(request: CompletionRequest[T], ctx) -> CompletionResult[T]``
- ``embed(texts, snapshot, ctx) -> EmbeddingBatch``
- ``get_capabilities() -> ModelCapabilities[]``
- ``set_chat_model(model, actor, ctx) -> ModelSnapshot``

纪律：
- 全局预算共享（``ctx.budget``），**不每层重新发预算**；
- json_schema → json_object 回退，两者都必须 Pydantic 验证；
- 401/403 不重试；read timeout 在预算内重试；
- 复用 httpx 连接；云调用不持有写事务。
"""
from __future__ import annotations

import hashlib
from typing import Any, List, Optional

from app.contracts.ai import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    EmbeddingBatch,
    ModelCapabilities,
    ModelSnapshot,
    Usage,
)
from app.contracts.common import CallContext, Warning
from app.core.config import settings
from app.core.errors import (
    ErrorCode,
    DomainError,
    deadline_exceeded,
    dependency_unavailable,
    invalid_input,
)
from app.core.logging import get_logger

from . import capabilities as caps
from . import transport
from . import validation

log = get_logger(__name__)

#: 单次请求内的重试上限（受全局预算与 deadline 双重约束）
MAX_ATTEMPTS = 3

#: embedding 单次请求的最大 input 条数（text-embedding-v3 上限 10，超限返回 400）
EMBED_BATCH_SIZE = 10


def _providers() -> List[transport.Provider]:
    return transport.build_providers()


def _snapshot_model(request: CompletionRequest, ctx: Optional[CallContext]) -> str:
    if request.model_snapshot and request.model_snapshot.chat_model:
        return request.model_snapshot.chat_model
    if ctx is not None and ctx.model_snapshot is not None:
        name = getattr(ctx.model_snapshot, "chat_model", "") or ""
        if name:
            return name
    return ""


def _messages_payload(messages: List[ChatMessage]) -> List[dict]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _budget_guard(ctx: Optional[CallContext], used_calls: int) -> None:
    """统一守卫：取消 → deadline → 调用预算（顺序即优先级）。

    ``max_calls`` 语义是"本上下文最多允许的云调用次数"（``ge=0``）；
    ``0`` 表示一次都不允许，而不是无限。预算耗尽抛 ``DEADLINE_EXCEEDED``。
    """
    if ctx is None:
        return
    if ctx.is_cancelled():
        raise DomainError(ErrorCode.CANCELLED, "调用已取消", retryable=False)
    transport.check_deadline(ctx.deadline_at, request_id=ctx.request_id)
    if used_calls >= ctx.budget.max_calls:
        raise DomainError(
            ErrorCode.DEADLINE_EXCEEDED,
            f"云调用预算已耗尽（上限 {ctx.budget.max_calls} 次）",
            retryable=False,
        )


def complete(
    request: CompletionRequest,
    ctx: Optional[CallContext] = None,
) -> CompletionResult:
    """结构化/文本补全。返回值中的 ``value`` 已通过 Pydantic 验证（若提供 schema）。"""
    if not request.messages:
        raise invalid_input("messages 不能为空", field="messages")

    binding = validation.resolve_schema(
        request.output_schema, default_name=getattr(request, "schema_name", None) or "result"
    )
    model_override = _snapshot_model(request, ctx)
    providers = _providers()
    if not providers:
        raise DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "未配置模型服务（LLM_API_KEY 缺失）",
            retryable=True,
        )

    deadline_at = ctx.deadline_at if ctx is not None else None
    warnings: List[Warning] = []
    last_error: Optional[DomainError] = None
    total_calls = 0

    for provider in providers:
        base_body: dict = {
            "messages": _messages_payload(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "model": model_override or provider.model,
        }

        # ---------- 路径一：严格 json_schema ----------
        if binding.json_schema is not None:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                _budget_guard(ctx, total_calls)
                total_calls += 1
                schema_mode = "json_schema"
                body = {
                    **base_body,
                    "response_format": validation.json_schema_format(binding),
                }
                try:
                    result = transport.chat_once(provider, body)
                    caps.observe(provider.model, json_schema=True)
                    return _finish_structured(result, binding, ctx, "json_schema",
                                              total_calls, warnings)
                except DomainError as exc:
                    last_error = exc
                    if exc.code in (ErrorCode.FORBIDDEN,):
                        raise
                    if not exc.retryable:
                        # 供应商拒绝 schema：回退 json_object（能力记为 False）
                        caps.observe(provider.model, json_schema=False)
                        warnings.append(
                            Warning(
                                code="json_schema_unsupported",
                                message="供应商不接受 json_schema，已回退 json_object",
                                stage="ai",
                            )
                        )
                        break
                    if attempt >= MAX_ATTEMPTS:
                        break
                if deadline_at is not None:
                    transport.check_deadline(deadline_at, request_id=getattr(ctx, "request_id", ""))

            # json_object 回退
            for attempt in range(1, MAX_ATTEMPTS + 1):
                _budget_guard(ctx, total_calls)
                total_calls += 1
                hint = validation.schema_hint(binding)
                body = {
                    **base_body,
                    "messages": base_body["messages"] + [{"role": "user", "content": hint}],
                    "response_format": {"type": "json_object"},
                }
                try:
                    result = transport.chat_once(provider, body)
                    caps.observe(provider.model, json_object=True)
                    return _finish_structured(result, binding, ctx, "json_object",
                                              total_calls, warnings)
                except DomainError as exc:
                    last_error = exc
                    if exc.code == ErrorCode.FORBIDDEN:
                        raise
                    if not exc.retryable:
                        caps.observe(provider.model, json_object=False)
                        break
                    if attempt >= MAX_ATTEMPTS:
                        break
            continue

        # ---------- 路径二：纯文本 ----------
        for attempt in range(1, MAX_ATTEMPTS + 1):
            _budget_guard(ctx, total_calls)
            total_calls += 1
            try:
                result = transport.chat_once(provider, base_body)
                return CompletionResult(
                    value=result.text,
                    usage=_usage(result.usage),
                    model=result.model,
                    mode="text",
                    attempts=total_calls,
                    warnings=warnings,
                )
            except DomainError as exc:
                last_error = exc
                if exc.code == ErrorCode.FORBIDDEN:
                    raise
                if not exc.retryable or attempt >= MAX_ATTEMPTS:
                    break

    if last_error is not None:
        raise last_error
    raise dependency_unavailable("所有模型供应商标均调用失败")


def _finish_structured(
    result: transport.TransportResult,
    binding: validation.SchemaBinding,
    ctx: Optional[CallContext],
    mode: str,
    attempts: int,
    warnings: List[Warning],
) -> CompletionResult:
    """解析 + **Pydantic 验证**（两种模式共用同一条验证路径）。"""
    payload = validation.parse_json_text(result.text)
    if payload is None:
        raise DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "模型未返回可解析的 JSON 对象",
            retryable=True,
        )
    try:
        value = binding.validate(payload)
    except Exception as exc:  # noqa: BLE001  (pydantic ValidationError)
        detail = validation.summarise(exc) if hasattr(exc, "errors") else "schema 校验失败"
        raise DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"模型输出未通过 schema 校验：{detail}",
            retryable=True,
            cause=exc,
        ) from exc
    return CompletionResult(
        value=value,
        usage=_usage(result.usage),
        model=result.model,
        mode=mode,
        attempts=attempts,
        warnings=warnings,
    )


def _usage(raw: dict) -> Usage:
    return Usage(
        input_tokens=raw.get("input_tokens"),
        output_tokens=raw.get("output_tokens"),
        elapsed_ms=int(raw.get("elapsed_ms") or 0),
    )


def embed(
    texts: List[str],
    snapshot: Optional[ModelSnapshot] = None,
    ctx: Optional[CallContext] = None,
) -> EmbeddingBatch:
    """批量 embedding；校验数量/顺序/维度一致、有限值。

    按供应商上限分批：text-embedding-v3 单次 ``input`` 最多 10 条
    （超限返回 400 ``batch size ... not be larger than 10``）。
    """
    if not texts:
        raise invalid_input("texts 不能为空", field="texts")
    _budget_guard(ctx, 0)

    providers = _providers()
    if not providers:
        raise DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE, "未配置模型服务", retryable=True
        )
    provider = providers[0]
    model = (snapshot.embedding_model if snapshot and snapshot.embedding_model
             else settings.embedding_model)

    batch_size = EMBED_BATCH_SIZE
    collected: List[dict] = []
    for offset in range(0, len(texts), batch_size):
        chunk = list(texts[offset:offset + batch_size])
        last_error: Optional[DomainError] = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            _budget_guard(ctx, attempt - 1)
            try:
                raw = transport.embeddings_once(provider, model=model, texts=chunk)
                data = raw.get("data")
                if isinstance(data, list):
                    collected.extend(data)
                last_error = None
                break
            except DomainError as exc:
                last_error = exc
                if exc.code == ErrorCode.FORBIDDEN or not exc.retryable:
                    raise
            if ctx is not None:
                transport.check_deadline(ctx.deadline_at, request_id=ctx.request_id)
        if last_error is not None:
            raise last_error

    return _build_embedding_batch({"data": collected}, model, texts)


def _build_embedding_batch(raw: dict, model: str, texts: List[str]) -> EmbeddingBatch:
    data = raw.get("data")
    if not isinstance(data, list) or not data:
        raise dependency_unavailable("embedding 响应缺少 data")
    # 按 index 排序，保证与输入顺序一致
    try:
        ordered = sorted(data, key=lambda d: int(d.get("index", 0)))
    except (TypeError, ValueError):
        ordered = list(data)
    vectors = [d.get("embedding") for d in ordered]
    if len(vectors) != len(texts):
        raise DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"embedding 数量不一致：请求 {len(texts)} 条，返回 {len(vectors)} 条",
            retryable=False,
        )
    dimension = 0
    for vec in vectors:
        if not isinstance(vec, list) or not vec:
            raise dependency_unavailable("embedding 向量为空")
        if dimension == 0:
            dimension = len(vec)
        elif len(vec) != dimension:
            raise DomainError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "embedding 向量维度不一致",
                retryable=False,
            )
    import math

    for vec in vectors:
        for value in vec:
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise DomainError(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    "embedding 向量包含非有限值",
                    retryable=False,
                )

    caps.observe(model, embedding_dimension=dimension)
    usage_raw = raw.get("usage") or {}
    return EmbeddingBatch(
        model=model,
        dimension=dimension,
        vectors=[[float(x) for x in vec] for vec in vectors],
        input_hashes=[hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts],
        usage=Usage(
            input_tokens=usage_raw.get("prompt_tokens") or usage_raw.get("total_tokens"),
            output_tokens=None,
            elapsed_ms=0,
        ),
    )


# --------------------------------------------------------------- 治理入口


def get_capabilities() -> List[ModelCapabilities]:
    return caps.list_capabilities()


def set_chat_model(model: str, actor=None, ctx: Optional[CallContext] = None) -> ModelSnapshot:
    return caps.set_chat_model(model, actor, ctx)


def is_ready() -> bool:
    """是否配置了可用模型服务（不发起真实调用）。"""
    return bool(_providers())


__all__ = [
    "complete",
    "embed",
    "get_capabilities",
    "set_chat_model",
    "is_ready",
]
