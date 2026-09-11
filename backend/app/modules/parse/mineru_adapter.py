"""M02 — MinerU 适配器（REFACTOR_SPEC §5.2、§5.14、§6.4）。

职责：把 MinerU 精准解析结果转成本模块的 ``RawDocument``，并保证：

- 解析**已保存的同一份字节**：优先本地文件上传；若使用远程 URL，调用方必须能确认
  解析输入与 ``SourceDocument.sha256`` 相同，否则不用（见 ``parse_bytes`` 只接受 bytes）；
- **正确等待批任务终态**（不因 ``extract_result`` 非空就返回）；
- **ZIP 安全解包**：专用目录、限制路径穿越/展开总量/单项大小/条目数量；
- 原始 JSON/HTML 永不当指令执行；
- 保留 ``page_idx``（0-based）与 bbox 值及其单位声明，不假定 MinerU 固定单位；
- 保留 header/footer/page_number 块（不再丢弃）。
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from app.contracts.common import Warning
from app.core.config import settings
from app.core.errors import DomainError, ErrorCode, dependency_unavailable
from app.core.logging import get_logger

from .pymupdf_adapter import RawBlock, RawDocument, RawPage

log = get_logger(__name__)

ADAPTER_NAME = "mineru"
ADAPTER_VERSION = "v4"

#: ZIP 安全限制（§5.14）
MAX_ZIP_ENTRIES = 5000
MAX_ZIP_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ZIP_ENTRY_BYTES = 64 * 1024 * 1024
MAX_POLL_SECONDS = 600
POLL_INTERVAL = 4.0

_BASE = lambda: settings.mineru_base_url.rstrip("/")  # noqa: E731

#: MinerU content_list 的 type → 契约 BlockKind
_TYPE_KIND = {
    "text": "paragraph",
    "title": "heading",
    "table": "table",
    "equation": "equation",
    "image": "image",
    "chart": "image",
    "header": "header",
    "footer": "footer",
    "page_number": "page_number",
    "page_footnote": "footer",
    "list": "paragraph",
}

#: 不参与正文拼接但**保留**为块的类型
_META_KINDS = {"header", "footer", "page_number", "page_footnote"}


class MineruError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(settings.mineru_token) and settings.mineru_enabled


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.mineru_token}",
    }


# --------------------------------------------------------------- 提交/轮询


def _submit_by_bytes(data: bytes, filename: str, model_version: str = "vlm") -> str:
    r = httpx.post(
        f"{_BASE()}/api/v4/file-urls/batch",
        headers=_headers(),
        json={"files": [{"name": filename, "data_id": "researchlens"}],
              "model_version": model_version},
        timeout=60,
    )
    j = r.json()
    if j.get("code") != 0:
        raise MineruError(f"获取上传链接失败 {j.get('code')}")
    d = j.get("data") or {}
    batch_id = d.get("batch_id")
    urls = d.get("file_urls") or []
    if not urls or not batch_id:
        raise MineruError("未返回上传 URL 或 batch_id")
    put = httpx.put(urls[0], content=data, timeout=300)
    if put.status_code not in (200, 201):
        raise MineruError(f"文件上传失败 {put.status_code}")
    return f"batch:{batch_id}"


def _poll(task_ref: str, *, timeout: float = MAX_POLL_SECONDS) -> dict:
    """轮询直到**终态** done/failed；批任务必须等到条目自身 done。"""
    start = time.time()
    while time.time() - start < timeout:
        if task_ref.startswith("batch:"):
            bid = task_ref.split(":", 1)[1]
            r = httpx.get(f"{_BASE()}/api/v4/extract-results/batch/{bid}",
                          headers=_headers(), timeout=60)
            j = r.json()
            if j.get("code") != 0:
                raise MineruError(f"查询失败 {j.get('code')}")
            results = ((j.get("data") or {}).get("extract_result")) or []
            if not results:
                time.sleep(POLL_INTERVAL)
                continue
            first = results[0]
            state = first.get("state")
            if state == "done" and first.get("full_zip_url"):
                return first
            if state == "failed":
                raise MineruError(f"解析失败：{first.get('err_msg')}")
            # pending / running / done 但缺 zip：继续等待，绝不提前返回
            time.sleep(POLL_INTERVAL)
            continue

        r = httpx.get(f"{_BASE()}/api/v4/extract/task/{task_ref}",
                      headers=_headers(), timeout=60)
        j = r.json()
        if j.get("code") != 0:
            raise MineruError(f"查询失败 {j.get('code')}")
        d = j.get("data") or {}
        state = d.get("state")
        if state == "done":
            if not d.get("full_zip_url"):
                raise MineruError("任务完成但未返回结果 zip")
            return d
        if state == "failed":
            raise MineruError(f"解析失败：{d.get('err_msg')}")
        time.sleep(POLL_INTERVAL)
    raise MineruError("等待 MinerU 解析超时")


def _download_zip(url: str, *, retries: int = 3, backoff: float = 3.0) -> bytes:
    last: Optional[Exception] = None
    for i in range(retries):
        try:
            r = httpx.get(url, timeout=300)
            r.raise_for_status()
            content = r.content
            if len(content) > MAX_ZIP_TOTAL_BYTES:
                raise MineruError("结果 zip 超过允许体积")
            return content
        except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            log.warning("MinerU zip 下载失败(第 %d 次)", i + 1)
            time.sleep(backoff * (i + 1))
    raise MineruError(f"MinerU zip 下载失败：{type(last).__name__ if last else 'unknown'}")


# --------------------------------------------------------------- 安全解包


@dataclass
class SafeArchive:
    """受限解包结果：只保留必要的文本/JSON/图片条目。"""

    markdown: str = ""
    content_list: list = field(default_factory=list)
    images: dict = field(default_factory=dict)
    names: List[str] = field(default_factory=list)
    total_bytes: int = 0


def _is_unsafe_name(name: str) -> bool:
    if name.startswith("/") or name.startswith("\\"):
        return True
    if ".." in name.replace("\\", "/").split("/"):
        return True
    # Windows 盘符 / 反斜杠绝对路径
    if re.match(r"^[A-Za-z]:", name):
        return True
    return False


def safe_extract(zip_bytes: bytes) -> SafeArchive:
    """安全解包 MinerU 结果 zip（不落盘，限制条目数/单项/总量/路径）。"""
    if not zip_bytes:
        raise MineruError("空结果")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise MineruError("结果不是有效 ZIP") from exc

    archive = SafeArchive()
    entries = zf.infolist()
    if len(entries) > MAX_ZIP_ENTRIES:
        raise MineruError(f"ZIP 条目数超过上限（{len(entries)}）")

    total = 0
    for info in entries:
        if info.is_dir():
            continue
        name = info.filename
        if _is_unsafe_name(name):
            log.warning("跳过不安全 ZIP 路径：%s", name)
            continue
        if info.file_size > MAX_ZIP_ENTRY_BYTES:
            log.warning("跳过超大 ZIP 条目：%s (%d)", name, info.file_size)
            continue
        total += info.file_size
        if total > MAX_ZIP_TOTAL_BYTES:
            raise MineruError("ZIP 展开总量超过上限")
        archive.names.append(name)

        lowered = name.lower()
        try:
            if lowered.endswith("full.md"):
                archive.markdown = zf.read(info).decode("utf-8", "ignore")
            elif lowered.endswith("_content_list.json"):
                raw = json.loads(zf.read(info).decode("utf-8", "ignore"))
                if isinstance(raw, list):
                    archive.content_list = raw
            elif "/images/" in name or name.startswith("images/"):
                archive.images[name.split("/")[-1]] = zf.read(info)
        except Exception as exc:  # noqa: BLE001
            log.warning("读取 ZIP 条目失败 %s: %s", name, type(exc).__name__)

    archive.total_bytes = total
    return archive


# --------------------------------------------------------------- 归一


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(x) for x in value if x).strip()
    return str(value).strip()


def _kind_of(item: dict) -> str:
    return _TYPE_KIND.get(item.get("type", ""), "other")


def to_raw_document(archive: SafeArchive) -> RawDocument:
    """content_list → RawDocument；所有物理页保留，含空白/纯图页。"""
    warnings: List[Warning] = []
    by_page: dict = {}
    for item in archive.content_list:
        page_idx = item.get("page_idx")
        if page_idx is None:
            page_idx = 0
        try:
            page_idx = int(page_idx)
        except (TypeError, ValueError):
            page_idx = 0
        by_page.setdefault(page_idx, []).append(item)

    if not by_page:
        warnings.append(
            Warning(code="no_content_list", message="MinerU 结果缺少 content_list", stage="parse")
        )
        return RawDocument(warnings=warnings, parser_name=ADAPTER_NAME,
                           parser_version=ADAPTER_VERSION, full_text=archive.markdown)

    max_idx = max(by_page)
    pages: List[RawPage] = []
    for idx in range(max_idx + 1):
        items = by_page.get(idx, [])
        blocks: List[RawBlock] = []
        image_blocks: List[dict] = []
        ordinal = 0
        body_parts: List[str] = []
        for item in items:
            kind = _kind_of(item)
            text = _item_text(item, kind)
            bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else None
            block = RawBlock(
                kind=kind,
                text=text,
                bbox=[float(v) for v in bbox] if bbox and len(bbox) >= 4 else None,
                # MinerU 的 bbox 是 **0–1000 归一化网格**（官方 schema），不是像素。
                # 实测 823 个块的 x1/y1 最大值 991/998、最小值 122，与像素语义不符；
                # 此前声明 "pixel" 会让任何 "像素 ÷ 页面尺寸" 的裁剪计算全错
                # （且 MinerU 成功路径从不填 pages.width_pt，恒为 1.0）。
                bbox_units="normalized" if bbox else "unknown",
                ordinal=ordinal,
                # 表格：保留原始 HTML 与独立 caption（REFACTOR_SPEC §5.4 要求
                # Media.extracted.table_html 是真实 HTML；此前这里剥标签只剩纯文本，
                # 前端表格无法对齐、且 caption 与 body 粘连导致"同表双语 caption 重复"）。
                table_html=(item.get("table_body") or None) if kind == "table" else None,
                table_caption=(_as_text(item.get("table_caption")) or None)
                if kind == "table" else None,
            )
            blocks.append(block)
            ordinal += 1
            if kind in ("image",):
                image_blocks.append(
                    {
                        "img_path": item.get("img_path") or item.get("image_path") or "",
                        "bbox": block.bbox,
                        "caption": _caption_of(item),
                    }
                )
            if kind not in _META_KINDS and text:
                body_parts.append(text)

        full = "\n".join(body_parts).strip()
        quality = "text" if full else ("image_only" if image_blocks else "empty")
        pages.append(
            RawPage(
                pdf_page_index=idx,
                width_pt=0.0,   # MinerU 不保证给页面尺寸；由调用方用 PyMuPDF 补齐
                height_pt=0.0,
                rotation=0,
                cropbox_pdf=[0.0, 0.0, 0.0, 0.0],
                text=full,
                extraction_quality=quality,
                blocks=blocks,
                image_blocks=image_blocks,
            )
        )
    return RawDocument(
        pages=pages,
        page_count=len(pages),
        warnings=warnings,
        parser_name=ADAPTER_NAME,
        parser_version=ADAPTER_VERSION,
        full_text=archive.markdown,
    )


def _item_text(item: dict, kind: str) -> str:
    if kind == "table":
        caption = _as_text(item.get("table_caption"))
        body = re.sub(r"<[^>]+>", " ", item.get("table_body") or "")
        body = re.sub(r"\s+", " ", body).strip()
        return (caption + " " + body).strip()
    if kind == "image":
        return _caption_of(item)
    return _as_text(item.get("text"))


def _caption_of(item: dict) -> str:
    for key in ("chart_caption", "image_caption", "table_caption", "content"):
        value = _as_text(item.get(key))
        if value:
            return value
    return ""


def parse_bytes(data: bytes, *, filename: str = "paper.pdf") -> RawDocument:
    """完整 MinerU 流程：上传**已保存的同一份字节** → 轮询终态 → 安全解包 → 归一。

    任何失败抛 ``MineruError``，由 service 层降级到 PyMuPDF 并附 warning。
    """
    if not enabled():
        raise MineruError("未配置 MINERU_TOKEN 或已禁用")
    if not data:
        raise MineruError("无字节可解析")
    task_ref = _submit_by_bytes(data, filename)
    result = _poll(task_ref)
    zip_url = result.get("full_zip_url")
    if not zip_url:
        raise MineruError("未返回结果 zip")
    archive = safe_extract(_download_zip(zip_url))
    return to_raw_document(archive)


def mineru_tables(raw: RawDocument, content_list: list) -> List[dict]:
    """从 content_list 抽取表格候选（保留原始 HTML，不做有损矩阵截断）。"""
    tables: List[dict] = []
    for item in content_list:
        if item.get("type") != "table":
            continue
        body = item.get("table_body") or ""
        if not body:
            continue
        tables.append(
            {
                "caption": _as_text(item.get("table_caption")),
                "page_index": int(item.get("page_idx") or 0),
                "table_html": body,
                "footnote": _as_text(item.get("table_footnote")),
                "bbox": item.get("bbox"),
            }
        )
    return tables


__all__ = [
    "MineruError",
    "SafeArchive",
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "enabled",
    "safe_extract",
    "to_raw_document",
    "parse_bytes",
    "mineru_tables",
]
