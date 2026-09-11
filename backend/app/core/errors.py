"""M00 — 类型化领域错误（REFACTOR_SPEC §5.1）。

约定：
- 服务函数失败抛 ``DomainError``（或子类），由 API 层统一映射为 HTTP。
- 可预期业务结果（例如证据被拒）**不**抛异常，放在 output 里。
- 不允许把完整外部报错回传用户（只保留摘要）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    CONFLICT = "CONFLICT"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    AMBIGUOUS_REFERENCE = "AMBIGUOUS_REFERENCE"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CANCELLED = "CANCELLED"
    # 业务结果类：通常不抛，仅用于流/任务终态与报告
    EVIDENCE_REJECTED = "EVIDENCE_REJECTED"


HTTP_STATUS: Dict[ErrorCode, int] = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.CONFLICT: 409,
    ErrorCode.REVISION_MISMATCH: 409,
    ErrorCode.AMBIGUOUS_REFERENCE: 409,
    ErrorCode.UNSUPPORTED_MEDIA: 415,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.DEADLINE_EXCEEDED: 504,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.CANCELLED: 500,  # 仅用于已建立的流/任务终态
    ErrorCode.EVIDENCE_REJECTED: 200,
}

# 明确可重试的错误码默认值（网络/依赖类）
_RETRYABLE_DEFAULT = {
    ErrorCode.DEPENDENCY_UNAVAILABLE,
    ErrorCode.DEADLINE_EXCEEDED,
    ErrorCode.RATE_LIMITED,
    ErrorCode.INTERNAL_ERROR,
}


@dataclass
class FieldError:
    path: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return {"path": self.path, "reason": self.reason}


class DomainError(Exception):
    """结构化领域错误。``message`` 不包含 token、绝对路径或论文大段原文。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: Optional[bool] = None,
        field_errors: Optional[List[FieldError]] = None,
        retry_after_ms: Optional[int] = None,
        request_id: str = "",
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = _RETRYABLE_DEFAULT.__contains__(code) if retryable is None else retryable
        self.field_errors: List[FieldError] = list(field_errors or [])
        self.retry_after_ms = retry_after_ms
        self.request_id = request_id
        self.__cause__ = cause

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    @property
    def legacy_detail(self) -> Any:
        """旧接口兼容：优先返回 FastAPI 风格的 detail。"""
        if self.field_errors:
            return [{"loc": ["body", fe.path], "msg": fe.reason, "type": "value_error"}
                    for fe in self.field_errors]
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "request_id": self.request_id,
            "field_errors": [fe.to_dict() for fe in self.field_errors],
            "retry_after_ms": self.retry_after_ms,
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"DomainError({self.code.value}, {self.message!r})"


# ---------------------------------------------------------------- 便捷构造


def not_found(message: str = "resource not found") -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, message)


def invalid_input(message: str, *, field: str | None = None) -> DomainError:
    fe = [FieldError(field, message)] if field else []
    return DomainError(ErrorCode.INVALID_INPUT, message, field_errors=fe)


def conflict(message: str) -> DomainError:
    return DomainError(ErrorCode.CONFLICT, message)


def revision_mismatch(message: str = "revision does not belong to paper") -> DomainError:
    return DomainError(ErrorCode.REVISION_MISMATCH, message)


def ambiguous(message: str = "reference is ambiguous") -> DomainError:
    return DomainError(ErrorCode.AMBIGUOUS_REFERENCE, message)


def forbidden(message: str = "forbidden") -> DomainError:
    return DomainError(ErrorCode.FORBIDDEN, message)


def unsupported_media(message: str = "unsupported media type") -> DomainError:
    return DomainError(ErrorCode.UNSUPPORTED_MEDIA, message)


def payload_too_large(message: str = "payload too large") -> DomainError:
    return DomainError(ErrorCode.PAYLOAD_TOO_LARGE, message)


def dependency_unavailable(message: str = "dependency unavailable") -> DomainError:
    return DomainError(ErrorCode.DEPENDENCY_UNAVAILABLE, message)


def deadline_exceeded(message: str = "deadline exceeded") -> DomainError:
    return DomainError(ErrorCode.DEADLINE_EXCEEDED, message)


def internal_error(message: str = "internal error") -> DomainError:
    return DomainError(ErrorCode.INTERNAL_ERROR, message)


def cancelled(message: str = "cancelled") -> DomainError:
    return DomainError(ErrorCode.CANCELLED, message)


__all__ = [
    "ErrorCode",
    "HTTP_STATUS",
    "FieldError",
    "DomainError",
    "not_found",
    "invalid_input",
    "conflict",
    "revision_mismatch",
    "ambiguous",
    "forbidden",
    "unsupported_media",
    "payload_too_large",
    "dependency_unavailable",
    "deadline_exceeded",
    "internal_error",
    "cancelled",
]
