"""services/mineru — 兼容薄壳（REFACTOR_SPEC §6.4：旧签名代理）。

**保留原有全部公共函数名与签名**，可迁移部分转发到
``app.modules.parse.mineru_adapter``（安全的 ZIP 解包、终态轮询、保留
header/footer/page_number 块）。

新代码请使用 ``app.modules.parse.parse``（MinerU 优先、PyMuPDF 降级，产出
契约 DTO）。本模块继续返回旧 dict IR，供 ``modules/pipeline/ingest.py`` 等
历史调用方使用。

# legacy: 旧返回结构（full_text/pages/figures/tables）保留；新 canonical
# 产物请走 app.modules.parse。两套并存期间不删除旧函数。
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
import zipfile
from typing import Dict, List, Optional

import httpx

from app.core.config import settings

log = logging.getLogger("researchlens.mineru")

_BASE = settings.mineru_base_url.rstrip("/")

HEADERS = lambda: {"Content-Type": "application/json", "Authorization": f"Bearer {settings.mineru_token}"}  # noqa: E731


class MineruError(RuntimeError):
    """旧异常类型（保持可用；新适配器用同名的 ``mineru_adapter.MineruError``）。"""


# ------------------------------------------------------------------ 传输


def _submit_by_url(url: str, model_version: str = "vlm") -> str:
    payload = {
        "url": url,
        "model_version": model_version,
        "is_ocr": True,
        "enable_formula": True,
        "enable_table": True,
        "language": "ch",
    }
    r = httpx.post(f"{_BASE}/api/v4/extract/task", headers=HEADERS(), json=payload, timeout=60)
    j = r.json()
    if j.get("code") != 0:
        raise MineruError(f"提交失败 {j.get('code')} {j.get('msg')}")
    tid = ((j.get("data") or {}).get("task_id"))
    if not tid:
        raise MineruError(f"未返回 task_id: {j}")
    return tid


def _submit_by_bytes(data: bytes, filename: str, model_version: str = "vlm") -> str:
    r = httpx.post(
        f"{_BASE}/api/v4/file-urls/batch",
        headers=HEADERS(),
        json={"files": [{"name": filename, "data_id": "researchlens"}],
              "model_version": model_version},
        timeout=60,
    )
    j = r.json()
    if j.get("code") != 0:
        raise MineruError(f"获取上传链接失败 {j.get('code')} {j.get('msg')}")
    d = j.get("data") or {}
    batch_id = d.get("batch_id")
    urls = d.get("file_urls") or []
    if not urls:
        raise MineruError(f"未返回上传 URL: {j}")
    put = httpx.put(urls[0], content=data, timeout=180)
    if put.status_code not in (200, 201):
        raise MineruError(f"文件上传失败 {put.status_code}")
    if not batch_id:
        raise MineruError("未返回 batch_id")
    return f"batch:{batch_id}"


def _poll(task_ref: str, timeout: float = 600, interval: float = 4.0) -> List[Dict]:
    """轮询任务直到**终态**；批任务必须等到条目 done（修复 D22：非空即返回）。"""
    h = HEADERS()
    start = time.time()
    while time.time() - start < timeout:
        if task_ref.startswith("batch:"):
            bid = task_ref.split(":", 1)[1]
            r = httpx.get(f"{_BASE}/api/v4/extract-results/batch/{bid}", headers=h, timeout=60)
            j = r.json()
            if j.get("code") != 0:
                raise MineruError(f"查询失败 {j.get('code')} {j.get('msg')}")
            res = ((j.get("data") or {}).get("extract_result")) or []
            if not res:
                time.sleep(interval)
                continue
            first = res[0]
            state = first.get("state")
            if state == "done":
                return res
            if state == "failed":
                raise MineruError(f"解析失败：{first.get('err_msg')}")
            time.sleep(interval)
            continue
        r = httpx.get(f"{_BASE}/api/v4/extract/task/{task_ref}", headers=h, timeout=60)
        j = r.json()
        if j.get("code") != 0:
            raise MineruError(f"查询失败 {j.get('code')} {j.get('msg')}")
        d = j.get("data") or {}
        state = d.get("state")
        if state == "done":
            return [d]
        if state == "failed":
            raise MineruError(f"解析失败：{d.get('err_msg')}")
        time.sleep(interval)
    raise MineruError("等待 MinerU 解析超时")


def _download_zip(url: str, retries: int = 3, backoff: float = 3.0) -> bytes:
    last: Optional[Exception] = None
    for i in range(retries):
        try:
            r = httpx.get(url, timeout=180)
            r.raise_for_status()
            return r.content
        except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as e:
            last = e
            log.warning("MinerU zip 下载失败(第 %d 次)，重试：%s", i + 1, e)
            time.sleep(backoff * (i + 1))
    raise MineruError(f"MinerU zip 下载失败：{last}")


# ------------------------------------------------------------------ 解析


def _html_table_to_matrix(html: str, max_rows: int = 12, max_cols: int = 12) -> List[List[str]]:
    """# legacy: not yet migrated — 旧有损矩阵截断（12×12、单元格 60 字）。

    ⚠️ 该截断不满足 §5.3/§3.4 的原件保真要求，新代码请使用
    ``app.modules.visual.tables.extract_cells``（保留 rowspan/colspan 与完整文本）。
    """
    if not html:
        return []
    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    out: List[List[str]] = []
    for row_html in rows_html:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)
        if not cells:
            continue
        row = []
        for c in cells:
            txt = re.sub(r"<[^>]+>", " ", c)
            txt = re.sub(r"\s+", " ", txt).strip()
            row.append(txt[:60])
            if len(row) >= max_cols:
                break
        if row:
            out.append(row)
        if len(out) >= max_rows:
            break
    return out


def _as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x).strip()
    return str(v).strip()


def _group_pages(content_list: List[Dict]) -> List[Dict]:
    """# legacy: not yet migrated — 旧分页：**丢弃** header/footer/page_number 块。

    ⚠️ 这正是 D01 报告的失真点；新实现见 ``app.modules.parse.mineru_adapter``
    （保留全部块与坐标）。此处仅为旧管线兼容保留。
    """
    by_page: Dict[int, List[str]] = {}
    for item in content_list:
        page = item.get("page_idx", 0)
        typ = item.get("type")
        if typ in ("page_number", "header", "footer", "page_footnote"):
            continue
        if typ == "table":
            cap = _as_text(item.get("table_caption"))
            body_txt = re.sub(r"<[^>]+>", " ", item.get("table_body") or "")
            body_txt = re.sub(r"\s+", " ", body_txt).strip()
            seg = (cap + " " + body_txt).strip()
        elif typ in ("image", "chart"):
            seg = _as_text(item.get("chart_caption") or item.get("image_caption"))
        else:
            seg = _as_text(item.get("text"))
        if seg:
            by_page.setdefault(page, []).append(seg)
    return [{"page_no": p + 1, "text": "\n".join(by_page.get(p, []))} for p in sorted(by_page)]


def _bbox_width(bbox) -> float:
    try:
        if not bbox or len(bbox) < 4:
            return 0.0
        return float(bbox[2]) - float(bbox[0])
    except Exception:  # noqa: BLE001
        return 0.0


def _is_content_figure(item: Dict) -> bool:
    typ = item.get("type")
    if typ not in ("image", "chart"):
        return False
    cap = _as_text(item.get("chart_caption") or item.get("image_caption") or item.get("content"))
    if cap:
        return True
    return _bbox_width(item.get("bbox")) >= 300


def _clean_caption(item: Dict) -> str:
    caps = []
    for key in ("chart_caption", "image_caption"):
        v = item.get(key)
        if isinstance(v, list):
            caps.extend(str(x).strip() for x in v if str(x).strip())
        elif isinstance(v, str) and v.strip():
            caps.append(v.strip())
    content = _as_text(item.get("content"))
    if content and content not in caps:
        caps.append(content)
    if not caps:
        return ""
    caps.sort(key=lambda s: len(s), reverse=True)
    return caps[0]


def parse_result(zip_bytes: bytes) -> Dict:
    """# legacy: not yet migrated — 旧 ZIP 解析（使用 ``zipfile`` 直接读，未做路径
    穿越/展开体积/数量限制）。

    ⚠️ 新实现见 ``app.modules.parse.mineru_adapter.safe_extract``（受限解包）。
    """
    if not zip_bytes:
        raise MineruError("空结果")
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))

    md = ""
    for n in z.namelist():
        if n.endswith("full.md"):
            md = z.read(n).decode("utf-8", "ignore")
            break

    content_list: List[Dict] = []
    for n in z.namelist():
        if n.endswith("_content_list.json"):
            raw = json.loads(z.read(n).decode("utf-8", "ignore"))
            if isinstance(raw, list):
                content_list = raw
            break

    pages = _group_pages(content_list)

    figures: List[Dict] = []
    images_map: Dict[str, bytes] = {}
    for n in z.namelist():
        if n.startswith("images/") and not n.endswith("/"):
            images_map[n] = z.read(n)
    fig_no = 0
    for item in content_list:
        if item.get("type") not in ("image", "chart"):
            continue
        if not _is_content_figure(item):
            continue
        cap = _clean_caption(item)
        ipath = item.get("img_path") or item.get("image_path") or ""
        img = images_map.get(ipath.split("/")[-1]) if ipath else None
        if not img and ipath:
            img = images_map.get(f"images/{ipath.rsplit('/',1)[-1]}")
        if img:
            fig_no += 1
            import base64

            figures.append({
                "fig_no": fig_no,
                "caption": cap or f"图 {fig_no}",
                "page": (item.get("page_idx") or 0) + 1,
                "image_b64": base64.b64encode(img).decode("utf-8"),
            })

    tables: List[Dict] = []
    tbl_no = 0
    for item in content_list:
        if item.get("type") == "table":
            body = item.get("table_body") or ""
            matrix = _html_table_to_matrix(body)
            if not matrix and not body:
                continue
            tbl_no += 1
            tables.append({
                "table_no": tbl_no,
                "caption": _as_text(item.get("table_caption")) or f"表 {tbl_no}",
                "page": (item.get("page_idx") or 0) + 1,
                "content": matrix,
                "table_html": body,
                "key_finding": _as_text(item.get("table_footnote")),
            })

    return {"full_text": md, "pages": pages, "figures": figures, "tables": tables}


def parse_pdf(data: Optional[bytes] = None, url: Optional[str] = None,
              filename: str = "paper.pdf") -> Dict:
    """MinerU 解析入口（旧签名）。

    优先本地字节上传（可确认与保存字节一致）；仅在无字节时才用 URL。
    ⚠️ 使用远程 URL 时必须能确认解析输入与 SourceDocument hash 相同（§5.14）；
    调用方无法确认时应改用 PyMuPDF 降级。
    """
    if not settings.has_mineru:
        raise MineruError("未配置 MINERU_TOKEN")
    if data:
        task_ref = _submit_by_bytes(data, filename)
    elif url and url.startswith("http"):
        task_ref = _submit_by_url(url)
    else:
        raise MineruError("无数据且无 URL")
    results = _poll(task_ref)
    if not results:
        raise MineruError("未取得解析结果")
    first = results[0]
    if first.get("state") == "failed":
        raise MineruError(f"解析失败：{first.get('err_msg')}")
    zip_url = first.get("full_zip_url")
    if not zip_url:
        raise MineruError("未返回结果 zip")
    return parse_result(_download_zip(zip_url))


__all__ = [
    "MineruError",
    "parse_result",
    "parse_pdf",
]
