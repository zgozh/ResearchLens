"""启动自举策略：**只自动导入 1 篇**真实论文，另外两篇留给使用者在导入页手动触发。

## 用户原话

> "改成只有基于 Haar 小波域指标自适应选择载体的 JPEG 隐写这一篇会进入解析，
>  另外两篇不自动，别人可以在导入那里进行测试而不是直接开启项目就自动导入。"

## 为什么改成 1 篇

自举 3 篇的代价落在**每个克隆者**身上：首次启动就要串行跑完 3 篇（实测未配 MinerU
约 4 分钟、配 MinerU 约 10 分钟；worker 是单进程串行），占着队列与模型配额，而其中
两篇往往不是他想看的那一篇。改成「自动 1 篇打底 + 其余按需导入」后：

- 新部署一启动就有**一篇真实中文论文**可看（不是空库、也不是只剩自绘示例）；
- 另外两篇仍留在导入页示例里（`frontend/app/upload/page.tsx` 的 `EXAMPLE_PAPERS`），
  点一下就能复现同样的结果 —— 既不浪费别人的配额，也不隐藏已验证过的样例。

## 本模块锁住的口径

1. `AUTO_SEED_PAPERS` 恰好 1 篇，且是 Haar 那篇（5281）；
2. `REAL_PAPERS`（目录）仍是 3 篇 —— 导入页要拿它们做示例；
3. `provision_real_papers()` 实际**只入队 1 个 job**（行为级断言，不是只看常量）；
4. 导入页源码里仍列着这三条链接（需求的后半句：别人能在导入处测试）。
"""
from __future__ import annotations

import pathlib

import pytest

#: 仓库根（backend/app/tests/unit/ → 上溯 4 层）
ROOT = pathlib.Path(__file__).resolve().parents[4]

HAAR_URL = "https://www.jos.org.cn/josen/article/pdf/5281"
USER_IMPORT_URLS = [
    "https://www.jos.org.cn/josen/article/pdf/5281",
    "https://www.jos.org.cn/josen/article/pdf/6106",
    "https://www.jos.org.cn/josen/article/pdf/6550",
]


# ------------------------------------------------------------------ 1 常量口径


class TestAutoSeedSubset:
    def test_only_one_paper_is_auto_seeded(self):
        from app.modules.pipeline import seed_real

        assert len(seed_real.AUTO_SEED_PAPERS) == 1, (
            "启动自举只该自动导入 1 篇；要改数量请先改这条测试的理由"
        )

    def test_auto_seeded_paper_is_the_haar_one(self):
        from app.modules.pipeline import seed_real

        url, title = seed_real.AUTO_SEED_PAPERS[0]
        assert url == HAAR_URL
        assert "Haar" in title and "JPEG" in title

    def test_catalog_keeps_all_three(self):
        """目录不能跟着缩水：缩了导入页示例就没得列，需求后半句就落空了。"""
        from app.modules.pipeline import seed_real

        urls = [u for u, _ in seed_real.REAL_PAPERS]
        assert urls == USER_IMPORT_URLS
        # 自动的那篇必须是目录成员（不许另起野链接绕过目录）
        assert seed_real.AUTO_SEED_PAPERS[0] in seed_real.REAL_PAPERS


# ------------------------------------------------------------------ 2 行为口径


class TestProvisionEnqueuesOnlyAutoSubset:
    def test_log_reads_the_key_the_report_actually_returns(self):
        """日志键名必须与 `seed_catalog` 的返回形状一致。

        实测踩到过：日志读 `report.get("skipped")`，而 `seed_catalog` 返回的是
        `skipped_keys` —— 于是**永远打印"跳过 0 篇"**。运维看到"入队 0、跳过 0"
        会以为自举没跑，实际是"已经导过、被正确跳过了"（`skipped_keys=1`）。
        """
        src = (ROOT / "backend" / "app" / "modules" / "pipeline" / "seed_real.py").read_text(
            encoding="utf-8"
        )
        assert 'report.get("skipped_keys"' in src, (
            "日志必须读 skipped_keys —— 读 skipped 会恒定显示 0，把'已跳过'伪装成'没跑'"
        )
        assert 'report.get("skipped"' not in src

    def test_provision_enqueues_exactly_one_job(self, monkeypatch):
        """**行为级**：真的调用一次自举，数它入队了几个 job、是不是那一篇。

        为什么 monkeypatch `_find_paper`：本测试问的是「入队几篇」，
        不该被共享测试库里恰好存在同名论文影响（那会让断言随机成败）。
        """
        from app.modules.pipeline import seed_real

        created: list[str] = []
        enqueued: list[dict] = []

        class _Rec:
            def __init__(self, ident: int) -> None:
                self.id = ident

        def _fake_create_paper(payload, ctx=None):
            created.append(payload.title)
            return _Rec(1000 + len(created))

        def _fake_enqueue(spec, ctx):
            enqueued.append({"paper_id": spec.paper_id, "url": spec.source.url})
            return _Rec(5000 + len(enqueued))

        monkeypatch.setattr(seed_real, "_find_paper", lambda title: None)
        monkeypatch.setattr("app.modules.papers.create_paper", _fake_create_paper)
        monkeypatch.setattr("app.modules.pipeline.service.enqueue", _fake_enqueue)

        seed_real.provision_real_papers()

        # provision_real_papers 内部吞异常（启动期不能炸），所以这里必须自己
        # 断言"确实跑到了"——否则 monkeypatch 失效时会伪装成"0 篇=通过"。
        assert created, "自举没有建任何论文：多半是 provision_real_papers 提前异常了"
        assert len(enqueued) == 1, f"启动只该入队 1 个 job，实际 {len(enqueued)}：{enqueued}"
        assert enqueued[0]["url"] == HAAR_URL


# ------------------------------------------------------------------ 3 导入页口径


class TestImportPageStillOffersThem:
    def test_upload_page_lists_all_three_chinese_urls(self):
        page = ROOT / "frontend" / "app" / "upload" / "page.tsx"
        if not page.exists():  # pragma: no cover - 只跑后端的环境
            pytest.skip("没有前端源码（只装了 backend）")

        src = page.read_text(encoding="utf-8")
        missing = [u for u in USER_IMPORT_URLS if u not in src]
        assert not missing, (
            f"导入页示例里缺了这些链接：{missing}\n"
            "需求是「另外两篇不自动，但别人可以在导入那里测试」——"
            "示例被删掉就等于把这两篇藏起来了"
        )
