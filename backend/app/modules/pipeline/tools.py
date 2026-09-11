"""M11 — Agent 工具白名单与 scope 强制（REFACTOR_SPEC §5.8、§6.13）。

工具只有五个：``retrieve_blocks / get_blocks / get_media / validate_statement /
submit_candidate``。**不含任意 I/O 工具**。

每个调用都：
1. 校验角色权限（``TOOL_PERMISSIONS``）；
2. **强制 scope**：args.scope 必须与 ctx.scope 完全一致，禁止模型把检索
   扩展到其他论文/其他 revision；
3. 返回 ``ToolResult``：超权/越界是 ``rejected``，依赖失败是 ``error``，
   绝不把异常抛给模型循环。

``submit_candidate`` **只提交候选，永不发布**。
"""
from __future__ import annotations

from typing import Any, Optional

from app.contracts.common import CallContext, Scope
from app.contracts.evidence import StatementDraft
from app.contracts.jobs import TOOL_PERMISSIONS, ToolCall, ToolResult
from app.contracts.retrieval import RetrievalRequest
from app.core.errors import DomainError, ErrorCode, forbidden, invalid_input


def dispatch(call: ToolCall, ctx: CallContext) -> ToolResult:
    """执行一个工具调用并返回受控结果。"""
    if not isinstance(call, ToolCall):
        raise invalid_input("call 必须为 ToolCall", field="call")

    if call.name not in TOOL_PERMISSIONS:
        return _rejected(call, f"未知工具 {call.name}")

    roles = TOOL_PERMISSIONS[call.name]
    if call.role not in roles:
        return _rejected(call, f"角色 {call.role} 无权调用 {call.name}")

    scope_check = _resolve_scope(call, ctx)
    if isinstance(scope_check, ToolResult):
        return scope_check
    scope = scope_check

    if ctx.is_cancelled():
        return _rejected(call, "已请求取消，不再发起工具调用")

    try:
        payload = _run(call, scope, ctx)
    except DomainError as exc:
        return ToolResult(call_id=call.id, status="error", payload=None, error=exc.to_dict())
    except Exception as exc:  # noqa: BLE001
        return ToolResult(
            call_id=call.id, status="error", payload=None,
            error={"code": ErrorCode.INTERNAL_ERROR.value,
                   "message": f"工具执行失败：{type(exc).__name__}"},
        )

    if payload is None:
        return _rejected(call, "工具参数不完整")
    return ToolResult(call_id=call.id, status="ok", payload=payload)


def _resolve_scope(call: ToolCall, ctx: CallContext):
    """解析并强制工具 scope == 上下文 scope（禁止跨论文扩展检索）。"""
    args_scope = call.args.scope if call.args else None
    ctx_scope = ctx.scope

    if call.name == "retrieve_blocks" and call.args and call.args.retrieval is not None:
        args_scope = call.args.retrieval.scope or args_scope

    if args_scope is None:
        if ctx_scope is None:
            return _rejected(call, "缺少 scope，工具拒绝执行")
        return ctx_scope

    if ctx_scope is not None and (
        args_scope.paper_id != ctx_scope.paper_id
        or args_scope.revision_id != ctx_scope.revision_id
    ):
        return _rejected(call, "工具 scope 与上下文不一致：禁止扩展到其他论文/revision")
    return args_scope


def _run(call: ToolCall, scope: Scope, ctx: CallContext) -> Any:
    args = call.args
    if call.name == "retrieve_blocks":
        from app.contracts.retrieval import RetrievalRequest
        from app.modules import retrieval as retrieval_mod

        request = args.retrieval
        if request is None:
            # 未提供检索请求时，用受控默认查询，不接受模型任意构造的范围
            request = RetrievalRequest(scope=scope, query="原文")
        request = request.model_copy(update={"scope": scope})
        return retrieval_mod.retrieve(request, ctx)

    if call.name == "get_blocks":
        from app.modules import parse as parse_mod

        if not args.block_ids:
            return None
        return parse_mod.get_blocks(scope, list(args.block_ids))

    if call.name == "get_media":
        from app.modules import visual as visual_mod

        if not args.media_ids:
            return None
        return visual_mod.get_media(scope, list(args.media_ids))

    if call.name == "validate_statement":
        from app.modules import evidence as evidence_mod

        draft = args.statement
        if draft is None:
            return None
        draft = _bind_scope(draft, scope)
        return evidence_mod.validate(draft, ctx)

    if call.name == "submit_candidate":
        from app.modules import claims as claims_mod

        draft = args.statement
        if draft is None:
            return None
        draft = _bind_scope(draft, scope)
        # 只注册**候选身份**（unverified），永不发布、永不产生 evidence
        claims_mod.register_statement(draft, "answer_only", ctx)
        return draft

    return None


def _bind_scope(draft: StatementDraft, scope: Scope) -> StatementDraft:
    if draft.scope.paper_id == scope.paper_id and draft.scope.revision_id == scope.revision_id:
        return draft
    return draft.model_copy(update={"scope": scope})


def _rejected(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(
        call_id=call.id, status="rejected", payload=None,
        error={"code": ErrorCode.FORBIDDEN.value, "message": message},
    )


__all__ = ["dispatch"]
