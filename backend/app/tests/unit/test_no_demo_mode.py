"""R4-紧急 — **彻底删除 DEMO 模式**：全项目永远走完整模型链路。

## 用户原话

> "请确认 DEMO_MODE=false 并已配置 DashScope/LLM。应该直接把这个 demo 模式删掉，
>  应该让整个项目都是完整模型不需要 demo 模型，整个项目功能已经不错了。"

## 为什么要删而不是"把默认值改成 false"

`DEMO_MODE` 是一个**双态开关**：true 时上传被 400 拦掉、真实论文自举被跳过、
健康检查对外宣告 `demo_mode=true`。留着它就有三种坏结果：

1. 有人 `cp .env.example .env` 后忘了改 → 上传直接 400，而界面的提示语只在
   **失败之后**才出现，用户看到的是"处理失败 / Failed to fetch"；
2. 部署形态分叉（demo 栈 vs live 栈），出问题时要先问"你哪套模式"；
3. 产品定位被稀释 —— 这是个**真实抽取**的产品，不需要一条"读内置 seed"的旁路。

**改法**：删掉开关本身，而不是把默认值改成 false。真值只有一个：
有 LLM 就调 LLM，没有就如实降级（`has_llm=False` 时走抽取式路径，这是**运行期降级**，
与"演示模式"是两件事）。

## 本模块锁住的口径

1. `settings` 上**不存在** `demo_mode` / `is_live`；
2. `HealthOut` **不再**对外宣告 `demo_mode`（对外契约里没有这个概念）；
3. 上传端点**没有** demo 分支（永远接受上传）；
4. 真实论文自举**没有** demo 门禁（启动就自举）；
5. 全仓库源码里 `demo_mode` / `DEMO_MODE` 零命中（文档里的历史记录不算 —— 那是史实）。
"""
from __future__ import annotations

import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[2]  # backend/app


# ------------------------------------------------------------------ 1


class TestSettingIsGone:
    def test_settings_has_no_demo_mode(self):
        from app.core.config import settings

        assert not hasattr(settings, "demo_mode"), (
            "DEMO_MODE 开关必须删除 —— 留着它就会有人忘了配，上传被 400 拦掉"
        )

    def test_settings_has_no_is_live(self):
        """`is_live` 只是 `not demo_mode` 的马甲，随开关一起删（否则等于留了个后门）。"""
        from app.core.config import settings

        assert not hasattr(settings, "is_live")

    def test_runtime_degradation_still_exists(self):
        """**降级能力不能跟着一起删**：没配 LLM 时 `has_llm=False` 是运行期事实，
        不是"演示模式"。这是两条不同的东西。"""
        from app.core.config import settings

        assert hasattr(settings, "has_llm")
        assert hasattr(settings, "has_mineru")


# ------------------------------------------------------------------ 2


class TestHealthContract:
    def test_health_out_has_no_demo_mode_field(self):
        from app.schemas.schemas import HealthOut

        assert "demo_mode" not in HealthOut.model_fields, (
            "对外健康检查不该再宣告一个已被删除的概念"
        )

    def test_health_endpoint_shape(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        body = client.get("/api/health").json()
        assert body.get("status") == "ok"
        assert "demo_mode" not in body, body
        assert "version" in body


# ------------------------------------------------------------------ 3


class TestUploadHasNoDemoBranch:
    def test_upload_endpoint_source_has_no_demo_guard(self):
        src = (APP / "api/routes.py").read_text(encoding="utf-8")
        m = re.search(r"async def paper_upload\(.*?\n(?=@router|def |\Z)", src, flags=re.S)
        assert m, "找不到 paper_upload 端点"
        body = m.group(0)
        assert "demo_mode" not in body, "上传端点不许再有 demo 分支（那是把功能关掉）"
        assert "DEMO_MODE" not in body


# ------------------------------------------------------------------ 4


class TestStartupAlwaysProvisionsReal:
    def test_lifespan_starts_real_provision_unconditionally(self):
        src = (APP / "main.py").read_text(encoding="utf-8")
        m = re.search(r"def lifespan\(.*?\n(?=app = )", src, flags=re.S)
        assert m, "找不到 lifespan"
        body = m.group(0)
        assert "demo_mode" not in body, "自举不该再有 demo 门禁"
        assert "start_real_provision_thread" in body, "启动时必须自举真实论文"

    def test_seed_real_has_no_demo_gate(self):
        src = (APP / "modules/pipeline/seed_real.py").read_text(encoding="utf-8")
        assert "demo_mode" not in src, "seed_real 不该再因 demo 模式跳过"


# ------------------------------------------------------------------ 5


class TestNoDemoModeAnywhere:
    def test_code_has_zero_demo_mode_hits(self):
        """**代码**里零命中 —— 这是"真的删了"而不是"改了个默认值"。

        为什么允许注释/docstring 提到它：删除的原因本身值得写在代码旁边
        （"此处曾有 DEMO_MODE 旁路，已删除"），否则下一个人会把它加回来。
        所以本门禁只判**代码行**：跳过 docstring 块与行尾注释。
        """
        hits: list[str] = []
        for path in APP.rglob("*.py"):
            rel = path.relative_to(APP).as_posix()
            if rel.startswith("tests/"):
                continue
            text = path.read_text(encoding="utf-8")
            in_doc = False
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.lstrip()
                # 三引号块开关（本仓库的 docstring 都是独占成行的三引号）
                quotes = stripped.count('"""') + stripped.count("'''")
                if in_doc:
                    if quotes:
                        in_doc = False
                    continue
                if quotes:
                    if quotes == 1:
                        in_doc = True
                    continue
                # 行尾注释去掉后再看有没有残留
                code = line.split("#", 1)[0]
                if "demo_mode" in code or "DEMO_MODE" in code:
                    hits.append(f"{rel}:{lineno}")
        assert not hits, (
            f"这些**代码行**还有 demo 模式残留：{sorted(set(hits))}\n"
            "（注释里提到它是允许的：删除原因值得写在旁边）"
        )

    def test_settings_schema_snapshot_has_no_demo_mode(self):
        """`settings` 是 dataclass：把字段名打出来，确保没有漏网的。"""
        import dataclasses

        from app.core.config import Settings

        names = {f.name for f in dataclasses.fields(Settings)}
        assert "demo_mode" not in names, sorted(n for n in names if "demo" in n)
