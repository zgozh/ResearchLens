"""M05 — 结构验证（REFACTOR_SPEC §5.6、§6.7）。

关键约束：``json_schema`` → ``json_object`` 回退后，**两者都必须用同一份
Pydantic schema 验证**。只做 "能 parse 成 JSON" 是不够的。

本模块负责：
- 从 ``SchemaRef`` / Pydantic 模型类解析出可用的 JSON Schema 与校验器；
- 解析模型输出（容忍 markdown 围栏）；
- 用 Pydantic 校验并给出结构化错误（不含原文大段内容）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Type

from pydantic import BaseModel, ValidationError

from app.contracts.ai import SchemaRef
from app.core.errors import invalid_input

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass
class SchemaBinding:
    """一次 schema 绑定：既提供 JSON Schema（发给供应商），也提供校验器。"""

    name: str
    version: str
    json_schema: Optional[dict]
    model: Optional[Type[BaseModel]]

    def validate(self, payload: Any) -> Any:
        if self.model is None:
            return payload
        return self.model.model_validate(payload)

    def errors(self, payload: Any) -> str:
        if self.model is None:
            return ""
        try:
            self.model.model_validate(payload)
            return ""
        except ValidationError as exc:
            return summarise(exc)


def summarise(exc: ValidationError) -> str:
    """只保留字段路径与原因，避免把大段模型输出写进错误/日志。"""
    parts = []
    for err in exc.errors()[:8]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def resolve_schema(ref: Any, *, default_name: str = "result") -> SchemaBinding:
    """把 ``SchemaRef`` / Pydantic 类 / dict 归一成 ``SchemaBinding``。"""
    if ref is None:
        return SchemaBinding(default_name, "1", None, None)

    if isinstance(ref, SchemaBinding):
        return ref

    if isinstance(ref, type) and issubclass(ref, BaseModel):
        return SchemaBinding(ref.__name__, "1", ref.model_json_schema(), ref)

    if isinstance(ref, SchemaRef):
        return SchemaBinding(ref.name, ref.version, None, None)

    # 允许显式 dict（受控调用方传入，不来自用户）
    if isinstance(ref, dict):
        return SchemaBinding(default_name, "1", ref, None)

    # 带 output_schema 属性的包装（部分调用方传自定义对象）
    inner = getattr(ref, "schema", None)
    if isinstance(inner, type) and issubclass(inner, BaseModel):
        return SchemaBinding(
            getattr(ref, "name", inner.__name__),
            getattr(ref, "version", "1"),
            inner.model_json_schema(),
            inner,
        )

    raise invalid_input("不支持的 output_schema 类型", field="output_schema")


def parse_json_text(text: str) -> Any:
    """解析模型输出；容忍 ```json 围栏。无法解析返回 ``None``。"""
    if text is None:
        return None
    raw = text.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = _FENCE.search(raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    # 退一步：截取最外层大括号
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def schema_hint(binding: SchemaBinding) -> str:
    """json_object 回退时把 schema 作为提示注入（不改变 system 角色边界）。"""
    if not binding.json_schema:
        return "请只输出一个 JSON 对象。"
    return (
        "请只输出符合以下 JSON Schema 的 JSON，不要输出任何解释文字：\n"
        + json.dumps(binding.json_schema, ensure_ascii=False)
    )


def json_schema_format(binding: SchemaBinding, name: str = "result") -> Optional[dict]:
    """构造 OpenAI 兼容的 ``response_format``（严格模式）。"""
    if not binding.json_schema:
        return None
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": binding.json_schema},
    }


__all__ = [
    "SchemaBinding",
    "resolve_schema",
    "parse_json_text",
    "schema_hint",
    "json_schema_format",
    "summarise",
]
