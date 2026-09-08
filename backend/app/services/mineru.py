"""services/mineru — MinerU 高质量文档解析（可选外部工具）。

把 PDF 直接抛给 MinerU 精准解析 API（reading-order markdown + 结构化表格 HTML +
真实图表图片 + OCR/公式），返回一份可直接入库的中间表示：
    {full_text, pages[{page_no,text}], figures[{image_b64,caption,page}],
     tables[{table_no,caption,page,content[[str]],key_finding}] }

采用「URL 提交」优先；无公开 URL 时改用本地文件批量上传签名接口。
任何一步失败都抛异常，由调用方决定降级到 pymupdf。
"""
from __future__ import annotations

import base64
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
    pass


def _submit_by_url(url: str, model_version: str = "vlm") -> str:
    """创建精准解析任务（URL 模式），返回 task_id。"""
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
    """创建精准解析任务（本地文件签名上传），返回 task_id（上传后自动解析）。"""
    r = httpx.post(
        f"{_BASE}/api/v4/file-urls/batch",
        headers=HEADERS(),
        json={"files": [{"name": filename, "data_id": "researchlens"}], "model_version": model_version},
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
    """轮询任务直到 done；返回解析结果条目列表（每项含 full_zip_url 或 err_msg）。"""
    h = HEADERS()
    start = time.time()
    while time.time() - start < timeout:
        if task_ref.startswith("batch:"):
            bid = task_ref.split(":", 1)[1]
            r = httpx.get(f"{_BASE}/api/v4/extract-results/batch/{bid}", headers=h, timeout=60)
            j = r.json()
            if j.get("code") != 0:
                raise MineruError(f"查询失败 {j.get('code')} {j.get('msg')}")
            # batch: data.extract_result 是数组
            res = ((j.get("data") or {}).get("extract_result")) or []
            if not res:
                time.sleep(interval)
                continue
            return res
        else:
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
    """下载结果 zip；对瞬时连接拒绝/超时做重试（MinerU CDN 偶发 Connection refused）。"""
    last: Optional[Exception] = None
    for i in range(retries):
        try:
            r = httpx.get(url, timeout=180)
            r.raise_for_status()
            return r.content
        except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as e:  # noqa: PERF203
            last = e
            log.warning("MinerU zip 下载失败(第 %d 次)，重试：%s", i + 1, e)
            time.sleep(backoff * (i + 1))
    raise MineruError(f"MinerU zip 下载失败：{last}")


def _html_table_to_matrix(html: str, max_rows: int = 12, max_cols: int = 12) -> List[List[str]]:
    """把 MinerU 表格的 HTML <table> 转成 [[cell,...],...] 字符串矩阵（图片不放入，取压缩/去重）。"""
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
    """MinerU 的 caption/summary 可能是 str 或 list[str]，统一转成单行文本。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x).strip()
    return str(v).strip()


def _group_pages(content_list: List[Dict]) -> List[Dict]:
    """按 page_idx 归组，每页文本拼接（含表格与公式文本），供正文/章节/断言/QA 使用。"""
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
            cap = _as_text(item.get("chart_caption") or item.get("image_caption"))
            seg = cap
        elif typ == "equation":
            seg = _as_text(item.get("text"))
        else:
            seg = _as_text(item.get("text"))
        if seg:
            by_page.setdefault(page, []).append(seg)
    pages = [{"page_no": p + 1, "text": "\n".join(by_page.get(p, []))} for p in sorted(by_page)]
    return pages


def _bbox_width(bbox) -> float:
    """bbox 形如 [x0,y0,x1,y1]，返回宽度；异常返回 0。"""
    try:
        if not bbox or len(bbox) < 4:
            return 0.0
        return float(bbox[2]) - float(bbox[0])
    except Exception:  # noqa: BLE001
        return 0.0


def _is_content_figure(item: Dict) -> bool:
    """过滤噪声图：作者头像 / 二维码 / 期刊 logo 等。

    判据：MinerU 的 content_list 里，真实内容图（流程图/曲线图/架构图）通常
    - 有非空题注（chart_caption/image_caption），或
    - bbox 宽度较大（≥ 300px，占满正文栏）。
    而二维码/头像/logo 多为「小图 + 无题注」。二者皆不满足则丢弃。
    """
    typ = item.get("type")
    if typ not in ("image", "chart"):
        return False
    cap = _as_text(item.get("chart_caption") or item.get("image_caption") or item.get("content"))
    if cap:
        return True
    # 无题注：仅当宽度足够大（正文级图）才保留，否则视为噪声
    if _bbox_width(item.get("bbox")) >= 300:
        return True
    return False


def _clean_caption(item: Dict) -> str:
    """拼合题注：取清晰的中/英题注段，去掉多余碎片（如 Axis 标签文本）。"""
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
    # 题注可能含多段（Axis 标签 + 图题），取最长的一段为主（图题通常最长、含 Fig./图 N）
    caps.sort(key=lambda s: len(s), reverse=True)
    return caps[0]


def parse_result(zip_bytes: bytes) -> Dict:
    """从 MinerU 结果 zip 解析出可入库 IR。"""
    if not zip_bytes:
        raise MineruError("空结果")
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = {n: z.getinfo(n).file_size for n in z.namelist()}

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

    # 图：取 image/chart 条目 + 对应图片字节
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
            continue  # 过滤二维码 / 作者头像 / logo
        cap = _clean_caption(item)
        ipath = item.get("img_path") or item.get("image_path") or ""
        img = images_map.get(ipath.split("/")[-1]) if ipath else None
        if not img and ipath:
            img = images_map.get(f"images/{ipath.rsplit('/',1)[-1]}")
        if img:
            fig_no += 1
            figures.append({
                "fig_no": fig_no,
                "caption": cap or f"图 {fig_no}",
                "page": (item.get("page_idx") or 0) + 1,
                "image_b64": base64.b64encode(img).decode("utf-8"),
            })

    # 表：取 table 条目（保留原始 HTML，前端优先渲染原表）
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

    return {
        "full_text": md,
        "pages": pages,
        "figures": figures,
        "tables": tables,
    }


def parse_pdf(data: Optional[bytes] = None, url: Optional[str] = None, filename: str = "paper.pdf") -> Dict:
    """MinerU 解析入口。优先 URL 提交，否则本地文件上传。返回 parse_result 结构。"""
    if not settings.has_mineru:
        raise MineruError("未配置 MINERU_TOKEN")
    if url and (url.startswith("http")):
        task_ref = _submit_by_url(url)
    else:
        if not data:
            raise MineruError("无数据且无 URL")
        task_ref = _submit_by_bytes(data, filename)
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
