"""M05 — 供应商传输层（REFACTOR_SPEC §5.6、§6.7）。

不替换供应商：仍走 DashScope OpenAI 兼容 HTTP。
职责仅限"把请求发出去、把响应拿回来"，不含业务语义与 DTO 校验（见 ``validation``）。

- 复用 httpx 连接（模块级 Client，按 base_url 缓存）；
- 401/403 视为不可重试（不循环重试鉴权失败）；
- 读超时/连接错误在调用方预算内可重试；
- 不记录 key、不把完整外部报错回传。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.errors import (
    DomainError,
    ErrorCode,
    deadline_exceeded,
    dependency_unavailable,
    forbidden,
)
from app.core.logging import get_logger

log = get_logger(__name__)

#: 不重试的 HTTP 状态：鉴权/权限类
NO_RETRY_STATUS = {400, 401, 403, 404, 422}

_CLIENTS: Dict[str, httpx.Client] = {}


@dataclass
class Provider:
    api_key: str
    base_url: str
    model: str


@dataclass
class TransportResult:
    text: str
    model: str
    usage: Dict[str, Any]
    mode: str
    attempts: int


def build_providers() -> List[Provider]:
    """候选供应商：主配置 + ``LLM_FALLBACKS``（``key@url|model`` 形式）。"""
    providers: List[Provider] = []
    if settings.has_llm:
        providers.append(
            Provider(settings.llm_api_key, settings.llm_base_url.rstrip("/"), settings.llm_model)
        )
    for item in (s.strip() for s in settings.llm_fallbacks.split(",") if s.strip()):
        try:
            key_url, model = item.rsplit("|", 1)
            key, url = key_url.split("@", 1)
            providers.append(Provider(key.strip(), url.strip().rstrip("/"), model.strip()))
        except ValueError:
            continue
    return providers


def get_client(base_url: str, *, timeout: float = 120.0) -> httpx.Client:
    """按 base_url 复用长连接 Client。

    **超时以"每次请求"为准**（见 ``_request_timeout``）。``timeout`` 只决定
    新建 client 时的默认值；命中缓存时该参数**不会**生效——因此调用方必须把
    自己的超时传给 ``client.post``，不能依赖这里。

    历史坑（ADR-0008）：本函数原先把 ``timeout`` 当作 client 属性缓存，而缓存 key
    只有 ``base_url``。于是 ``index`` 阶段先建的 60s client 会永久覆盖 ``claims``
    阶段声明的 300s，导致 paper 1 的抽取 6 次尝试全部 ReadTimeout。
    """
    client = _CLIENTS.get(base_url)
    if client is None or client.is_closed:
        client = httpx.Client(
            timeout=_request_timeout(timeout),
            limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),
        )
        _CLIENTS[base_url] = client
    return client


def _request_timeout(timeout: float) -> httpx.Timeout:
    """按请求构造超时：read/write/pool = ``timeout``，connect 独立且更短。

    connect 与 read 分开设置是必要的：连接阶段失败要快速暴露，
    而长输入的生成耗时可达数分钟。
    """
    return httpx.Timeout(timeout, connect=15.0)


def close_clients() -> None:
    for client in _CLIENTS.values():
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    _CLIENTS.clear()


def _headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _raise_for_status(resp: httpx.Response) -> None:
    status = resp.status_code
    if status < 400:
        return
    if status in (401, 403):
        raise forbidden("模型服务拒绝访问（鉴权失败）")
    if status == 429:
        raise DomainError(ErrorCode.RATE_LIMITED, "模型服务限流", retryable=True)
    if status >= 500:
        raise dependency_unavailable(f"模型服务不可用（HTTP {status}）")
    raise DomainError(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        f"模型服务返回错误（HTTP {status}）",
        retryable=False,
    )


def chat_once(
    provider: Provider,
    payload: Dict[str, Any],
    *,
    timeout: float = 300.0,
) -> TransportResult:
    """单次 chat/completions 调用；网络类错误抛可重试错误。

    读超时 300s：claims 抽取等长输入（48000 字符）+ strict json_schema 输出，
    qwen-plus 可能超过 120s，避免误判 ReadTimeout 而重试。
    **该超时按请求下发**（``timeout=``），不依赖缓存 client 的构造超时。
    """
    url = f"{provider.base_url}/chat/completions"
    client = get_client(provider.base_url, timeout=timeout)
    started = time.time()
    try:
        resp = client.post(
            url, headers=_headers(provider.api_key), json=payload,
            timeout=_request_timeout(timeout),
        )
    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TransportError) as exc:
        raise dependency_unavailable(f"模型服务连接失败：{type(exc).__name__}") from exc
    _raise_for_status(resp)
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise dependency_unavailable("模型服务返回非 JSON 响应") from exc
    choices = data.get("choices") or []
    if not choices:
        raise dependency_unavailable("模型服务未返回 choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    elapsed = int((time.time() - started) * 1000)
    usage = data.get("usage") or {}
    return TransportResult(
        text=content,
        model=data.get("model") or payload.get("model") or provider.model,
        usage={
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "elapsed_ms": elapsed,
        },
        mode="text",
        attempts=1,
    )


def embeddings_once(
    provider: Provider,
    *,
    model: str,
    texts: List[str],
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """单次 embeddings 调用；返回原始 JSON。**超时按请求下发**。"""
    url = f"{provider.base_url}/embeddings"
    client = get_client(provider.base_url, timeout=timeout)
    try:
        resp = client.post(
            url, headers=_headers(provider.api_key), json={"model": model, "input": texts},
            timeout=_request_timeout(timeout),
        )
    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.TransportError) as exc:
        raise dependency_unavailable(f"embedding 服务连接失败：{type(exc).__name__}") from exc
    _raise_for_status(resp)
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise dependency_unavailable("embedding 服务返回非 JSON 响应") from exc


def check_deadline(deadline_at, *, request_id: str = "") -> None:
    """在每次云调用前后校验全局 deadline（共享预算，不每层重新发）。"""
    from app.core.clock import is_expired

    if is_expired(deadline_at):
        raise deadline_exceeded("请求已超过全局 deadline")


__all__ = [
    "Provider",
    "TransportResult",
    "NO_RETRY_STATUS",
    "build_providers",
    "get_client",
    "close_clients",
    "chat_once",
    "embeddings_once",
    "check_deadline",
]
