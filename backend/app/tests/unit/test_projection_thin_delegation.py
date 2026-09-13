"""M10：**薄委托门禁** —— 非权威侧的投影不许再长出逻辑。

D-93/D-100/D-101 把四个域各收敛成"一份真实实现 + 一份薄委托"。但如果没人管，
下一次有人为了"顺手加个字段"就会把逻辑写回副本里，事故路径立刻复活
（D-48/D-60 就是这么来的）。

本文件把"薄委托"变成可执行的不变量：对**已知委托方**，检查其函数体
① 足够短、② 确实出现转发调用（`_projection` / 直接 import 的那份）。二者任一不满足即红。
"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2]

#: (文件, 函数名) —— 这些位置的投影**必须**只是委托。
#: 注意：这里列的是**非权威侧**。R4-M8 之后权威实现在 `app/projection/`
#: （`CONTRACT.md` 里有完整清单）；graph 与 scene 也在本清单里了 ——
#: 它们的实现已搬进 projection，原位置退化为薄委托。
DELEGATING = [
    ("modules/qa/legacy.py", "to_legacy_answer"),
    ("modules/evaluation/legacy.py", "to_legacy_evaluation"),
    ("modules/graph/legacy.py", "to_legacy_graph"),
    ("modules/scene/legacy.py", "to_legacy_presentation"),
]
#: R4-M8：`schemas/adapters.py` 的两项**已从清单移除** —— 它现在是纯 re-export 门面，
#: 一个 `def to_legacy_` 都没有（清单留着它就会红："找不到 def"）。
#: 实现全在 `app/projection/`（graph/scene 两个域模块 + dto 门面）。

#: 委托体允许的最大行数（含签名与 docstring）。超过就说明"又长出逻辑了"。
MAX_BODY_LINES = 45


def _function_source(rel: str, name: str) -> str:
    src = (APP / rel).read_text(encoding="utf-8")
    m = re.search(rf"^def {re.escape(name)}\(", src, flags=re.M)
    assert m, f"{rel} 里找不到 def {name}( —— 清单过期了？"
    rest = src[m.start():]
    nxt = rest.find("\ndef ", 1)
    return rest if nxt == -1 else rest[:nxt]


class TestDelegationStaysThin:
    def test_delegating_projections_are_thin(self):
        offenders = []
        for rel, name in DELEGATING:
            body = _function_source(rel, name)
            lines = [ln for ln in body.splitlines() if ln.strip()]
            if len(lines) > MAX_BODY_LINES:
                offenders.append(f"{rel}:{name}（{len(lines)} 行 > {MAX_BODY_LINES}）")
        assert not offenders, (
            "这些投影已经不再是薄委托（有人把逻辑写回副本了，事故路径复活）：\n  "
            + "\n  ".join(offenders)
        )

    def test_delegating_projections_actually_delegate(self):
        """必须出现转发调用 —— 否则"薄"可能是因为它只是空壳/占位。"""
        offenders = []
        for rel, name in DELEGATING:
            body = _function_source(rel, name)
            if not re.search(r"(from app\.|import .*to_legacy_|_projection|_project\()", body):
                offenders.append(f"{rel}:{name}")
        assert not offenders, f"这些投影没有转发调用（可能已成空壳）：{offenders}"
