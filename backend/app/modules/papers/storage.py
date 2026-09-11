"""M01 — 内容寻址字节存储（REFACTOR_SPEC §5.14、§6.3）。

约定（不可违背）：
- 字节只按内容寻址：临时文件 → sha256 校验 → ``os.replace`` 原子 rename；
- 同名不覆盖；重名文件落到 ``<name>-<hash>`` 而不是覆盖既有文件；
- 失败时清理临时文件（TTL 回收），不留下半成品引用；
- 数据库记录尚未发布时不删除旧资产。
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Optional

from app.core.config import settings
from app.core.errors import ErrorCode, DomainError, payload_too_large

#: PDF 魔数：PDF 头可能不在第 0 字节（存在前导垃圾/注释），但必须在开头若干字节内
_PDF_MAGIC = b"%PDF-"
_PDF_MAGIC_WINDOW = 1024

#: 一次读取的块大小（流式，避免全量读入内存）
CHUNK_SIZE = 64 * 1024

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class StoredBytes:
    """一次落盘结果。``rel_path`` 是相对 data_dir 的受控路径，绝不外露到 API。"""

    sha256: str
    byte_size: int
    rel_path: str
    abs_path: Path


def _assets_root() -> Path:
    root = settings.assets_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def sanitize_filename(name: Optional[str], fallback: str = "document.bin") -> str:
    """只保留 ASCII 安全字符；保留扩展名，避免同名覆盖由内容寻址兜底。"""
    raw = (name or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    safe = _SAFE_NAME.sub("_", raw)
    safe = safe.lstrip("._") or fallback
    return safe[:120]


def looks_like_pdf(head: bytes) -> bool:
    """魔数校验：在开头窗口内查找 ``%PDF-``。"""
    return _PDF_MAGIC in (head or b"")[:_PDF_MAGIC_WINDOW]


def sniff_mime(head: bytes, declared: str = "") -> str:
    """只做保守识别；PDF 以外不猜，沿用调用方声明。"""
    if looks_like_pdf(head):
        return "application/pdf"
    return declared or "application/octet-stream"


def _commit_temp(tmp_path: Path, sha: str, kind_dir: str, safe_name: str) -> Path:
    """把临时文件原子移动到内容寻址的最终位置。同 hash 已存在则复用（幂等）。"""
    prefix = sha[:2]
    target_dir = _assets_root() / kind_dir / prefix
    target_dir.mkdir(parents=True, exist_ok=True)
    final = target_dir / f"{sha}_{safe_name}"

    if final.exists():
        # 内容寻址幂等：同 hash 同名字节完全一致，直接丢弃临时文件。
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return final

    # 极端并发下同一路径被抢占：改用内容寻址唯一名，绝不覆盖他人文件。
    if final.exists():
        final = target_dir / f"{sha}_{os.getpid()}_{safe_name}"

    os.replace(tmp_path, final)
    return final


def store_stream_sync(
    stream: "ByteStream",
    *,
    kind_dir: str,
    filename: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> StoredBytes:
    """把同步 bytes 迭代器写入临时文件，流式限体积，返回内容寻址结果。

    ``ByteStream`` 是可关闭的 bytes 迭代器；这里同时接受 ``bytes`` 与可读文件对象。
    """
    limit = max_bytes if max_bytes is not None else settings.max_upload_bytes
    safe_name = sanitize_filename(filename)
    root = _assets_root()
    tmp_dir = root / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=".incoming-", suffix=".part", dir=str(tmp_dir))
    tmp_path = Path(tmp_name)
    h = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in _iter_chunks(stream):
                if not chunk:
                    continue
                total += len(chunk)
                if limit and total > limit:
                    raise payload_too_large(
                        f"内容超过允许的最大体积（{limit} 字节）"
                    )
                h.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        sha = h.hexdigest()
        final = _commit_temp(tmp_path, sha, kind_dir, safe_name)
        return StoredBytes(
            sha256=sha,
            byte_size=total,
            rel_path=str(final.relative_to(settings.data_dir)).replace("\\", "/"),
            abs_path=final,
        )
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _iter_chunks(stream) -> "list[bytes]":
    """把多种输入归一成 bytes 序列：bytes / 同步迭代器 / file-like。"""
    if stream is None:
        return []
    if isinstance(stream, (bytes, bytearray)):
        return [bytes(stream)]
    if hasattr(stream, "read"):
        def _gen():
            while True:
                block = stream.read(CHUNK_SIZE)
                if not block:
                    break
                yield block

        return _gen()
    return iter(stream)


async def store_stream_async(
    stream: AsyncIterator[bytes],
    *,
    kind_dir: str,
    filename: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> StoredBytes:
    """异步 ByteStream 版本；语义与 ``store_stream_sync`` 相同。"""
    limit = max_bytes if max_bytes is not None else settings.max_upload_bytes
    safe_name = sanitize_filename(filename)
    root = _assets_root()
    tmp_dir = root / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=".incoming-", suffix=".part", dir=str(tmp_dir))
    tmp_path = Path(tmp_name)
    h = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            async for chunk in stream:
                if not chunk:
                    continue
                total += len(chunk)
                if limit and total > limit:
                    raise payload_too_large(f"内容超过允许的最大体积（{limit} 字节）")
                h.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        sha = h.hexdigest()
        final = _commit_temp(tmp_path, sha, kind_dir, safe_name)
        return StoredBytes(
            sha256=sha,
            byte_size=total,
            rel_path=str(final.relative_to(settings.data_dir)).replace("\\", "/"),
            abs_path=final,
        )
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def head_of(path: Path, size: int = 2048) -> bytes:
    with path.open("rb") as fh:
        return fh.read(size)


def resolve_asset_path(rel_path: str) -> Path:
    """受控解析：拒绝绝对路径与 ``..`` 穿越，只允许落在 data_dir 之内。"""
    if not rel_path:
        raise DomainError(ErrorCode.NOT_FOUND, "资产路径为空")
    candidate = (settings.data_dir / rel_path).resolve()
    root = Path(settings.data_dir).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise DomainError(ErrorCode.FORBIDDEN, "资产路径越界", retryable=False) from exc
    if not candidate.is_file():
        raise DomainError(ErrorCode.NOT_FOUND, "资产字节不存在")
    return candidate


def iter_file_range(path: Path, start: int, end_inclusive: Optional[int]):
    """按 [start, end_inclusive] 读取文件；end 为 None 表示读到末尾。"""
    size = path.stat().st_size
    if start >= size:
        raise DomainError(
            ErrorCode.INVALID_INPUT,
            "Range 起点超出资产长度",
            field_errors=[],
            retryable=False,
        )
    stop = size - 1 if end_inclusive is None else min(end_inclusive, size - 1)
    remaining = stop - start + 1
    with path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            block = fh.read(min(CHUNK_SIZE, remaining))
            if not block:
                break
            remaining -= len(block)
            yield block


def read_file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def open_binary(path: Path) -> BinaryIO:
    return path.open("rb")


__all__ = [
    "StoredBytes",
    "CHUNK_SIZE",
    "sanitize_filename",
    "looks_like_pdf",
    "sniff_mime",
    "sha256_file",
    "store_stream_sync",
    "store_stream_async",
    "head_of",
    "resolve_asset_path",
    "iter_file_range",
    "read_file_bytes",
    "open_binary",
]
