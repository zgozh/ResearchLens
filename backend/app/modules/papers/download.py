"""M01 — 受控 URL 下载（REFACTOR_SPEC §6.3、§5.14 安全要求）。

威胁模型（工程约束，非渗透测试结论）：
- 仅允许 ``http`` / ``https``；
- 拒绝私网 / loopback / link-local / 保留段 / 云元数据地址（169.254.169.254 等）；
- **逐跳重定向重新校验**目标与 DNS 解析结果，防 DNS rebinding；限制跳数；
- 流式限体积（``settings.max_download_bytes``），超限立即中断；
- 默认公开部署使用允许域名单（``settings.allowed_source_hosts``）。

本模块在 **worker 中执行**：调用方不得在 HTTP 请求处理器同步等待下载。
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.errors import (
    DomainError,
    ErrorCode,
    forbidden,
    invalid_input,
    payload_too_large,
)
from app.core.logging import get_logger

log = get_logger(__name__)

#: 云元数据 / 特殊用途地址（即便解析成私网也需显式拒绝）
_BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
}

MAX_REDIRECTS = 5
_UA = "Mozilla/5.0 (ResearchLens)"
_DEFAULT_ACCEPT = "application/pdf,*/*"


@dataclass
class DownloadResult:
    """下载结果。``stream`` 为 bytes 列表（已按体积截断校验）。"""

    content: bytes
    final_url: str
    content_type: str = ""
    byte_size: int = 0
    redirects: List[str] = field(default_factory=list)


def _host_is_blocked(host: str) -> bool:
    lowered = (host or "").strip().lower().rstrip(".")
    if not lowered:
        return True
    if lowered in _BLOCKED_HOSTNAMES:
        return True
    # 纯 IP 直接判断；域名解析后仍需逐个判断（见 `_resolve_and_check`）
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return _ip_is_blocked(ip)


def _ip_is_blocked(ip: "ipaddress._BaseAddress | str") -> bool:
    """私网 / loopback / link-local / 保留 / 组播 / 未指定 一律拒绝。

    接受 ``IPv4Address``/``IPv6Address`` 或字符串形式；字符串无法解析时视为被阻断
    （fail-closed，绝不因解析失败而放行）。
    """
    if isinstance(ip, str):
        try:
            ip = ipaddress.ip_address(ip.strip().strip("[]"))
        except ValueError:
            return True
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return True
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    if isinstance(ip, ipaddress.IPv4Address):
        # 云元数据链路本地段再做一次显式拒绝
        if ip == ipaddress.ip_address("169.254.169.254"):
            return True
        # 0.0.0.0/8、100.64.0.0/10（CGNAT）、192.0.0.0/24 等由 is_* 覆盖不全时兜底
        if ip in ipaddress.ip_network("100.64.0.0/10"):
            return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _ip_is_blocked(ip.ipv4_mapped)
    return False


def _resolve_and_check(host: str) -> None:
    """解析 DNS 并校验**所有**返回地址（防 DNS rebinding / 多 A 记录绕过）。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise DomainError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"无法解析主机 {host}",
            retryable=True,
            cause=exc,
        ) from exc
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            raise forbidden(f"目标地址被拒绝（解析到受限网段）：{addr}")


def validate_url(url: str, *, allowed_hosts: Optional[List[str]] = None) -> str:
    """校验一次性 URL 字符串；返回规范化后的 URL。失败抛 DomainError。"""
    raw = (url or "").strip()
    if not raw:
        raise invalid_input("URL 不能为空", field="url")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise invalid_input("仅支持 http/https URL", field="url")
    if parsed.username or parsed.password:
        raise invalid_input("URL 不允许携带访问凭据", field="url")
    host = parsed.hostname or ""
    if not host:
        raise invalid_input("URL 缺少主机名", field="url")
    if _host_is_blocked(host):
        raise forbidden("目标主机被拒绝（私网/loopback/元数据地址）")

    allow = allowed_hosts if allowed_hosts is not None else settings.allowed_source_hosts
    if allow:
        lowered = host.lower()
        if not any(lowered == h.lower() or lowered.endswith("." + h.lower()) for h in allow):
            raise forbidden("目标主机不在允许来源名单内")

    _resolve_and_check(host)
    return raw


def strip_credentials(url: Optional[str]) -> Optional[str]:
    """去掉 query 中的访问凭据（token/signature 等），不持久化到 DB。"""
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.query:
        return url
    sensitive = {"token", "access_token", "signature", "sig", "key", "apikey", "api_key",
                 "x-amz-signature", "x-amz-credential", "auth", "password"}
    kept = [
        piece
        for piece in parsed.query.split("&")
        if piece and piece.split("=", 1)[0].lower() not in sensitive
    ]
    clean = parsed._replace(query="&".join(kept))
    return clean.geturl()


def fetch(
    url: str,
    *,
    max_bytes: Optional[int] = None,
    timeout: float = 60.0,
    allowed_hosts: Optional[List[str]] = None,
) -> DownloadResult:
    """流式下载；**每一跳**都重新校验 host/IP。超限或校验失败抛 DomainError。"""
    limit = max_bytes if max_bytes is not None else settings.max_download_bytes
    current = validate_url(url, allowed_hosts=allowed_hosts)
    redirects: List[str] = []
    header: dict = {}

    for _hop in range(MAX_REDIRECTS + 1):
        with httpx.Client(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout, connect=15.0),
            headers={"User-Agent": _UA, "Accept": _DEFAULT_ACCEPT, **header},
        ) as client:
            with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        raise DomainError(
                            ErrorCode.DEPENDENCY_UNAVAILABLE, "重定向缺少 Location", retryable=True
                        )
                    nxt = httpx.URL(current).join(location)
                    current = validate_url(str(nxt), allowed_hosts=allowed_hosts)
                    redirects.append(current)
                    if len(redirects) > MAX_REDIRECTS:
                        raise DomainError(
                            ErrorCode.DEPENDENCY_UNAVAILABLE,
                            f"重定向次数超过上限（{MAX_REDIRECTS}）",
                            retryable=False,
                        )
                    continue
                if resp.status_code >= 400:
                    raise DomainError(
                        ErrorCode.DEPENDENCY_UNAVAILABLE,
                        f"下载失败：HTTP {resp.status_code}",
                        retryable=resp.status_code >= 500,
                    )
                content_type = resp.headers.get("content-type", "")
                # 若服务端声明为 HTML 但内容非 PDF，仍允许由调用方做魔数校验拒绝
                buf = bytearray()
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    if limit and len(buf) > limit:
                        raise payload_too_large(f"下载内容超过最大体积（{limit} 字节）")
                return DownloadResult(
                    content=bytes(buf),
                    final_url=current,
                    content_type=content_type,
                    byte_size=len(buf),
                    redirects=redirects,
                )
    raise DomainError(ErrorCode.DEPENDENCY_UNAVAILABLE, "重定向处理异常", retryable=False)


__all__ = [
    "DownloadResult",
    "MAX_REDIRECTS",
    "validate_url",
    "strip_credentials",
    "fetch",
]
