"""AIClient — OpenAI-compatible provider-agnostic LLM + Vision + Embeddings.

Decision D-06 / D-11: all model calls go through this single seam so we can
  1) route to a primary provider, 2) fall back across configured candidates,
  3) never crash the main path (degrade to cache/mock).
Uses plain httpx (no vendor SDK) so any OpenAI-compatible base_url works.
"""
from __future__ import annotations

import json
import logging
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
    def __init__(self) -> None:
        self._providers: List[_Provider] = self._build_providers()
        self._timeout = httpx.Timeout(120.0, connect=15.0)

    def _build_providers(self) -> List[_Provider]:
        providers: List[_Provider] = []
        if settings.has_llm:
            providers.append(_Provider(settings.llm_api_key, settings.llm_base_url.rstrip("/"), settings.llm_model))
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
        """Return parsed JSON if json_schema or json_object, else text. None on total failure.

        json_object mode is faster on providers where strict `json_schema` validation is slow;
        it asks the model for a JSON object and passes the schema as a prompt hint.
        """
        last_err = None
        for prov in self._providers:
            body: Dict[str, Any] = {"messages": messages, "temperature": temperature}
            if json_object:
                body["model"] = model or prov.model
                hint = ("请只输出符合该 JSON Schema 的 JSON：\n"
                        + json.dumps(json_schema or {}, ensure_ascii=False))
                body["response_format"] = {"type": "json_object"}
                try:
                    txt = self._chat_once(prov, {**body, "messages": messages + [{"role": "user", "content": hint}]})
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.warning("provider %s failed: %s", prov.base_url, e)
                    continue
                if txt is None:
                    continue
                return self._parse_json(txt, json_schema or {})
            if json_schema is not None:
                body["model"] = model or prov.model
                # try strict json_schema, then json_object fallback
                try:
                    fmt = {
                        "type": "json_schema",
                        "json_schema": {"name": "result", "strict": True, "schema": json_schema},
                    }
                    txt = self._chat_once(prov, {**body, "response_format": fmt})
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    log.info("json_schema rejected by %s (%s); falling back to json_object", prov.base_url, e)
                    txt = None
                if txt is None:
                    # json_object fallback: keep a hint of the schema in the prompt
                    hint = ("请只输出符合该 JSON Schema 的 JSON：\n"
                            + json.dumps(json_schema, ensure_ascii=False))
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
            else:
                body["model"] = model or prov.model
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

    def _chat_once(self, prov: _Provider, body: Dict[str, Any]) -> Optional[str]:
        payload = {**body, "model": body.get("model", prov.model)}
        r = httpx.post(
            f"{prov.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {prov.api_key}"},
            json=payload,
            timeout=self._timeout,
        )
        r.raise_for_status()
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        return (choices[0].get("message") or {}).get("content")

    def _parse_json(self, txt: str, schema: dict) -> Optional[Any]:
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            # tolerate content wrapped in markdown fences
            import re

            m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", txt, re.DOTALL)
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
