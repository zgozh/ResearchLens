"""网址导入必须**只接受真的 PDF**（ADR-0064）。

用户视角：主页有个"粘贴论文网址"的输入框。实测把 arXiv 的**摘要页**
（``https://arxiv.org/abs/1706.03762``）贴进去会返回 **HTML**，而旧实现把响应体
**不管内容一律存成 .pdf** 并入库 → 解析阶段必然失败、库里多出一篇永远不会成功的"论文"，
用户看到的是一个卡住/空白的条目。

纪律：**入库前先验明是 PDF**（魔数 ``%PDF-`` 或 content-type=application/pdf），
不是就**立刻 400 报错并说明原因**，不建论文、不建 revision、不留垃圾数据。
"""
from __future__ import annotations

import os

os.environ["LLM_API_KEY"] = ""


def _resp(content: bytes, content_type: str = ""):
    from types import SimpleNamespace

    return SimpleNamespace(content=content, headers={"content-type": content_type},
                           status_code=200)


class TestPdfGuard:
    def test_real_pdf_bytes_pass(self):
        from app.api.routes import _looks_like_pdf

        assert _looks_like_pdf(_resp(b"%PDF-1.7\n...", "application/pdf")) is True
        # 有些站点不给 content-type，但字节是 PDF
        assert _looks_like_pdf(_resp(b"%PDF-1.4\n...", "")) is True

    def test_html_page_is_rejected(self):
        from app.api.routes import _looks_like_pdf

        assert _looks_like_pdf(_resp(b"<!DOCTYPE html><html>", "text/html")) is False

    def test_html_with_pdf_content_type_is_still_rejected(self):
        """报错页有时挂着 application/pdf：**字节优先**。"""
        from app.api.routes import _looks_like_pdf

        assert _looks_like_pdf(_resp(b"<html>error</html>", "application/pdf")) is False

    def test_empty_body_is_rejected(self):
        from app.api.routes import _looks_like_pdf

        assert _looks_like_pdf(_resp(b"", "application/pdf")) is False

    def test_error_message_is_actionable(self):
        from app.api.routes import _pdf_rejection_reason

        reason = _pdf_rejection_reason(_resp(b"<!DOCTYPE html>", "text/html"))
        assert "PDF" in reason and ("直链" in reason or "下载地址" in reason), reason
