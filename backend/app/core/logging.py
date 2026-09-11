"""M00 — 日志（§5.14：日志只存 ID/hash/摘要错误，禁止记录 token 与原文大段内容）。"""
from __future__ import annotations

import logging
import re
import sys

_REDACT_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|authorization|secret)\s*[=:]\s*[\"']?([^\s\"',}]{6,})"),
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
]


def redact(text: str) -> str:
    """抹掉疑似凭据。用于任何面向日志/响应的字符串。"""
    if not text:
        return text
    out = text
    for pat in _REDACT_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(lambda m: f"{m.group(1)}=***", out)
        else:
            out = pat.sub("***", out)
    return out


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            record.msg = redact(str(record.msg))
        except Exception:  # noqa: BLE001
            pass
        return True


_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    handler.addFilter(_RedactFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


__all__ = ["redact", "configure_logging", "get_logger"]
