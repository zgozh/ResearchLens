"""M00 — 安全原语（§5.14）。

覆盖：
- 管理凭据校验（``require_admin``）→ ``Actor``
- 外部 URL 准入（限 http/https、拒凭据/私网/loopback/link-local/云元数据、防 DNS rebinding）
- 文件路径穿越防护
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List
from urllib.parse import urlparse

from .config import settings
from .errors import DomainError, ErrorCode, forbidden, invalid_input, not_found

# 云元数据地址（AWS/GCP/Azure/阿里云）——任何情况下都不允许访问
_BLOCKED_HOSTS = {
    "169.254.169.254",       # AWS/GCP/Azure IMDS
    "metadata.google.internal",
    "100.100.100.200",       # 阿里云元数据
    "fd00:ec2::254",
}

_ALLOWED_SCHEMES = {"http", "https"}


@dataclass(frozen=True)
class Actor:
    """调用者身份。``reviewer`` 一律从认证上下文取，不信任请求自报。"""

    name: str = "anonymous"
    is_admin: bool = False


ANONYMOUS = Actor(name="anonymous", is_admin=False)


def require_admin(credential: str | None) -> Actor:
    """校验管理凭据。未配置 ADMIN_TOKEN 且非公开部署时，本地演示放行。"""
    if settings.admin_token:
        if credential and _constant_eq(credential, settings.admin_token):
            return Actor(name="admin", is_admin=True)
        raise forbidden("需要管理凭据（X-Admin-Token）")
    if settings.public_deployment:
        # 公开部署必须配置 token，否则一律拒绝（配置校验已提前失败，这里是兜底）
        raise forbidden("公开部署未配置 ADMIN_TOKEN，管理操作已禁用")
    return Actor(name="local-admin", is_admin=True)


def _constant_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a.encode(), b.encode()):
        diff |= x ^ y
    return diff == 0


# ------------------------------------------------------------------ URL


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def resolve_host_ips(host: str, port: int | None = None) -> List[str]:
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:  # noqa: BLE001
        raise invalid_input(f"无法解析主机名：{host}") from exc
    return sorted({info[4][0] for info in infos})


def assert_url_allowed(url: str, *, allowed_hosts: Iterable[str] | None = None) -> str:
    """校验外部 URL 准入，返回规范化后的 URL。

    注意：DNS 校验必须在**每次实际连接前**执行（含每次重定向），
    调用方需在连接后再次用 ``assert_connected_ip_allowed`` 校验真实对端 IP。
    """
    if not url or not isinstance(url, str):
        raise invalid_input("URL 为空")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise invalid_input("仅支持 http/https 链接", field="url")
    if parsed.username or parsed.password:
        raise invalid_input("URL 不得包含访问凭据", field="url")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise invalid_input("URL 缺少主机名", field="url")
    if host in _BLOCKED_HOSTS:
        raise invalid_input("目标主机不可访问", field="url")

    allow_list = [h.lower() for h in (allowed_hosts if allowed_hosts is not None
                                      else settings.allowed_source_hosts)]
    if allow_list and host not in allow_list:
        raise invalid_input("目标主机不在允许列表内", field="url")

    for ip_text in resolve_host_ips(host, parsed.port):
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if _is_blocked_ip(ip) or ip_text in _BLOCKED_HOSTS:
            raise invalid_input("目标地址为内网/保留地址，已拒绝", field="url")
    return url.strip()


def assert_connected_ip_allowed(ip_text: str) -> None:
    """下载器在真实建连后调用，防止 DNS rebinding。"""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError as exc:
        raise invalid_input("连接地址非法") from exc
    if _is_blocked_ip(ip) or str(ip) in _BLOCKED_HOSTS:
        raise invalid_input("实际连接地址为内网/保留地址，已拒绝")


# ------------------------------------------------------------------ path


def ensure_within(root: Path, candidate: Path) -> Path:
    """路径穿越防护：解析后必须落在 root 之内。"""
    root_r = Path(root).resolve()
    cand_r = Path(candidate).resolve()
    try:
        cand_r.relative_to(root_r)
    except ValueError as exc:
        raise DomainError(ErrorCode.INVALID_INPUT, "路径越界，已拒绝") from exc
    return cand_r


def safe_filename(name: str, *, fallback: str = "file.bin") -> str:
    """剥掉目录部分与危险字符，避免同名覆盖/路径穿越。"""
    raw = (name or "").replace("\\", "/").split("/")[-1].strip()
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "._- ()[]")
    cleaned = cleaned.strip(". ") or fallback
    return cleaned[:120]


def open_asset_stream(path: Path, root: Path) -> Path:
    """打开前确认资产在受控根目录内且存在。"""
    resolved = ensure_within(root, path)
    if not resolved.is_file():
        raise not_found("资产不存在")
    return resolved


__all__ = [
    "Actor",
    "ANONYMOUS",
    "require_admin",
    "resolve_host_ips",
    "assert_url_allowed",
    "assert_connected_ip_allowed",
    "ensure_within",
    "safe_filename",
    "open_asset_stream",
]
