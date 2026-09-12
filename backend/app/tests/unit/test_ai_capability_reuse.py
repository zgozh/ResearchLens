"""已观测到的模型能力必须被**复用**，不能每次重新撞（ADR-0053）。

真实缺陷（D-39 实测）：`ai/service.py` 只判断 `binding.json_schema is not None`，
**从不读** `caps.capabilities_for(model).json_schema`。于是
`caps.observe(model, json_schema=False)`（供应商拒绝 schema 时记下的）**永远是死数据**：

- 每次结构化调用都要重新撞最多 3 次 json_schema 失败、再回退 json_object；
- 实测 qwen3.6-plus 每次 `attempts=4`，且**第二次调用没有变快**（19.7/28.5/17.4s），
  直接证明能力没被复用；抽取单次因此从约 125s 变成 494s。

对 qwen-plus 无影响（它一次就接受 schema），所以这个缺陷只在"换模型"时才咬人——
但它让"换模型"这件事的代价被系统性放大，必须修。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_API_KEY", "")


def _request(snapshot_model: str):
    from pydantic import BaseModel

    from app.contracts.ai import ChatMessage, CompletionRequest, ModelSnapshot

    class _Out(BaseModel):
        answer: str = ""

    return CompletionRequest(
        messages=[ChatMessage(role="user", content="hi")],
        output_schema=_Out,
        model_snapshot=ModelSnapshot(id="s1", chat_model=snapshot_model),
    )


@pytest.fixture
def patched(monkeypatch):
    """把 transport 与能力表替换成受控实现，统计**实际发出的 response_format**。"""
    from app.contracts.ai import CompletionResult
    from app.modules.ai import capabilities as caps
    from app.modules.ai import service as ai_service

    sent: list = []

    def fake_chat_once(provider, body):  # noqa: ANN001
        sent.append(body.get("response_format"))
        fmt = body.get("response_format") or {}
        if fmt.get("type") == "json_schema":
            from app.core.errors import DomainError, ErrorCode

            # 供应商拒绝 schema：不可重试（与真实行为一致）
            raise DomainError(ErrorCode.INVALID_INPUT, "does not support json_schema",
                              retryable=False)
        return ai_service.transport.TransportResult(
            text='{"answer": "ok"}', model="m", usage={}, mode="json_object", attempts=1,
        )

    monkeypatch.setattr(ai_service.transport, "chat_once", fake_chat_once)
    # 单测里 LLM_API_KEY 被清空 → `_providers()` 返回空；这里注入一个假供应商，
    # 让流程走到 provider 循环（本测试关心的是**是否复用已观测能力**，不是鉴权）。
    monkeypatch.setattr(
        ai_service, "_providers",
        lambda: [ai_service.transport.Provider("k", "https://example.invalid/v1", "m")],
    )
    caps.reset_observed()
    return {"sent": sent, "caps": caps, "service": ai_service}


class TestObservedCapabilityIsReused:
    def test_second_call_skips_json_schema_after_observation(self, patched):
        """第一次撞失败并记录；**第二次必须直接走 json_object**（0 次白撞）。"""
        from app.contracts.common import Scope, new_ctx

        service = patched["service"]
        sent = patched["sent"]
        ctx = new_ctx(Scope(paper_id=1, revision_id="r"), snapshot={"id": "s1", "chat_model": "m"})

        service.complete(_request("m"), ctx)
        first_attempts = sent.count({"type": "json_schema", "json_schema": sent and None})  # noqa: E501
        schema_tries_first = sum(1 for f in sent if isinstance(f, dict) and f.get("type") == "json_schema")
        object_tries_first = sum(1 for f in sent if isinstance(f, dict) and f.get("type") == "json_object")
        assert schema_tries_first >= 1 and object_tries_first >= 1, \
            f"第一次应撞 schema 后回退 json_object：{sent}"

        sent.clear()
        service.complete(_request("m"), ctx)

        schema_tries = sum(1 for f in sent if isinstance(f, dict) and f.get("type") == "json_schema")
        object_tries = sum(1 for f in sent if isinstance(f, dict) and f.get("type") == "json_object")
        assert schema_tries == 0, \
            f"已观测到 JSON schema 不被接受，第二次不该再撞：{sent}"
        assert object_tries >= 1, "应直接走 json_object"
        _ = first_attempts

    def test_unknown_model_still_tries_schema_first(self, patched):
        """未观测过的模型仍应先试严格 json_schema（不好凭模型名猜能力）。"""
        from app.contracts.common import Scope, new_ctx

        service = patched["service"]
        sent = patched["sent"]
        ctx = new_ctx(Scope(paper_id=1, revision_id="r"), snapshot={"id": "s1", "chat_model": "m2"})

        service.complete(_request("m2"), ctx)

        assert any(isinstance(f, dict) and f.get("type") == "json_schema" for f in sent), \
            "未观测过的模型必须仍先试 strict json_schema"
