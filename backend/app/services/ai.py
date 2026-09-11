"""AIClient — 兼容薄壳（REFACTOR_SPEC §6.7：保留旧签名，不替换供应商）。

**旧类 ``AIClient`` 与 ``get_ai()`` 的公开签名保持不变**，旧调用方
（``services/pipeline.py``、``services/qa.py``、``modules/pipeline/ingest.py``）
继续可用。

新增能力（类型验证、预算共享、能力探测、模型快照）在
``app.modules.ai`` 中提供；本类的结构化调用可选转发到那里，但**保留原有
``Optional`` 返回与"永不抛异常到主链路"的旧契约**（旧调用方按 None 判空）。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

log = logging.getLogger("researchlens.ai")


@dataclass
class _Provider:
    api_key: str
    base_url: str
    model: str


class AIClient:
    """旧 AIClient（签名向后兼容）。"""

    def __init__(self) -> None:
        self._providers: List[_Provider] = self._build_providers()
        self._timeout = httpx.Timeout(120.0, connect=15.0)

    def _build_providers(self) -> List[_Provider]:
        providers: List[_Provider] = []
        if settings.has_llm:
            providers.append(
                _Provider(settings.llm_api_key, settings.llm_base_url.rstrip("/"),
                          settings.llm_model)
            )
        for item in filter(None, (s for s in settings.llm_fallbacks.split(",") if s.strip())):
            try:
                key_url, model = item.rsplit("|", 1)
                key, url = key_url.split("@", 1)
                providers.append(_Provider(key.strip(), url.strip().rstrip("/"), model.strip()))
            except ValueError:
                continue
        return providers

    @property
    def ready(self) -> bool:
        return bool(self._providers)

    # --- chat / structured output ---
    def complete(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        json_schema: Optional[dict] = None,
        json_object: bool = False,
    ) -> Optional[Any]:
        """旧契约：返回解析后的 JSON 或文本；失败返回 ``None``（不抛异常）。

        ``json_object`` 模式请求 JSON 对象并把 schema 作为提示注入。
        """
        last_err = None
        for prov in self._providers:
            body: Dict[str, Any] = {"messages": messages, "temperature": temperature}
            if json_object:
                body["model"] = model or self._resolve_model(prov)
                hint = ("请只输出符合该 JSON Schema 的 JSON：\n"
                        + __import__("json").dumps(json_schema or {}, ensure_ascii=False))
                body["response_format"] = {"type": "json_object"}
                try:
                    txt = self._chat_once(prov, {**body, "messages": messages +
                                                 [{"role": "user", "content": hint}]})
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.warning("provider %s failed: %s", prov.base_url, e)
                    continue
                if txt is None:
                    continue
                return self._parse_json(txt, json_schema or {})
            if json_schema is not None:
                body["model"] = model or self._resolve_model(prov)
                try:
                    fmt = {
                        "type": "json_schema",
                        "json_schema": {"name": "result", "strict": True, "schema": json_schema},
                    }
                    txt = self._chat_once(prov, {**body, "response_format": fmt})
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.info("json_schema rejected by %s; falling back to json_object",
                             prov.base_url)
                    txt = None
                if txt is None:
                    hint = ("请只输出符合该 JSON Schema 的 JSON：\n"
                            + __import__("json").dumps(json_schema, ensure_ascii=False))
                    fb_body = {
                        **body,
                        "response_format": {"type": "json_object"},
                        "messages": messages + [{"role": "user", "content": hint}],
                    }
                    try:
                        txt = self._chat_once(prov, fb_body)
                    except Exception as e2:  # noqa: BLE001
                        last_err = e2
                        continue
                if txt is None:
                    continue
                return self._parse_json(txt, json_schema)
            body["model"] = model or self._resolve_model(prov)
            try:
                txt = self._chat_once(prov, body)
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("provider %s failed: %s", prov.base_url, e)
                continue
            if txt is None:
                continue
            return txt
        if last_err:
            log.error("all providers failed: %s", last_err)
        return None

    def _resolve_model(self, prov: _Provider) -> str:
        """优先级：调用方显式 model > 运行时选择的模型 > Provider 默认模型。"""
        from app.core.runtime import get_active_model
        return get_active_model() or prov.model

    def _chat_once(self, prov: _Provider, body: Dict[str, Any], _retry: int = 2) -> Optional[str]:
        payload = {**body, "model": body.get("model", prov.model)}
        last: Optional[Exception] = None
        for attempt in range(_retry + 1):
            try:
                r = httpx.post(
                    f"{prov.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {prov.api_key}"},
                    json=payload,
                    timeout=self._timeout,
                )
                # 401/403 不重试（§6.7）
                if r.status_code in (401, 403):
                    log.warning("provider %s 鉴权失败 %d", prov.base_url, r.status_code)
                    return None
                r.raise_for_status()
                data = r.json()
                choices = data.get("choices") or []
                if not choices:
                    return None
                return (choices[0].get("message") or {}).get("content")
            except (httpx.ReadTimeout, httpx.ConnectError, httpx.TransportError) as e:
                last = e
                log.warning("provider %s 第 %d 次调用失败：%s", prov.base_url, attempt + 1, e)
        if last:
            raise last
        return None

    def _parse_json(self, txt: str, schema: dict) -> Optional[Any]:
        import json

        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            m = __import__("re").search(r"```(?:json)?\s*(\{.*\})\s*```", txt, __import__("re").DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    return None
            return None

    # --- embeddings (RAG, LIVE only) ---
    def embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        if not self._providers:
            return None
        prov = self._providers[0]
        try:
            r = httpx.post(
                f"{prov.base_url}/embeddings",
                headers={"Authorization": f"Bearer {prov.api_key}"},
                json={"model": settings.embedding_model, "input": texts},
                timeout=self._timeout,
            )
            r.raise_for_status()
            data = r.json()
            return [d["embedding"] for d in data["data"]]
        except Exception as e:  # noqa: BLE001
            log.warning("embedding failed: %s", e)
            return None

    # --- vision ---
    def vision(self, prompt: str, image_url: str, *, model: Optional[str] = None) -> Optional[str]:
        if not self._providers:
            return None
        prov = self._providers[0]
        body = {
            "model": model or settings.vision_model or prov.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
        }
        try:
            txt = self._chat_once(prov, body)
        except Exception as e:  # noqa: BLE001
            log.warning("vision failed: %s", e)
            return None
        return txt


_client: Optional[AIClient] = None


def get_ai() -> AIClient:
    global _client
    if _client is None:
        _client = AIClient()
    return _client


__all__ = ["AIClient", "get_ai"]
