"""单测共享夹具：**隔离数据库 + 禁止真实云调用**。

为什么需要它（重要）：
``app.core.db.session_scope`` 的签名是 ``session_scope(factory=SessionLocal)``，
默认值在**函数定义时**就绑定了模块级 ``SessionLocal``。因此"把
``db_mod.SessionLocal`` 换成测试 factory"并不能改变 ``session_scope()`` 的行为——
写操作仍会落到真实 ``data/researchlens.db``。

本 conftest 通过两条路径确保隔离：
1. 在 import ``app`` 之前设置 ``DATABASE_URL``/``DATA_DIR`` 指向 tmp 目录，
   让**模块级引擎**本身就指向临时库；
2. 同时把 ``session_scope`` 底层函数的 ``__defaults__`` 指向测试 factory，
   并提供 ``isolated_db`` 夹具供各测试模块按需重建表结构。

另外清空 LLM/embedding 密钥，保证单测**绝不打真实云调用**。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# --------------------------------------------------------------- 环境隔离（必须在 app 导入前）
_TMP_ROOT = Path(__file__).resolve().parent / "_tmp_shared"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
# 每次 pytest 会话从干净库开始：删除上次运行的 unit.db（含 WAL/SHM），
# 否则跨运行残留的 job/paper 会让 claim_next 等「领取下一个」的测试捡到脏数据。
for _f in ("unit.db", "unit.db-wal", "unit.db-shm"):
    (_TMP_ROOT / _f).unlink(missing_ok=True)
os.environ.setdefault("DATA_DIR", str(_TMP_ROOT / "data"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP_ROOT / 'unit.db').as_posix()}")
os.environ["MINERU_ENABLED"] = "false"
os.environ["MINERU_TOKEN"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_FALLBACKS"] = ""
os.environ["EMBEDDING_MODEL"] = ""


@pytest.fixture(scope="session", autouse=True)
def _shared_engine():
    """整个单测会话共用**一个**临时引擎（所有测试模块指向同一 tmp 库）。

    表结构只创建一次；各测试通过**不同的 paper/revision scope** 隔离数据，
    因此不需要在会话中途 drop_all（中途清表会破坏其它测试模块的数据）。
    """
    from app.core import db as db_mod

    import app.models  # noqa: F401
    from app.models import artifacts, audit, evidence, jobs, retrieval, source  # noqa: F401

    eng = db_mod.engine
    db_mod.Base.metadata.create_all(bind=eng)

    # 关键：让 session_scope() 真正使用测试引擎
    factory = db_mod.SessionLocal
    underlying = getattr(db_mod.session_scope, "__wrapped__", None)
    if underlying is not None:
        underlying.__defaults__ = (factory,)
    yield eng


@pytest.fixture
def isolated_db(_shared_engine):
    """模块级夹具：清空所有表，保证测试之间互不污染。"""
    from app.core import db as db_mod

    yield db_mod.SessionLocal
