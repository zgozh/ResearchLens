# 投影契约（canonical → legacy）

本文件是 M10「投影层收敛」的**权威清单**：每个域**哪一份是真实实现**、另一份是薄委托、
以及哪些不变量被测试锁住。新增/修改投影前先读这里。

## 为什么需要这份清单

这个仓库因为"两份投影只修一处"出过**两次事故**（D-48：`_legacy_step` 丢掉 `figure_refs`；
D-60：问答投影漏了 `mode`，前端无法区分"通用回答"与"拒答"）。事故的形态都一样：
API 表面没有异常，但某个功能整块失效，而且**只有用户会发现**。

## 现状：每个域只剩一份真实实现

| 域 | 真实实现（唯一） | 另一侧 | 收敛记录 |
|---|---|---|---|
| graph | `modules/graph/legacy.to_legacy_graph` | `schemas/adapters.to_legacy_graph` 委托 | D-93 |
| evaluation | `schemas/adapters.to_legacy_evaluation` | `modules/evaluation/legacy.to_legacy_evaluation` 委托 | D-100 |
| qa | `schemas/adapters.to_legacy_answer` | `modules/qa/legacy.to_legacy_answer` 委托 | ADR-0060 |
| scene | `modules/scene/legacy.to_legacy_presentation` | `schemas/adapters.to_legacy_presentation` 委托 | D-101 |
| paper / detail / claim / claim_summary / evidence | `schemas/adapters.py` | 无副本 | — |

**为什么权威侧不在同一个包里**：收敛时按"**哪一份是线上在用、且被验收覆盖的**"来定，
而不是按包的位置来定 —— 例如 scene 的权威侧是 `modules/scene/legacy`，因为
`schemas/adapters` 那份**根本没有调用方**（D-101）。把线上路径换成没人用过的实现，
风险高于收益。

## 被测试锁住的不变量

1. **双读一致性**（`app/tests/unit/test_projection_dual_read.py`）：
   同一 canonical 对象经两处投影，**顶层键集合 + 各字段逐一相等**。
   评测域连"顶层多/少一个字段"都会被抓住（D-100 加强）。
2. **静态门禁**：`def to_legacy_` 只允许出现在白名单文件里（新增副本立刻变红）；
   白名单里"已经没有投影"的条目也会变红，逼着清单随收敛缩小。
3. **薄委托门禁**：非权威侧的函数体必须**只是委托**（行数与"是否出现转发调用"双重判据），
   防止有人把逻辑又写回副本里。

## 尚未完成（如实登记）

方案 §M10-1 要求把实现**物理迁移**到 `app/projection/` 包、`adapters` 改 re-export、
白名单收窄到只剩该包。目前是"**逻辑上唯一实现 + 测试防漂移**"，
**不是**"包结构上的唯一入口"。这一步是纯机械迁移，但要动 9 个函数与多处导入，
计划单独一轮完成。

## 图谱域字段清单（R4-M9 增补）

`modules/graph/legacy.py::to_legacy_graph` 是图谱投影的**唯一实现**，
`schemas/adapters.to_legacy_graph` 薄委托给它。节点 props 的构成：

| 键 | 来源 | 说明 |
|---|---|---|
| `status` | `GraphNodeRecord.status` | verified / unverified |
| `claim_id` / `evidence_id` / `media_id` / `anchor_ids` | 节点字段 | 定位与取图 |
| `support_status` | `graph.service._evidence_node_props` | 证据的支撑结论 |
| `quote` | 同上 | 逐字原文（截断 400） |
| `page` | 同上 | 1-based 页码 |
| `anchor_id` | 同上 | 锚点 |
| **`validation`** | 同上（**R4-M9 新增**） | `{decision, semantic_status, reasons}`，供前端 `VerdictBadge` 四分类；缺判定时为 `null`（前端不渲染徽标） |

**纪律**：props 由 `**(dict(getattr(n, "props", None) or {}))` **整体透传**，
不在投影层做白名单筛选 —— 白名单式投影漏字段时 API 表面看不出异常，
但功能会整块失效（ADR-0058 / D-48 的真实前科：`props.support_status` 曾被丢掉）。
新增 props 字段**只需在 service 层装配 + 在此登记**，投影层无需改动。
---

## R4-M8 物理迁移完成记录（迁移后的权威清单）

**迁移前**：逻辑上唯一，物理上散在三处（`modules/graph|scene/legacy.py`、
`schemas/adapters.py`），由两层门禁防漂移。
**迁移后**：**全部权威实现住在 `app/projection/`**。

| 文件 | 角色 | 内容 |
|---|---|---|
| `projection/graph.py` | **权威** | `to_legacy_graph`（dict 形态，props 整体透传） |
| `projection/scene.py` | **权威** | `to_legacy_presentation`（dict 形态，含 `_dedup_ints`） |
| `projection/dto.py` | **权威（门面）** | `to_legacy_paper/detail/evidence/claim/claim_summary`，以及 graph/presentation 的 **Pydantic 包装版**（返回 `GraphOut`/`PresentationOut`） |
| `schemas/adapters.py` | **re-export 门面** | 一行逻辑都没有；保留导入路径免得几十个调用点同时改名 |
| `modules/graph/legacy.py` | 薄委托 | `to_legacy_graph` → `projection.graph` |
| `modules/scene/legacy.py` | 薄委托 | `to_legacy_presentation` → `projection.scene` |
| `modules/evaluation/legacy.py` | 薄委托 | `to_legacy_evaluation` → `projection.dto` |
| `modules/qa/legacy.py` | 薄委托 | `to_legacy_answer` → `projection.dto` |

### 门禁（三条，全部可执行）

1. **`test_no_projection_copies_outside_allowlist`**：`def to_legacy_` 不得在清单之外再生；
2. **`test_authorities_live_in_projection`**（R4-M8 新增）：除登记过的薄委托外，
   任何 `def to_legacy_` **必须**在 `projection/` 下 —— 这条把"还差多少"变成断言；
3. **`test_delegating_projections_are_thin`**：薄委托 ≤45 行且必须有转发调用。

### ⚠️ 迁移时踩到的坑（下次搬东西请先看这条）

`schemas.adapters.to_legacy_graph` 原本返回 **`GraphOut`（Pydantic）**，而
`projection/graph.py` 的实现返回 **dict**。如果 re-export 门面直接从
`projection.graph` 再导出，**返回类型会悄悄改变** —— 双读一致性测试当场抓到
（`'dict' object has no attribute 'model_dump'`）。

正确做法：门面必须再导出 `projection/dto.py` 里的**包装版**（它内部委托 dict 实现并包成
Pydantic）。**搬迁不得改变对外契约**，哪怕只是"顺手少包一层"。

### 仍可继续做的纯整理（非功能，不影响任何行为）

`projection/dto.py` 还可以按域拆成 `projection/{papers,claims,qa,evaluation}.py`
（方案原文的目录形态）。当前拆分：拆分需要先把 `to_legacy_evidence` 挪到
`projection/claims.py` 以避免 `dto ↔ qa` 循环导入。**纯文件组织，无行为变化，随时可做。**