"""M10 安全网：跨域**双读一致性** + 投影副本静态门禁（REFACTOR_PLAN_R3）。

## 为什么先写这个

M10 要把 `schemas/adapters.py` 与 `modules/{graph,scene,evaluation,qa}/legacy.py` 里
**重复的 canonical→legacy 投影**合并成一处。这个仓库已经因为"两份投影只修一处"
出过两次事故（D-48/D-60）——所以合并之前**必须先有能抓住分叉的测试**，
否则合并本身就是新的风险。

本文件两件事：
1. **双读一致性**：同一份 canonical 对象分别经两处投影，结果必须逐字段相等
   （不等就是已经分叉了，合并前必须先知道）；
2. **静态门禁**：`def to_legacy_` 只允许出现在**白名单**里；新增副本会立刻变红
   （合并完成后白名单收敛到只剩 `app/projection/`）。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.contracts.common import Scope, Warning
from app.contracts.evaluation import EvaluationReport, MetricEntry, MetricValue

SCOPE = Scope(paper_id=7, revision_id="rev-proj")

APP = Path(__file__).resolve().parents[2]  # backend/app

#: 允许出现 `def to_legacy_` 的位置。
#:
#: **两种角色要分清**（R4-M8 澄清）：
#: - **权威**（实现住在这）→ 只能在本包的 `projection/` 下；
#: - **委托**（只是转发）→ 原位置保留同名函数做转发，仍会命中 `^def to_legacy_`，
#:   因此也必须登记（它们由 `test_projection_thin_delegation.py` 保证"薄 + 真的转发"）。
#:
#: 每加一项都等于承认"这里还有一份非权威侧"——所以它只能变小、不能变大。
ALLOWED_PROJECTION_FILES = {
    "projection/graph.py",
    "projection/scene.py",
    "projection/dto.py",
    "modules/evaluation/legacy.py",
    "modules/qa/legacy.py",
    "modules/graph/legacy.py",
    "modules/scene/legacy.py",
}

#: **非权威侧**（薄委托）——与 `test_projection_thin_delegation.DELEGATING` 的模块部分一致。
#: 用来把"权威"和"委托"分开：除这些之外，任何 `def to_legacy_` 都必须在 `projection/` 下。
#:
#: R4-M8 后 `schemas/adapters.py` **已从这里消失**：它现在只是 re-export 门面，
#: 一个 `def to_legacy_` 都没有（实现全在 `projection/dto.py`）。
DELEGATE_FILES = {
    "modules/evaluation/legacy.py",
    "modules/qa/legacy.py",
    "modules/graph/legacy.py",
    "modules/scene/legacy.py",
}

#: 迁移完成的目标：**权威只住在 projection/**。当前已达成的部分：graph / scene / dto。
#: 仍可继续做的**纯整理**（非功能）：把 `projection/dto.py` 按域拆成
#: `projection/{papers,claims,qa,evaluation}.py` —— 不影响任何行为，随时可做。
AUTHORITY_PREFIX = "projection/"

#: 迁移完成的目标：**权威只住在 projection/**。当前还差 evaluation/qa（在 adapters 里）
#: 与 paper/claims 投影（也在 adapters 里）—— 差距由 `test_authorities_live_in_projection`
#: 写成可执行断言，而不是一句"待办"。
AUTHORITY_PREFIX = "projection/"


def _answer_record():
    from app.contracts.evidence import ArtifactText, StatementSpan
    from app.contracts.qa import AnswerRecord

    return AnswerRecord(
        scope=SCOPE, id="ans-1", question="主要贡献是什么？",
        text=ArtifactText(text="结论句。", spans=[StatementSpan(start_cp=0, end_cp=4, statement_id="s1")]),
        statements=[], evidence=[], grounded=False, confidence="Medium",
        note="note", mode="generated", warnings=[Warning(code="w", message="m", stage="qa")],
    )


def _graph_artifact():
    from app.contracts.evidence import ArtifactText
    from app.contracts.graph import GraphArtifact, GraphEdgeRecord, GraphNodeRecord

    label = ArtifactText(text="节点标签", spans=[])
    return GraphArtifact(
        scope=SCOPE, id="g-1",
        nodes=[GraphNodeRecord(id="n1", kind="claim", label=label, status="verified",
                               anchor_ids=[], props={"support_status": "supports"})],
        edges=[GraphEdgeRecord(id="e1", source="n1", target="n1", relation="supports",
                               label=label, status="verified")],
    )


def _evaluation_report():
    return EvaluationReport(
        scope=SCOPE, id="eval-1",
        metrics=[
            MetricEntry(name="quote_exact_rate", value=MetricValue(value=1.0, status="measured")),
            MetricEntry(name="support_recall", value=MetricValue(status="not_evaluated",
                                                                 reason="no_golden_truth")),
        ],
        warnings=[],
    )


class TestDualReadConsistency:
    """同一 canonical 对象经两处投影必须完全一致（分叉 = 事故前兆）。"""

    def test_qa_answer_projection_agrees(self):
        from app.modules.qa.legacy import to_legacy_answer as module_proj
        from app.schemas.adapters import to_legacy_answer as adapter_proj

        rec = _answer_record()
        a = adapter_proj(rec)
        b = module_proj(rec)
        assert a == b, f"问答投影已分叉：\n adapters={a}\n module  ={b}"

    def test_graph_projection_agrees(self):
        from app.modules.graph.legacy import to_legacy_graph as module_proj
        from app.schemas.adapters import to_legacy_graph as adapter_proj

        art = _graph_artifact()
        a = adapter_proj(art)
        b = module_proj(art)
        # 两处返回类型不同（GraphOut vs dict）：比**载荷**。
        # `revision_id` 只有适配器版本带（GraphOut 的字段），module 版本不含 —— 属既有差异，
        # 比较时排除；除此之外必须逐字段相等。
        assert a.model_dump(exclude={"revision_id"}) == b, (
            f"图谱投影已分叉：\n adapters={a.model_dump()}\n module  ={b}"
        )

    def test_evaluation_projection_agrees(self):
        from app.modules.evaluation.legacy import to_legacy_evaluation as module_proj
        from app.schemas.adapters import to_legacy_evaluation as adapter_proj

        rep = _evaluation_report()
        a = adapter_proj(rep)
        b = module_proj(rep)
        # 两处返回类型不同（Pydantic vs dict），比 metrics 与 overall 两项
        am, bm = a.metrics, b["metrics"]
        # 顶层键也要对齐（只比 metrics 会漏掉"一边多/少一个顶层字段"这类分叉）
        assert set(a.model_dump().keys()) == set(b.keys()), (
            f"顶层键分叉：{sorted(a.model_dump())} != {sorted(b)}"
        )
        assert set(am.keys()) == set(bm.keys()), "metrics 键集合分叉"
        for key, value in am.items():
            assert value == bm[key], f"{key} 分叉：{value} != {bm[key]}"


class TestProjectionStaticGate:
    """静态门禁：`def to_legacy_` 不得在白名单之外再生；**权威只许住在 `projection/`**。"""

    def test_no_projection_copies_outside_allowlist(self):
        found: list[str] = []
        for path in APP.rglob("*.py"):
            rel = path.relative_to(APP).as_posix()
            if rel.startswith("tests/"):
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(r"^def to_legacy_", text, flags=re.M):
                found.append(rel)
        extra = sorted(set(found) - ALLOWED_PROJECTION_FILES)
        assert not extra, (
            "在白名单之外发现了新的投影副本："
            f"{extra}\nM10 的目标是**收敛**，不是再复制一份；请改调既有实现。"
        )

    def test_authorities_live_in_projection(self):
        """**R4-M8 的核心不变量**：除登记过的薄委托外，`def to_legacy_` 必须在本包 `projection/` 下。

        这条把"迁移还差多少"变成可执行断言：搬走一块，非 `projection/` 的命中就少一块。
        当前剩下的都在 `schemas/adapters.py`（evaluation / qa 与 paper/claims 投影）。
        """
        offenders: list[str] = []
        for path in APP.rglob("*.py"):
            rel = path.relative_to(APP).as_posix()
            if rel.startswith("tests/"):
                continue
            text = path.read_text(encoding="utf-8")
            if not re.search(r"^def to_legacy_", text, flags=re.M):
                continue
            if rel in DELEGATE_FILES:
                continue          # 薄委托（由 thin-delegation 门禁保证它确实是转发）
            if not rel.startswith(AUTHORITY_PREFIX):
                offenders.append(rel)
        assert not offenders, (
            "这些位置既不是登记过的薄委托、也不在 `projection/` 下 —— "
            f"它们是**还没搬家的权威实现**：{sorted(set(offenders))}"
        )

    def test_every_imported_symbol_still_exists_in_the_facade(self):
        """**再导出门面必须覆盖所有被 import 的符号**（含私有辅助）。

        为什么专门加这条：R4-M8 搬迁后第一版门面只再导出了公开函数，而
        `modules/papers/legacy.py` 从**这里**导入 `_legacy_step`，且那句 import 写在
        **函数体内** —— 单元测试全绿，直到端到端验收打 `GET /api/papers/{id}` 才 500。
        「函数体内 import」是静态分析看不见的盲区，所以这里直接扫源码把所有
        `from app.schemas.adapters import X, Y` 的符号名收集起来逐个验证。
        """
        import importlib

        module = importlib.import_module("app.schemas.adapters")
        missing: list[str] = []
        sites = 0
        for path in APP.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            # 锚定行首（允许缩进）—— 否则文档/注释里出现的示例文字会被当成真的 import
            for m in re.finditer(
                r"^\s*from app\.schemas\.adapters import ([^\n]+)$", text, flags=re.M
            ):
                sites += 1
                raw = m.group(1).strip().strip("()")
                for name in raw.split(","):
                    name = name.strip().split(" as ")[0].strip()
                    if not name or name == "\\":
                        continue
                    if not hasattr(module, name):
                        missing.append(f"{path.relative_to(APP).as_posix()}: {name}")
        assert sites > 0, "没扫到任何 `from app.schemas.adapters import` 站点 —— 扫描逻辑失效了？"
        assert not missing, (
            "这些符号被别处 import，但再导出门面里没有：\n  " + "\n  ".join(sorted(set(missing)))
        )

    def test_allowlist_has_no_stale_entries(self):
        """白名单里列了、但实际已经没有投影的文件 → 说明合并有进展，清单该收敛了。"""
        present = set()
        for rel in ALLOWED_PROJECTION_FILES:
            path = APP / rel
            if path.exists() and re.search(
                r"^def to_legacy_", path.read_text(encoding="utf-8"), flags=re.M
            ):
                present.add(rel)
        stale = sorted(ALLOWED_PROJECTION_FILES - present)
        assert not stale, f"白名单里这些文件已经没有投影了，请从清单里删掉：{stale}"
