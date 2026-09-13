"""R4-紧急 — **网址导入的 slug 唯一性**：第二次不带标题的导入不许 500。

## 实测到的真 bug（这就是"真实导入处理失败"的根因之一）

`POST /api/papers/from-url` 在请求没带 `title` 时写死 `title = "Real Paper"`，
于是 `slug = "real-paper"` —— 一个**常量**。而 `papers.slug` 上有唯一索引 `ix_papers_slug`。

后果：**只要库里已经有一篇 `real-paper`，之后每一次不带标题的网址导入都会**
`IntegrityError: duplicate key value violates unique constraint "ix_papers_slug"` → HTTP 500。

实测证据（后端日志）：

```
sqlalchemy.exc.IntegrityError: (psycopg.errors.UniqueViolation)
duplicate key value violates unique constraint "ix_papers_slug"
DETAIL:  Key (slug)=(real-paper) already exists.
[parameters: {'slug': 'real-paper', 'title': 'Real Paper',
              'abstract': '真实公开论文 · https://www.jos.org.cn/josen/article/pdf/5281', ...}]
```

**为什么以前没暴露**：库里第一篇无标题导入（paper 11）成功占了 `real-paper`，
此后所有无标题导入都在 500 —— 而前端 `api.paperFromUrl(url)` **从不传 title**，
所以"粘贴网址"这条路从第二篇起就是坏的。

## 本模块锁住的口径

1. slug **必须由 URL 派生**（可读、稳定），不再用常量；
2. **幂等**：同一个 URL 重复导入 → 复用同一篇（不新建、不 500）；
3. 不同 URL → 不同 slug；
4. 显式给了 `title` 时仍以标题派生的 slug 为准（用户意图优先）。
"""
from __future__ import annotations

import os

import pytest

os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""


# ------------------------------------------------------------------ 1


class TestSlugFromUrl:
    """slug 派生规则（纯函数，先测规则本身）。"""

    def _slug(self, url: str, title: str = "") -> str:
        from app.api.routes import slug_for_import

        return slug_for_import(url=url, title=title)

    def test_jos_pdf_url_yields_readable_slug(self):
        s = self._slug("https://www.jos.org.cn/josen/article/pdf/5281")
        assert "5281" in s, s
        assert s == s.lower() and " " not in s

    def test_arxiv_url_yields_readable_slug(self):
        s = self._slug("https://arxiv.org/pdf/1706.03762")
        assert "1706" in s or "03762" in s, s

    def test_two_different_urls_differ(self):
        a = self._slug("https://www.jos.org.cn/josen/article/pdf/5281")
        b = self._slug("https://www.jos.org.cn/josen/article/pdf/6106")
        assert a != b, (a, b)

    def test_same_url_is_stable(self):
        u = "https://arxiv.org/pdf/1810.04805"
        assert self._slug(u) == self._slug(u), "同 URL 必须派生同 slug（幂等的前提）"

    def test_explicit_title_wins(self):
        s = self._slug("https://arxiv.org/pdf/1810.04805", title="BERT Paper")
        assert "bert" in s, s

    def test_slug_never_empty_and_bounded(self):
        for u in ("https://x/y", "https://example.com/", "https://a/b?c=d&e=f"):
            s = self._slug(u)
            assert s and len(s) <= 64, (u, s)

    def test_no_constant_real_paper_slug(self):
        """不许再出现"常量 slug" —— 那正是撞唯一索引的原因。"""
        s1 = self._slug("https://a.example.com/one")
        s2 = self._slug("https://b.example.com/two")
        assert s1 != s2
        assert "real-paper" not in (s1, s2), "不该再退化成常量 real-paper"


# ------------------------------------------------------------------ 2


class TestEndpointIsIdempotentAndSafe:
    """端点行为：同 URL 复用、异 URL 不撞——**都不许 500**。"""

    @pytest.fixture
    def client(self, monkeypatch):
        # 不真的下载：把外网调用换成返回一段最小 PDF
        from fastapi.testclient import TestClient

        from app.api import routes as routes_mod
        from app.main import app

        pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"

        class _Resp:
            status_code = 200
            headers = {"content-type": "application/pdf"}
            content = pdf

            def raise_for_status(self):
                return None

        monkeypatch.setattr(
            "httpx.get", lambda *a, **k: _Resp(), raising=False
        )
        # 后台任务不跑真实 pipeline（那只验端点行为）
        monkeypatch.setattr(routes_mod, "ingest_paper_from_pdf", lambda *a, **k: 1)
        return TestClient(app)

    def test_first_import_returns_paper_id(self, client):
        r = client.post("/api/papers/from-url",
                        json={"url": "https://example.com/a/111"})
        assert r.status_code == 200, r.text
        assert r.json().get("paper_id") or r.json().get("slug")

    def test_second_untitled_import_does_not_500(self, client):
        """**核心回归**：第二次不带标题的导入以前会撞唯一索引 500。"""
        first = client.post("/api/papers/from-url", json={"url": "https://example.com/a/222"})
        assert first.status_code == 200, first.text
        second = client.post("/api/papers/from-url", json={"url": "https://example.com/a/333"})
        assert second.status_code == 200, (
            f"第二次不同 URL 的无标题导入必须成功，实际 {second.status_code}: {second.text}"
        )
        assert first.json()["slug"] != second.json()["slug"], "不同 URL 必须得到不同 slug"

    def test_same_url_twice_is_idempotent(self, client):
        """同一 URL 重复导入 → 复用同一篇（不新建、不报错）。"""
        first = client.post("/api/papers/from-url", json={"url": "https://example.com/a/444"})
        assert first.status_code == 200, first.text
        again = client.post("/api/papers/from-url", json={"url": "https://example.com/a/444"})
        assert again.status_code == 200, again.text
        assert again.json()["paper_id"] == first.json()["paper_id"]
        assert again.json()["slug"] == first.json()["slug"]
