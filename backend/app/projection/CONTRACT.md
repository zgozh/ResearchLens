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
