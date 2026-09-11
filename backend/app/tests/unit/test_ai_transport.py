"""AI 传输层：**每次请求必须带上自己声明的超时**。

真实缺陷（paper 1 claims 连续 ReadTimeout 的根因 / ADR-0008）：
``get_client`` 只用 ``base_url`` 做缓存 key，命中缓存时 ``timeout`` 参数被**静默丢弃**。
``index`` 阶段先跑 ``embeddings_once(timeout=60)`` 建好 client 并缓存，紧接着
``claims`` 阶段的 ``chat_once(timeout=300)`` 复用到同一个 client → **实际生效的
read timeout 是 60s**。paper 1 单次抽取稳定 >60s，于是 6 次尝试（json_schema 3 次 +
json_object 3 次）全部超时，claims 阶段耗时恰好 6×60 ≈ 360.8s 且产物为 0。

本文件锁死修复后的契约：``chat_once`` / ``embeddings_once`` 各自把
**按请求的 timeout** 传给 ``client.post``，从而不再依赖（也不受制于）缓存 client 的
构造超时。
"""
from __future__ import annotations

import os

os.environ.setdefault("LLM_API_KEY", "")

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.modules.ai import transport  # noqa: E402


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _RecordingClient:
    """记录 ``post`` 的调用参数，用来断言"按请求传超时"。"""

    def __init__(self, payload):
        self.calls = []
        self._payload = payload

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(self._payload)


@pytest.fixture
def provider():
    return transport.Provider("test-key", "https://dashscope.invalid/compatible-mode/v1", "qwen-plus")


def test_chat_once_sends_its_own_read_timeout(monkeypatch, provider):
    """claims 抽取的 300s 必须真正作用在这一次请求上。"""
    client = _RecordingClient(
        {"choices": [{"message": {"content": "ok"}}], "usage": {}, "model": "qwen-plus"}
    )
    monkeypatch.setattr(transport, "get_client", lambda base_url, **kw: client)

    transport.chat_once(provider, {"model": "qwen-plus", "messages": []})

    assert client.calls, "未发出请求"
    timeout = client.calls[0].get("timeout")
    assert timeout is not None, (
        "chat_once 必须按请求传 timeout；否则会继承缓存 client 的超时"
        "（index 阶段的 60s 会覆盖 claims 的 300s）"
    )
    assert timeout.read == 300.0, f"read timeout 应为 300s，实际 {timeout.read}"
    assert timeout.connect == 15.0, "connect 超时应保持独立且较短"


def test_chat_once_honours_explicit_timeout(monkeypatch, provider):
    client = _RecordingClient(
        {"choices": [{"message": {"content": "ok"}}], "usage": {}, "model": "m"}
    )
    monkeypatch.setattr(transport, "get_client", lambda base_url, **kw: client)

    transport.chat_once(provider, {"model": "m", "messages": []}, timeout=42.0)

    assert client.calls[0]["timeout"].read == 42.0


def test_embeddings_once_sends_its_own_read_timeout(monkeypatch, provider):
    """embedding 的 60s 也必须作用在它自己的请求上（不能被别处的长超时放大）。"""
    client = _RecordingClient({"data": []})
    monkeypatch.setattr(transport, "get_client", lambda base_url, **kw: client)

    transport.embeddings_once(provider, model="text-embedding-v3", texts=["x"])

    timeout = client.calls[0].get("timeout")
    assert timeout is not None, "embeddings_once 必须按请求传 timeout"
    assert timeout.read == 60.0, f"read timeout 应为 60s，实际 {timeout.read}"


def test_cached_client_does_not_override_per_request_timeout(monkeypatch, provider):
    """回归：先建 60s 的缓存 client，再用它发 300s 请求，实际必须仍是 300s。"""
    transport.close_clients()
    created = {}

    real_get_client = transport.get_client

    def factory(base_url, *, timeout=120.0):
        client = real_get_client(base_url, timeout=timeout)
        created["client"] = client
        return client

    monkeypatch.setattr(transport, "get_client", factory)

    # 模拟真实顺序：index 阶段先用 60s 建好并缓存 client
    factory(provider.base_url, timeout=60.0)
    cached = created["client"]
    assert cached.timeout.read == 60.0

    # 再用同一个缓存 client 发 claims 请求：按请求的 timeout 必须覆盖构造时的 60s
    recorded = {}

    def spy_post(url, **kwargs):
        recorded.update(kwargs)
        raise httpx.ReadTimeout("stop here", request=httpx.Request("POST", url))

    monkeypatch.setattr(cached, "post", spy_post)
    with pytest.raises(Exception):
        transport.chat_once(provider, {"model": "qwen-plus", "messages": []})

    assert recorded.get("timeout") is not None, "必须按请求传 timeout，不能依赖缓存 client 的超时"
    assert recorded["timeout"].read == 300.0, (
        f"缓存 client 的 60s 不得覆盖 claims 的 300s，实际 {recorded['timeout'].read}"
    )
    transport.close_clients()
