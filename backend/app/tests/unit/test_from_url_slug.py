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
        # 后台任务不跑真实 pipeline（那只验端点行为）——
        # 打桩"干活"的入口；注意现在是 `ingest_pdf_for_paper`（端点不再用
        # `ingest_paper_from_pdf`，见 TestFromUrlOwnsExactlyOnePaper）。
        monkeypatch.setattr(routes_mod, "ingest_pdf_for_paper", lambda *a, **k: 1)
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


# ------------------------------------------------------------------ 3


class TestFromUrlOwnsExactlyOnePaper:
    """端点返回的 `paper_id` 必须是**真正被处理的那一篇**，且不许留下空壳论文。

    ## 实测到的真 bug（2026-09-13，真实导入自己踩到）

    端点先插入一行 Paper（`slug_for_import` 派生的 slug），**然后**把活儿交给
    `ingest_paper_from_pdf`；而后者内部又用 `_find_paper_by_slug(title)` 自己找论文，
    找不到就**再建一篇**。两者能不能对上，取决于 `make_slug(title)` 是否等于端点的 slug：

    | 调用方 | title | 端点 slug | `make_slug(title)` | 结果 |
    |---|---|---|---|---|
    | 前端粘贴网址 | 空 → `title = slug` | `jos-6106` | `jos-6106` | ✅ 复用同一篇 |
    | **带中文标题** | `数据驱动的…` | `数据驱动的…` | `paper`（中文被 ASCII 化掉） | ❌ **建两篇** |

    实测（POST 6106 且带中文标题）：30ms 内出现 **paper 21**（中文 slug、`pending`、
    0 job / 0 revision / 0 source）与 **paper 22**（`ingest-<hash>`、跑完 publish）。
    而接口返回的是 **21** —— 也就是**返回了一篇永远不会被处理的论文**，
    界面会永远停在"处理中"，库里还多一个空壳。

    前端目前不传 title，所以这条路径没暴露；但 API 明确支持 title，属于真缺陷。
    修法：端点把活儿交给 `ingest_pdf_for_paper(pid, ...)`（为**已存在**的 paper 跑 ingest），
    让"哪一篇"只有一个答案。
    """

    @pytest.fixture
    def harness(self, monkeypatch):
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

        monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp(), raising=False)

        calls: dict = {"for_paper": []}
        monkeypatch.setattr(
            routes_mod, "ingest_pdf_for_paper",
            lambda pid, data, **kw: calls["for_paper"].append((pid, kw)) or 1,
        )
        return TestClient(app), calls

    @pytest.fixture
    def real_ingest_harness(self, monkeypatch):
        """只打桩**流水线本身**（`_enqueue_and_run`），保留两条 ingest 入口的真实逻辑。

        为什么不能顺手把 `ingest_paper_from_pdf` 也打桩：那个桩会替被测 bug 打掩护 ——
        "建了两篇论文"这件事正是发生在它的 `_find_paper_by_slug` + `create_paper` 里，
        桩掉它，断言恒真（第一版就写错了，实测这条测试在修前也通过）。
        """
        from fastapi.testclient import TestClient

        from app.main import app
        from app.modules.pipeline import ingest as ingest_mod

        pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"

        class _Resp:
            status_code = 200
            headers = {"content-type": "application/pdf"}
            content = pdf

            def raise_for_status(self):
                return None

        monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp(), raising=False)
        monkeypatch.setattr(ingest_mod, "_enqueue_and_run", lambda *a, **k: 1)
        return TestClient(app)

    @staticmethod
    def _paper_count() -> int:
        from app.core.db import SessionLocal
        from app.models.models import Paper

        with SessionLocal() as db:
            return db.query(Paper).count()

    def test_chinese_title_creates_exactly_one_paper(self, real_ingest_harness):
        """**一次导入 = 一篇论文**（修前实测是两篇：空壳 + 真货）。"""
        client = real_ingest_harness
        before = self._paper_count()

        r = client.post("/api/papers/from-url",
                        json={"url": "https://example.com/cn/5281", "title": "中文标题的论文"})
        assert r.status_code == 200, r.text

        assert self._paper_count() - before == 1, (
            "带非 ASCII 标题的导入建了不止一篇论文 —— 多出来的是永远不会被处理的空壳"
        )
        assert r.json()["slug"] == "中文标题的论文", r.json()

    def test_processing_targets_the_returned_paper_id(self, harness):
        """核心：被处理的那一篇 = 接口返回的那一篇。"""
        client, calls = harness
        r = client.post("/api/papers/from-url",
                        json={"url": "https://example.com/cn/6106", "title": "另一个中文标题"})
        assert r.status_code == 200, r.text
        pid = r.json()["paper_id"]

        assert calls["for_paper"], "端点必须调用 ingest_pdf_for_paper（为已存在的 paper 跑 ingest）"
        assert calls["for_paper"][0][0] == pid, (
            f"被处理的是 {calls['for_paper'][0][0]}，而接口返回 {pid} —— 界面会永远转圈"
        )
