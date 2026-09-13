# ResearchLens 第三轮重构方案设计

> 版本：v1.0（2026-09-13）
> 性质：架构方案文档。不含完整业务实现代码；仅含接口签名与伪代码。
> 使用方式：第六章每条任务（M1–M12）可独立复制给编码模型逐个实现；验收流程按"先写失败测试 → 改 → 跑全量 pytest 与端到端验收 → 记 ADR"。
> 关联文档：`docs/REFACTOR_PLAN.md`（第二轮方案）、`docs/REFACTOR_SPEC.md`、`docs/DECISIONS.md`。
> 本轮原则：**不重做已完成的事**（§1.2 白名单），所有"必须修复"项给出可断言验收判据。

---

## 一、原有项目现状与问题诊断

### 1.1 项目与技术栈（事实）

- **产品**：ResearchLens —— 把一篇真实论文变成可交互科研成果：解析 → 结构化导读 → 断言/证据链 → 图表 → 研究图谱 → 方法动画 → 讲解分镜 → 证据问答 → 自动评测。
- **后端**：Python 3.12 / FastAPI / SQLAlchemy 2 + Alembic / PostgreSQL；Docker Compose 四容器（`backend:8002→8000`、`worker`、`frontend:4002→3000`、`db:5432`）。
- **前端**：Next.js 14 App Router + React 18 + Tailwind + `@xyflow/react` + KaTeX；前后端不同源，后端地址由 `absoluteApiUrl()` 拼接。
- **模型**：DashScope `qwen-plus`（对话）+ `text-embedding-v3`（向量）；PDF 解析走 MinerU（云），产物含 `table_html`、LaTeX、`<sup>` 类行内标签。
- **数据双轨**：legacy 表 + canonical 表（`claim_records/statements/validations/evidence_records/media/section_records/...`），对外同时提供 canonical 端点与 legacy 兼容投影。

### 1.2 前两轮已完成、**不要重复设计**的部分

| 模块 | 现状（已实地核对） |
|---|---|
| 富文本渲染内核 | `frontend/lib/richtext.ts` 是唯一解析/渲染实现，`MathText/LongText/TableRender/RichText/ExtractedFormula/SourceMedia(题注)` 都已委托它；真实语料 236 段 0 残留 |
| 文本规范化 | `backend/app/modules/textnorm/`（纯规则、零 LLM），已被证据门消费 |
| SSE 终结事件保证 | `modules/qa/stream.py` 所有事件进保护区，任何异常收敛成唯一 `error`；等待期发 `: ping`；流级 deadline |
| 断流恢复端点 | `GET /api/papers/{id}/qa/answers/{answer_id}` 已存在并可用 |
| 引用重定位 | `gate.build_candidates` 在指定块定位不到时按全文逐字重定位（只接受 precise，排除 `origin=generated` 块） |
| 非研究发现过滤 | `gate._is_non_claim_statement` 拦参考文献/许可声明/页脚 |
| 媒体策略 | 前后端已收敛（实测分叉 0/14）；`MediaViewer` 有旋转/缩放/复位 |
| 图谱布局 | `frontend/lib/graphLayout.ts` 分层布局，断言节点包围盒不相交 |
| 评测原因码 | `MetricValue.reason` + legacy 投影 `metrics.not_evaluated_reasons` |
| 卫生门禁 | `backend/app/tests/unit/test_text_hygiene_gate.py`（75 条）+ `npm run test:hygiene`（真实语料） |

### 1.3 本次必须修复的问题（本轮新报，根因已定位并经代码核实）

**P1【必须修复】证据文本在两处面板仍是纯文本渲染，LaTeX 源码直接暴露**
- 现象：用户看到证据链/问答证据卡里显示 `For the base model, we use a rate of $P _ { d r o p } = 0 . 1$` 原文。
- 代码实证：`frontend/components/views/QAView.tsx:369/371` 两处 `{e.text || e.quote}` 直接插值；`components/evidence/EvidenceDrawer.tsx` 同样未走 `lib/richtext.ts`。
- 关键判定：**不是"未转义字符污染了判定"** —— A/B 实测（同陈述、同证据、只差输入是否规范化）判定改变 **0 条**；也不是"没重新引用"。这是**纯展示层漏面**。
- 库内证据引文必须保持原文切片（纪律 2：逐字来自原文，不许改写过库）；清洗只能发生在渲染层。
- 必须做成：**任何展示证据/引文/回答文本的地方都必须过同一渲染内核**，并有一条**穷举式**测试防止再漏（M1/M3）。

**P2【必须修复】证据链"未支持"的语义要能被用户读懂**
- 现状分布（paper 7 实测）：`verified 64 / unverified 6 / rejected 2 / contested 1`。
  - 6 条 `unverified` 的 reasons =「该句不是研究发现（参考文献/许可声明/页脚）」——**系统故意拦下的**，但 UI 与真正"证据不足"混在一起显示成"未支持"；
  - 1 条 `contested` 是**真矛盾**（原文 β₁=0.9 vs 陈述写 0）；
  - 2 条 `semantic=supports` 但 `decision=rejected`（另有原因）。
- 必须做成：UI 把"未支持"细分为**四类不同含义**并可展开看 reasons：`非研究发现` / `真矛盾` / `有支持但未通过其他检查` / `证据不足`。用户看到"未支持"时必须能回答"为什么"。

**P3【必须修复】证据问答前端显示"被中断/没有生成内容"，但服务端已产出并落库**
- 实测：按浏览器同样的 POST `/qa/stream`，事件序列 `meta → status → status → final`，4s 内必发 final（三条默认问题均验证）。服务端无恙。
- 根因在**前端**：`useQAStream` + `QAView` 的"流结束但没解到 final"分支直接显示"本次回答被中断或超时，没有生成内容"（代码实证：`QAView.tsx:203-204`），**没有**先用 `meta.answer_id` 去 `GET /qa/answers/{id}` 取回，也没有降级到非流式 `POST /qa`。
- 用户明确要求：**"应该直接完全放开，不要限制"**。
- 必须做成（三件事一起）：
  1. **绝不空答**：失败路径先取回落库结果 → 再非流式兜底 → 最后才提示可重试（且文案不得说"没有生成内容"）；
  2. **策略放开**：论文相关问题检索不到证据时，**优先给通用回答并标注"通用回答（未使用论文原文）"**，其次"论文中没有提到 X"，只有模型不可用时才如实说明；
  3. **可观测**：每次流式回答落一条审计（事件序列、是否拿到 final、异常类型、answer_id），否则线上"被中断"无法定位。

**P4【必须修复】自动评测"全部显示未评测"——前端把 `MetricValue` 对象当数字用**
- 实测：`GET /api/papers/7/evaluation` 返回真实值（`source_asset_coverage 0.3571`、`anchor_page_accuracy 1.0`、`quote_exact_rate 1.0`、`support_precision 0.6667` …）；而 `GET /api/papers/7/exhibits` 的 `evaluation.metrics` 是 **`list[MetricEntry]`**，其中 `entry.value` 是 **`MetricValue` 对象**。
- 代码实证（`EvalView.tsx`）：L65-68 优先把持久化 report 的 `entry.value`（对象）写入 `out[entry.name]`；L68 只在**键不存在**时才填 legacy 数字；L48-50 `toNumber()` 对对象执行 `Number({...})` = `NaN` → 全部渲染成"未评测"。
- 必须做成：前端有**唯一**的指标解析函数，能同时吃 `MetricValue` 对象 / 数字 / `list[MetricEntry]` / `dict`，并在无法解析时**明确区分**"后端没给值"与"前端解析失败"（后者是 bug，不能静默显示成未评测）。

**P5【必须修复】验收脚本不在仓库里，无法回归**
- 代码实证：端到端脚本（`verify_route_a.py` / `verify_graph.py` / `verify_e2e_extra.py` / `verify_metrics_live.py` / `verify_qa_stability.py`）躺在 `.scratch/`（被 gitignore），同目录还混有 100+ 一次性诊断脚本与 commit message 草稿。
- 必须做成：**纳入仓库**（`scripts/acceptance/`）并有一条命令跑全部，作为交付门禁。

### 1.4 建议优化（第二轮已知、本轮一并规划）

1. **投影层收敛**：`schemas/adapters.py` 与 `modules/{claims,graph,scene,evaluation,qa}/legacy.py` 仍各有一份 canonical→legacy 投影（D-48/D-60 两次事故的结构根因），需收敛为**一处实现 + 契约测试**。
2. **阶段进度与断点续跑**：导入约 4 分钟（AI 起草参考断言 + 题库作答），用户看不到进度、中断后只能重头再来、重复计费。
3. **文本卫生门禁扩面**：把卫生扫描从"章节/表格/媒体题注"扩到**证据/问答/评测**所有展示路径（本轮 P1 正是漏面导致）。
4. **评测可测性**：`anchor_region_hit_rate` 在原文无坐标矩形时永远不可测（拒绝编造 IoU，属设计选择）——要保证 UI 说明清楚，而不是混进"未评测"。
5. **金标集口径**：AI 起草的参考断言只是 proxy，`overall_score` 需要人工确认后才有值；UI 必须把两种口径分开显示（已有 `ai_overall_score` 字段）。

---

## 二、本次重构总体目标与硬性约束

### 2.1 业务目标（每条均为可断言判据）

1. **可读**：任何展示论文文本的位置（导读/全文/表格/媒体题注/**证据卡**/**证据抽屉**/**问答回答**）都不得出现未渲染的 LaTeX 或 HTML 标签。
   - 验收判据：仓库内维护一份机器可读的"展示路径清单"（组件 + 数据源字段），门禁遍历清单逐点渲染真实脏语料，正则扫描 `$`/`$$`/`\tag`/`<[a-z]+>` 字面量/控制符，**命中数 = 0**；清单外的面板被发现直接渲染证据/引文字段时门禁变红（防新漏面）。
2. **可解释**：每条"未支持"都能定位到具体原因类别与理由文本。
   - 验收判据：对 paper 7 实测分布的四类样本（non_claim × 6 / contested × 1 / rejected × 2 / insufficient）各构造一例，`<VerdictBadge>` 渲染出对应四类标签且展开后 reasons 文本逐字等于后端下发；未知字段组合回落"证据不足"且 reasons 不丢。
3. **可用**：问答在任何路径下都不空答。
   - 验收判据：注入三种故障（流中途切断 / final 丢失 / 模型超时），前端最终展示的回答文本均非空，且 DOM 中**不出现**"没有生成内容"文案；后端注入"生成空串 / gate 全拒 / 检索为空"三种故障，落库 answer 的 `text` 或 `statements` 均非空。
4. **可信**：指标"有值/未评测"的判定必须与后端一致。
   - 验收判据：同一指标值以四种形态（`MetricValue` 对象 / number / `list[MetricEntry]` / dict）输入 `evalMetrics.parse`，输出 `value` 完全相等；对 paper 7 真实响应，前端显示值与 `GET /evaluation` 的四个已知值（0.3571 / 1.0 / 1.0 / 0.6667）逐一相等；无法解析的输入产出 `source='unparsable'` 且 UI 显示"数据异常"而非"未评测"。
5. **可回归**：验收脚本进仓库、一条命令跑全。
   - 验收判据：干净克隆后执行 `python scripts/acceptance/run_all.py`（或等价 npm 脚本）输出机读 JSON 汇总；服务不可达时以非零退出码 + 明确错误信息失败，**不得**静默跳过。

### 2.2 硬性约束

- **技术栈不变**：FastAPI + SQLAlchemy/Alembic + PostgreSQL + Next.js App Router + Tailwind + `@xyflow/react` + KaTeX；模型侧 DashScope（`qwen-plus` + `text-embedding-v3`）。
- **兼容既有接口**：所有既有字段不得删除、不得改语义；新增一律可选带默认值。
- **不引重型依赖**：KaTeX/DOMPurify 级别可用；禁图布局引擎、富文本编辑器框架、状态管理大件。
- **部署约束**：`docker-compose`（非 `docker compose`）；schema 变更走 Alembic expand-first。
- **数据纪律（不可破坏）**：
  1. 未评估的指标**不许填 0**，必须 `not_evaluated` + 原因码；
  2. **证据引文逐字来自原文块**，不许改写原文来"修显示"；显示层的清洗只能作用于渲染，不得回写库；
  3. 机器构造的金标集**不当作人工真值**，AI 口径必须标明；
  4. 展示层不得把"位置推断"当"题注匹配/原件"。
- **性能**：问答首字节 < 2s；任何路径 ≤120s 必有终结结果；导入 ≤ 6 分钟。

---

## 三、本次重构总体架构设计

### 3.1 目录树（目标形态，只列**变化**部分）

```
backend/app/
  projection/                     # 【新增·收敛】canonical→legacy 唯一投影入口
    __init__.py                   #   对外只 re-export to_legacy_* 系列
    claims.py graph.py scene.py evaluation.py qa.py
    CONTRACT.md                   #   字段清单（契约测试比对基准）
  modules/
    qa/
      stream.py                   # 【扩展】终结事件保证（已有）+ 写审计
      service.py                  # 【扩展】三档路由 + 绝不空答不变量
      audit.py                    # 【新增】流式回答审计（record/query）
    evidence/
      gate.py                     # 【扩展】reasons 分类稳定化（稳定 reason code，供 UI 四分类）
  schemas/
    adapters.py                   # 【收敛】投影函数迁出，仅 re-export + DeprecationWarning
  tests/hygiene/                  # 【扩展】卫生门禁扩到证据/问答/评测路径
frontend/
  lib/
    evalMetrics.ts                # 【新增】唯一指标解析（MetricValue/list/dict/number）
    evidenceVerdict.ts            # 【新增】verdict → 四类语义 + 文案
    renderPaths.ts                # 【新增】展示路径清单（M1 穷举门禁的数据源）
    richtext.ts                   # 【已有】唯一富文本内核（本轮扩面消费，不改实现）
  components/
    evidence/EvidenceDrawer.tsx   # 【修】引文/原文改走 <RichText>
    views/QAView.tsx              # 【修】证据卡走 <RichText>；断流三档兜底；策略标注
    views/EvalView.tsx            # 【修】删除本地 toNumber/优先级拼装，改调 evalMetrics
    evidence/VerdictBadge.tsx     # 【新增】四分类徽标 + reasons 展开
    evaluation/MetricCard.tsx     # 【新增】统一指标卡片（值/原因码/口径徽标）
  hooks/
    useQAStream.ts                # 【修】断流状态机：answer_id 恢复 → 非流式兜底 → 可重试
scripts/acceptance/               # 【新增·入库】端到端验收脚本 + run_all 一条命令
  README.md                       #   跑法、环境变量、退出码约定
```

**目录决策说明**：
- `renderPaths.ts` 单独成文件而非散在测试里：清单是"产品事实"（哪些面板展示论文文本），新增面板必须登记，门禁才能防漏；测试只消费它。
- `VerdictBadge/MetricCard` 放组件目录而非塞进视图：两处视图（ClaimView/QAView 证据卡、EvalView/exhibits 面板）都要复用。
- 审计查询端点挂在 canonical 路由下（运维向），不进 legacy 投影范围。

### 3.2 关键数据流

**证据展示链路（P1 修复路径）**：

```
GET /papers/{id}/claims/{cid} | /statements | /qa 回答里的 citations
  → evidence[].quote / source_text（库内保持原文切片，纪律 2，不改写）
  → 前端统一渲染入口：<RichText value={quote} density="compact" />
      （宽松模式：后端未给规范化字段时，richtext.ts 前端等价清洗）
  → 渲染输出在任何面板都不含 $ / $$ / \tag / 裸标签
  → renderPaths.ts 清单登记每个消费点；M3 门禁逐点扫描
```

**问答链路（放开后，P3）**：

```
POST /papers/{id}/qa/stream
  → meta{answer_id, mode}（已落库，status=streaming）
  → service 三档路由：
      有证据      → generated/extractive（带 citations）
      检索为空     → general（note="通用回答（未使用论文原文）"，无 citations）
                     或 not_mentioned（能锁定对象 X 时："论文中没有提到 X"）
      模型不可用   → error{code:LLM_UNAVAILABLE, retryable:true}（如实说明）
  → 唯一终结事件（final|error，已有保证）→ 写 qa_audit 一行
前端 useQAStream 状态机：
  completed(final)     → 正常展示
  断流/final 丢失/超时 → recovering：GET /qa/answers/{answer_id} 取回
      ├ 取到完整答案    → completed（标注"连接中断，已恢复结果"）
      ├ 仍 streaming    → 退避重拉 ≤3 次 → 失败则转非流式兜底
      └ 取不到          → 非流式兜底：POST /qa（同问）→ 展示结果
  全部失败             → failed（可重试按钮；文案只说"连接异常/可重试"，
                         禁止"没有生成内容"）
```

**评测展示链路（P4 修复路径）**：

```
/exhibits.evaluation.metrics（canonical list[MetricEntry]，entry.value=MetricValue 对象）
  ∪ /evaluation.metrics（legacy dict，数字 + not_evaluated_reasons）
  → lib/evalMetrics.ts 唯一解析：
      parse(raw) -> MetricView{ name, value, status, unit, reason, source }
      归一优先级：canonical entry 优先；同键 legacy 数字仅在 canonical 缺键时补
      （修复 EvalView 现 bug：对象写入后 legacy 不再覆盖）
  → <MetricCard>：measured/proxy 显示值 + 单位；
      not_evaluated 显示 reason 码 + 中文说明；
      unparsable 显示"数据异常（前端解析失败）"并上报告警
  → overall_score（人工口径）与 ai_overall_score（AI 口径）分区显示，互不冒充
```

### 3.3 依赖增减

- **新增**：无强制新增依赖（全部自研/复用现有）。
- **收敛/移除**：
  - `schemas/adapters.py` 投影函数迁入 `app/projection/`，原文件改 re-export + DeprecationWarning；
  - `modules/{claims,graph,scene,evaluation,qa}/legacy.py` 删除手写投影，仅保留"canonical 优先 + 旧表兜底"读取编排；
  - 前端 `EvalView` 内的 `toNumber()` 与临时优先级拼装删除，改调 `lib/evalMetrics.ts`；
  - `.scratch/` 中 5 个验收脚本迁移入库，`.scratch/` 维持 gitignore（一次性诊断脚本不入库）。

---

## 四、模块拆分与模块职责定义

### 4.1 `rich-text-render`【已有，本轮扩面】

- **职责**：唯一富文本渲染内核（`frontend/lib/richtext.ts` + `<RichText>`）。**新增职责**：配套维护 `lib/renderPaths.ts` 展示路径清单（每条 = 组件路径 + 数据源字段 + 面板名），供 M1/M3 门禁穷举校验。
- **依赖谁**：katex、sanitize 工具。
- **被谁依赖**：全部文本展示组件；本轮新增消费者 = `EvidenceDrawer`、`QAView` 证据卡。
- **对外契约**：`<RichText value={string|NormalizedText} density="prose|compact" tone="dark|light" />`；`RENDER_PATHS: RenderPath[]`。
- **不做什么**：不改库内文本（纪律 2）；不做编辑；不做 Markdown 全语法；不决定"该不该显示"（那是各面板的职责，内核只保证"显示了就不出乱码"）。

### 4.2 `evidence-verdict`【新增·前端】

- **职责**：把后端 `validation{ decision, semantic_status, reasons[] }` 归一为四类语义 + 文案 + 图标，供 `<VerdictBadge>` 渲染。
- **依赖谁**：`lib/contracts.ts` 类型。
- **被谁依赖**：`ClaimView`、`EvidenceDrawer`、`QAView` 证据卡。
- **对外契约**：`toVerdictView(validation) -> EvidenceVerdictView{ category, label, tone, reasons }`；四类 = `non_claim`（非研究发现）/ `contradiction`（真矛盾）/ `rejected_other`（有支持但未过其他检查）/ `insufficient`（证据不足）。
- **不做什么**：不重新判定（判定只发生在后端 gate）；不修改 reasons 原文；不把 verified 折叠进此组件（verified 走既有展示）。

### 4.3 `qa-answer-policy`【重构·后端 `qa/service.py`】

- **职责**：三档路由 + **绝不空答**不变量。检索有证据 → `generated/extractive`；检索为空或低分 → `general`（标注未使用论文原文）或 `not_mentioned`（能锁定问题对象时点名）；模型不可用 → 如实 `unavailable`。闲聊/问候 → `general`。
- **依赖谁**：retrieval、ai、answer_gate（既有发布门不变）、contracts。
- **被谁依赖**：`qa/stream.py`、非流式 `/qa` 端点。
- **对外契约**：`answer(question, mode_hint?) -> QAAnswer{ mode, text, statements?, citations?, note?, grounded }`；不变量：返回前 `text` 或 `statements` 必非空。
- **不做什么**：不伪造 citation（general/not_mentioned 一律无引用、grounded=false）；不因检索空返回空白；不改 answer_gate 对 generated/extractive 的发布门语义。

### 4.4 `qa-stream-recovery`【重构·前端 `useQAStream` + `QAView`】

- **职责**：断流状态机与兜底链：`meta.answer_id` 取回 → 非流式 `POST /qa` 兜底 → 可重试。失败文案只说连接/重试事实，**禁止"没有生成内容"**。
- **依赖谁**：`lib/sse.ts`、`lib/api.ts`。
- **被谁依赖**：`QAView`。
- **对外契约**：状态机 `idle | connecting | streaming | recovering | completed | failed | unavailable`（§5.5 逐状态 UI/文案表）。
- **不做什么**：不重复发流式请求做"恢复"（恢复走落库数据与非流式）；不自行重排 sentence 事件之外的数据。

### 4.5 `qa-audit`【新增·后端 `qa/audit.py`】

- **职责**：每次流式回答落一条审计：`answer_id`、事件类型序列、终结事件类型（final/error/none）、异常类型、耗时、mode；提供查询端点供运维定位"被中断"。
- **依赖谁**：models（新表 `qa_stream_audits`，Alembic expand-first）、core。
- **被谁依赖**：`qa/stream.py`（写入）、canonical 运维端点（查询）。
- **对外契约**：`record(audit: StreamAudit) -> None`（尽力写，失败只记日志不阻断流）；`GET /papers/{id}/qa/stream-audit?limit` → `list[StreamAudit]`。
- **不做什么**：不存回答全文（只存元数据与事件序列，控制体积）；不做实时告警（本轮只落库可查）。

### 4.6 `eval-metrics-parse`【新增·前端 `lib/evalMetrics.ts`】

- **职责**：唯一指标解析。吃四种输入形态（`MetricValue` 对象 / number / `list[MetricEntry]` / dict），归一出 `MetricView[]`；区分"后端无值"（not_evaluated + reason）与"前端解析失败"（unparsable，属 bug，显式上报）。
- **依赖谁**：`lib/contracts.ts`。
- **被谁依赖**：`EvalView`、exhibits 面板。
- **对外契约**：`parseMetrics(input: unknown) -> MetricView[]`；`parseOverall(input) -> { human: number|null, ai: number|null }`。
- **不做什么**：不重新计算指标；不对 not_evaluated 填 0（纪律 1）；不合并 human/ai 口径。

### 4.7 `projection`【新增·后端】

- **职责**：canonical→legacy **唯一**投影入口 + `CONTRACT.md` 字段清单。
- **依赖谁**：contracts、models（只读）。
- **被谁依赖**：`api/routes.py`、`api/canonical.py` 兼容字段、`modules/*/legacy.py`（只保留读取编排）。
- **对外契约**：`to_legacy_claim/graph/scene/evaluation/qa(...)` 纯函数系列；静态门禁：`def to_legacy_` 全仓库只允许出现在 `app/projection/`。
- **不做什么**：不查 DB、不做业务判定、不抛 DomainError（非法输入返回 None + 日志）。

### 4.8 `acceptance-suite`【新增·`scripts/acceptance/`】

- **职责**：端到端验收脚本入库：迁移 `.scratch/` 的 5 个脚本（route_a / graph / e2e_extra / metrics_live / qa_stability），统一机读输出（JSON 行），`run_all.py` 一条命令跑全并汇总退出码。
- **依赖谁**：运行中的 docker-compose 栈（健康检查前置）。
- **被谁依赖**：交付门禁、CI、人工验收。
- **对外契约**：`python scripts/acceptance/run_all.py [--base-url URL] [--paper-id N]` → 退出码 0/非 0 + `results.json`。
- **不做什么**：不做单元测试（那是 pytest/vitest 的事）；不测 UI 像素；健康检查失败时**必须**明确报错退出，不得静默跳过。

### 4.9 `pipeline-progress`【优化·后端 pipeline + 前端导入页】

- **职责**：阶段进度事件 + 幂等键 + 断点续跑。AI 类阶段（claims 起草 / qa_bank 作答 / evaluate 裁判）跳过即不重复计费。
- **依赖谁**：全部业务模块（编排）、ai（快照）、core。
- **被谁依赖**：`/papers/{id}/process`、`/rebuild-derived`、worker、前端导入页。
- **对外契约**：`StageEvent{ stage, status, progress_pct, message }`；`POST /process { from_stage? }`；幂等键 `sha256(revision_id + stage + 输入指纹)`。
- **不做什么**：不实现阶段业务；不做跨论文批处理。

---

## 五、完整接口契约规格

> 签名级契约。`...` = 既有字段不变。新增字段均可选带默认值；既有字段不删不改语义。

### 5.1 HTTP

```python
GET /api/papers/{id}/claims/{cid}
  resp: { ..., statements: [ { ..., evidence: [ {
            quote: str,              # 原文切片（不变，纪律 2）
            source_text?: str,       # 原文上下文（不变）
            validation?: {           # 【新增可选】四分类所需的原始三件套
              decision: str, semantic_status: str, reasons: [str]
            } } ] } ] }
  说明: 后端不提供 display_text —— 明文约定"引文渲染由前端 RichText 负责"，
        避免前后端两份清洗逻辑漂移（纪律 2：库内只存原文）。

GET /api/papers/{id}/statements
  resp: 同上 evidence.validation 可选挂出。兼容: 不挂时前端按无判定处理。

POST /api/papers/{id}/qa
  req:  { question: str, mode_hint?: "auto"|"general" }
  resp: QAAnswer（见 5.3）
  err:  422 QUESTION_EMPTY | 502 LLM_UNAVAILABLE(retryable=true)

POST /api/papers/{id}/qa/stream
  req:  同上
  resp: text/event-stream；事件 meta/status/citation/sentence/final/error（既有契约不变）
  保证: 首字节 < 2s；任何路径 ≤120s 唯一终结事件（已有，本轮加审计）。

GET /api/papers/{id}/qa/answers/{answer_id}      # 既有，本轮成为恢复链第一环
  resp: QAAnswer | { status: "streaming" }
  err:  404 ANSWER_NOT_FOUND

GET /api/papers/{id}/evaluation
  resp: { ..., metrics: { <name>: number|null },   # legacy dict（不变）
          not_evaluated_reasons: { <name>: str },  # 既有（保持）
          ai_overall_score: number|null,           # 既有
          overall_score: number|null }             # 人工口径（无人工确认时 null）

GET /api/papers/{id}/exhibits
  resp: { ..., evaluation: { metrics: [ MetricEntry{      # canonical（不变）
            name: str, value: MetricValue, unit?: str } ] } }
  说明: entry.value 为 MetricValue 对象这一事实写入 contracts 注释与前端类型，
        杜绝"以为是数字"的再次误判。

GET /api/papers/{id}/qa/stream-audit?limit=50    # 【新增·运维】
  resp: { items: [ StreamAudit ] }
  err:  404 PAPER_NOT_FOUND
  权限: 与既有运维端点同级。
```

### 5.2 SSE 事件契约（不变，重申保证 + 审计挂钩）

- 事件序列 `meta → status* → citation* → sentence* → (final|error)`，终结事件恰一次（已有实现，本轮不动）。
- 新增保证：**每条流结束时**（无论 final/error/异常/客户端断开）写一条 `StreamAudit`；`terminal='none'` 的审计行即"前端看到被中断"的候选集，可按 `answer_id` 与前端恢复行为对账。

### 5.3 DTO

```python
# ── 证据四分类（前端视图模型；后端只下发原始三件套，分类逻辑唯一在前端） ──
EvidenceVerdictView = {
  category: 'non_claim' | 'contradiction' | 'rejected_other' | 'insufficient',
  label: str,                     # 中文标签：非研究发现/真矛盾/未通过其他检查/证据不足
  tone: 'gray' | 'red' | 'amber' | 'slate',
  reasons: [ { code: str, message: str } ],   # 后端 reasons 结构化（code 稳定枚举）
  quote_raw: str,                 # 原文切片（展示走 RichText）
}
# 分类规则（唯一真相，lib/evidenceVerdict.ts）：
#   reasons 含 NON_CLAIM_*              → non_claim（即使 decision=unverified）
#   semantic_status=contradicts
#     或 decision=contested             → contradiction
#   semantic_status=supports 且 decision=rejected → rejected_other
#   其余（含未知组合）                   → insufficient（reasons 原样保留，不丢）

# ── 问答 mode 语义表（qa/service.py 唯一出处，前端只展示） ──
QAMode = 'generated'      # 基于论文证据生成，有 citations，grounded=true
       | 'extractive'    # 原文抽取回答，有 citations，grounded=true
       | 'general'       # 通用回答，note="通用回答（未使用论文原文）"，无 citations
       | 'not_mentioned' # 论文未提及，note="论文中没有提到 {X}"，无 citations
       | 'abstained'     # 发布门拦截（有证据但引用不上），grounded=false，带原因
       | 'unavailable'   # 模型不可用，如实说明，retryable
QAAnswer = { answer_id, mode: QAMode, text: str, statements?: [...],
             citations?: [...], note?: str, grounded: bool, usage?: {...} }
# 不变量：text 非空 或 statements 非空（落库前断言）。

# ── 指标视图（前端 lib/evalMetrics.ts 输出） ──
MetricView = {
  name: str,
  value: number | null,           # not_evaluated/unparsable 时为 null（纪律 1）
  status: 'measured' | 'proxy' | 'not_evaluated' | 'unparsable',
  unit?: str,
  reason?: str,                   # not_evaluated 的原因码（后端下发）
  source: 'canonical' | 'legacy' | 'unparsable',
}

# ── 流式审计（后端 qa/audit.py + 端点） ──
StreamAudit = {
  answer_id: str,
  paper_id: str,
  mode?: str,
  events: [str],                  # 事件类型序列，如 ["meta","status","sentence","final"]
  terminal: 'final' | 'error' | 'none',
  error_code?: str,
  exception_type?: str,           # 未捕获异常的类名（有的话）
  elapsed_ms: int,
  created_at: datetime,
}
```

### 5.4 错误模型

沿用现有 `DomainError{ code, message, retryable, field_errors? }`。本轮涉及的错误码：

| code | 位置 | retryable | 含义 |
|---|---|---|---|
| `STREAM_NO_TERMINAL_EVENT` | 后端流自检（已有） | true | 流未产生终结事件（理论不可达，出现即告警） |
| `LLM_UNAVAILABLE` | /qa 与流内 error | true | DashScope 故障，如实告知用户 |
| `QA_RECOVERY_FAILED` | 前端内部态（不来自后端） | true | 取回 + 非流式兜底均失败；UI 显示"连接异常，可重试" |
| `METRIC_PARSE_FAILED` | 前端内部态 | false | 指标输入无法解析；UI 显示"数据异常"并 console 上报，**不得**渲染为"未评测" |
| `ANSWER_NOT_FOUND` | 恢复端点 | false | answer_id 不存在 |

### 5.5 前端组件契约

```tsx
// 唯一文本渲染入口（所有展示论文文本的面板必须用它，renderPaths.ts 登记）
<RichText value={string | NormalizedText} density="prose|compact" tone="dark|light" />

// 证据判定徽标 + reasons 展开
<VerdictBadge verdict={EvidenceVerdictView} expandable />

// 指标卡片：值 + 单位 + 口径徽标 + 原因码说明
<MetricCard metric={MetricView} />

// 问答流状态机（useQAStream 返回值）
type QAStreamState =
  | 'idle'        // 初始；输入框可用
  | 'connecting'  // 未收到 meta； spinner，无文案
  | 'streaming'   // 收到 meta、事件流入；逐句渲染
  | 'recovering'  // 断流/final 丢失/超时；文案"连接中断，正在取回已生成的结果…"
  | 'completed'   // 有完整答案；若经恢复而来，徽标"已恢复结果"
  | 'failed'      // 取回+兜底均失败；文案"连接异常，请重试" + 重试按钮（禁说"没有生成内容"）
  | 'unavailable' // 后端明确 LLM_UNAVAILABLE；文案"模型服务暂不可用，请稍后重试"
```

---

## 六、分模块开发任务清单

> 每条完整独立，可直接复制给编码模型。统一要求：遵守 §2.2 硬性约束与 §5 契约；schema 变更走 Alembic expand-first；验收流程 = 先写失败测试 → 改 → 全量 pytest + 端到端验收 → 记 ADR。
> 实现顺序建议：**W1 = M1 + M2 + M4 + M5（P1/P2/P3 核心）**；**W2 = M6 + M7 + M8 + M9（P3/P4 收尾）**；**W3 = M3 + M10 + M11（门禁与收敛）**；**W4 = M12（优化项）**。M1 必须先于 M3（清单先行，门禁随后）。

---

### M1 证据文本渲染扩面（前端）

- **模块名称**：`frontend/lib/renderPaths.ts`（新增）+ `components/evidence/EvidenceDrawer.tsx`、`components/views/QAView.tsx`（修）
- **模块职责**：消灭证据/引文/回答文本的裸渲染。QAView 证据卡（现 L369/371 `{e.text || e.quote}`）、EvidenceDrawer 引文区、以及清单登记的所有文本展示点，全部改走 `<RichText>`。
- **需要遵守的接口契约**：§5.5 `<RichText>`；§4.1 renderPaths 清单格式：
  ```ts
  type RenderPath = { id: string; panel: string; component: string;
                      field: 'quote'|'source_text'|'answer_text'|'caption'|'section_body'|...;
                      sample: string };  // sample = 该路径的真实脏语料样本
  export const RENDER_PATHS: RenderPath[];
  ```
- **业务逻辑要求**：
  1. 先把 §2.1-1 涉及的全部面板（导读/全文/表格/媒体题注/证据卡/证据抽屉/问答回答）逐条登记进 RENDER_PATHS，每条配真实脏样本（含 `$P _ { d r o p } = 0 . 1$`、`<sup>∗</sup>`、`$$…\tag{1}$$` 至少各一例）。
  2. EvidenceDrawer 与 QAView 证据卡的引文渲染替换为 `<RichText value={e.text || e.quote} density="compact" tone="dark" />`（tone 按面板实际明暗）。
  3. **不改库内文本、不改后端字段**（纪律 2：清洗只发生在渲染层）。
  4. 回答正文（answer.text）若当前已走 RichText 则仅登记清单；未走则一并替换。
- **输入输出说明**：输入为既有 API 响应（字段不变）；输出为渲染后的 React 树。零新增网络请求。
- **单元测试验证要点**（vitest + RTL）：
  - 遍历 RENDER_PATHS，对每条 sample 经对应面板渲染后的 DOM textContent 执行四正则扫描（`(?<!\$)\$(?!\$)`、`$$`、`\\tag\{`、`<[a-z]+>` 字面量、C0 控制符），命中数 = 0。
  - **穷举防漏**：静态扫描 `components/**` 中出现 `e.quote`/`e.text`/`source_text` 直接 JSX 插值的位置，凡不在 RENDER_PATHS 登记白名单内的，测试变红。
  - 回归：既有 236 段语料卫生测试继续全绿。

---

### M2 证据 verdict 四分类（前端）

- **模块名称**：`frontend/lib/evidenceVerdict.ts`（新增）+ `components/evidence/VerdictBadge.tsx`（新增）+ `ClaimView/EvidenceDrawer/QAView`（接入）
- **模块职责**：把后端 `validation{ decision, semantic_status, reasons }` 映射为四类语义（`non_claim/contradiction/rejected_other/insufficient`）+ 中文标签 + 色调，并提供 reasons 展开。
- **需要遵守的接口契约**：§5.3 `EvidenceVerdictView` 及分类规则表（该表为唯一真相）；§5.5 `<VerdictBadge>`。
- **业务逻辑要求**：
  1. 严格按 §5.3 分类规则实现，优先级自上而下：`NON_CLAIM_*` reasons → contradiction 信号 → supports+rejected → 其余回落 insufficient。
  2. reasons 需要结构化：后端 reasons 若为裸字符串数组，前端解析"码：文案"前缀为 `{code, message}`；无法解析时 code='UNKNOWN'、message 原文保留（不丢）。
  3. 未知 `(decision, semantic_status)` 组合 → insufficient + reasons 原样，**不得**抛错。
  4. 文案纪律：`non_claim` 标签为"非研究发现"（灰），说明文案含"系统主动排除，不代表证据不足"；`contradiction` 为"真矛盾"（红）；`rejected_other` 为"有支持但未通过其他检查"（琥珀）；`insufficient` 为"证据不足"（石板灰）。
- **输入输出说明**：输入 validation 三件套（可无，无时不渲染徽标）；输出 `EvidenceVerdictView` + 徽标组件。
- **单元测试验证要点**：
  - 四类各一例（取自 paper 7 实测形态）：non_claim（reasons 含"不是研究发现/参考文献"）→ "非研究发现"；contested（β₁=0.9 vs 0）→ "真矛盾"；semantic=supports+decision=rejected → "未通过其他检查"；普通 unverified 无 NON_CLAIM reasons → "证据不足"。
  - 关键反向断言：non_claim 样本的渲染结果**不含**"证据不足"字样。
  - 未知组合（如 decision='unverified', semantic_status='supports'）→ 回落 insufficient，reasons 数组长度不变。
  - 展开面板文本与后端 reasons 逐字相等。

---

### M3 卫生门禁扩面（后端 + 前端）

- **模块名称**：`backend/app/tests/hygiene/`（扩展）+ `frontend/` 卫生测试（扩展，消费 M1 清单）
- **模块职责**：把文本卫生扫描的覆盖面从"章节/表格/媒体题注"扩到**证据卡/证据抽屉/问答回答/评测文本**全部展示路径。
- **需要遵守的接口契约**：复用既有 `test_text_hygiene_gate.py` 的扫描器与 `npm run test:hygiene`；M1 的 RENDER_PATHS 清单。
- **业务逻辑要求**：
  1. 前端：卫生测试的输入源改为"RENDER_PATHS 全量 sample + 真实语料"，逐路径渲染扫描（M1 测试要点即本门禁的前端一半）。
  2. 后端：卫生扫描输入扩到 evidence 引文切片、QA 落库 answer.text、评测 reason 文案的样本集（从测试 DB fixture 或录制响应取）。
  3. **自验证用例**：测试中人为在一个面板插入一条未登记的直接插值路径 → 门禁必须变红（证明门禁不是摆设）；随后删除该注入。
  4. 清单漂移检查：RENDER_PATHS 中登记的组件文件不存在或字段不存在 → 变红（防止清单腐化）。
- **输入输出说明**：输入 = 清单 + 语料 + 源码树；输出 = 测试断言。
- **单元测试验证要点**：
  - 四门扫描（后端二次扫描 + 前端四正则）在扩面后的全集上全绿。
  - 注入用例如期变红（自验证通过）。
  - 清单漂移用例（指向不存在组件的条目）如期变红。

---

### M4 问答策略放开（后端 `qa/service.py`）

- **模块名称**：`backend/app/modules/qa/service.py`（重构路由层）+ `contracts/qa.py`
- **模块职责**：实现 §5.3 QAMode 语义表的三档路由：有证据 → generated/extractive；检索为空/低分 → general（标注）或 not_mentioned（点名对象）；模型不可用 → unavailable。闲聊/问候 → general。
- **需要遵守的接口契约**：§5.3 `QAAnswer/QAMode`；§5.1 `/qa`、`/qa/stream`；纪律 2（不伪造引用）、用户要求"直接放开不要限制"。
- **业务逻辑要求**：
  1. 路由顺序：规则前置（问候/闲聊 → general）→ 检索（有达标证据 → generated/extractive）→ 检索空：能抽取问题对象 X（名词短语）→ not_mentioned（note="论文中没有提到 X"）；抽不出对象或用户 mode_hint=general → general（note="通用回答（未使用论文原文）"）。
  2. general/not_mentioned 一律 `grounded=false`、`citations=[]`，不走 answer_gate 的引用校验（无引用可校）。
  3. generated/extractive 保持 answer_gate 既有发布门；被门拦截 → `abstained` + 原因（不降级为空白）。
  4. LLM 调用异常 → 抛 `DomainError(LLM_UNAVAILABLE, retryable=true)`，由流层收敛为 error 事件、非流式收敛为 502。
  5. 与 M5 的不变量共用：任何分支返回前经过非空断言。
- **输入输出说明**：输入 question + mode_hint + 检索结果；输出 QAAnswer（落库）。
- **单元测试验证要点**：
  - 三类默认问题各得非空答案："你好，介绍一下你自己" → general；"这篇论文的核心方法是什么"（有证据）→ generated/extractive 且 citations 非空；"这篇论文提到量子计算了吗"（无证据、对象可抽取）→ not_mentioned 且 note 含"量子计算"。
  - general 回答：note 含"未使用论文原文"、citations 为空、grounded=false。
  - mock 检索空 + 对象不可抽取 → general 而非空白。
  - mock LLM 抛异常 → DomainError(LLM_UNAVAILABLE)；流式路径收到 error 事件且 retryable=true。
  - 闲聊问题不得触发检索（mock retrieval 调用计数 = 0）。

---

### M5 绝不空答不变量（后端）

- **模块名称**：`backend/app/modules/qa/service.py`（落库前断言）+ `qa/stream.py`（兜底）
- **模块职责**：把"任何返回路径 answer 非空"做成**代码级不变量**，而非靠各分支自觉。
- **需要遵守的接口契约**：§5.3 QAAnswer 不变量；§5.4 错误码。
- **业务逻辑要求**：
  1. 落库前统一过 `assert_non_empty(answer)`：`text.strip()` 与 `statements` 皆空 → 替换为 `not_mentioned` 兜底模板（能抽对象）或 `general` 兜底文案，并记告警日志（不变量被触发 = 上游有 bug）。
  2. 流式路径：终结事件发出前对最终答案做同一断言；兜底模板同样经 `final` 下发（不是 error——用户要的是答案）。
  3. 兜底文案不得含"没有生成内容"字样（与前端文案纪律一致）。
- **输入输出说明**：输入 = 各分支产出的 QAAnswer 候选；输出 = 保证非空的 QAAnswer。
- **单元测试验证要点**：
  - 注入三种故障：mock 生成返回空串 / mock answer_gate 全拒 / mock 检索为空且生成空 → 落库 answer 均非空，mode ∈ {not_mentioned, general, abstained}。
  - 不变量触发时告警日志出现（caplog 断言）。
  - 非流式与流式两条路径各注入一次，行为一致。

---

### M6 断流恢复状态机（前端 `useQAStream` + `QAView`）

- **模块名称**：`frontend/hooks/useQAStream.ts`（重构）+ `components/views/QAView.tsx`（修）
- **模块职责**：实现 §5.5 七态状态机与三级兜底链：answer_id 取回 → 非流式 `POST /qa` → 可重试。
- **需要遵守的接口契约**：§5.1 恢复端点与 `/qa`；§5.5 状态机与文案表；§5.4 `QA_RECOVERY_FAILED`。
- **业务逻辑要求**：
  1. 流正常结束（final/error）→ completed/unavailable，行为不变。
  2. 连接断开、流结束无 final、45s 无帧、120s 超时 —— 四种触发一律进 recovering：已持 answer_id → `GET /qa/answers/{id}`（streaming 则 1s/2s/4s 退避重拉 ≤3 次）；取回完整答案 → completed（徽标"已恢复结果"）。
  3. 取回失败或未持 answer_id → 非流式兜底 `POST /qa`（同问）→ 成功则 completed（徽标"已切换为非流式回答"）。
  4. 全部失败 → failed：`QA_RECOVERY_FAILED`，文案"连接异常，请重试" + 重试按钮（重发新流式请求）。
  5. 文案红线：全状态机任何分支不得输出"没有生成内容"；现 `QAView.tsx:203-204` 文案删除。
- **输入输出说明**：输入 question/paper_id；输出状态 + 增量事件 + 最终 QAAnswer。
- **单元测试验证要点**（mock EventSource/fetch 三种故障注入）：
  - 流中途切断（已发 meta）： recovering → 取回成功 → completed，回答文本非空，DOM 含"已恢复结果"，**不含**"没有生成内容"。
  - final 丢失（流正常 close 但无 final）：同上走取回；取回返回 streaming ×3 → 转非流式兜底成功 → completed 且回答非空。
  - 模型超时（120s deadline 注入短时钟）： recovering → 取回 404/失败 → 非流式兜底 502 → failed，DOM 含"连接异常，请重试"与重试按钮，不含"没有生成内容"。
  - 重试按钮点击 → 状态回 connecting 并发出新流式请求。
  - 兜底链全程对同一 question 最多发起：1 流式 + 3 取回 + 1 非流式（计数断言，防风暴）。

---

### M7 流式审计（后端 `qa/audit.py` + 查询端点）

- **模块名称**：`backend/app/modules/qa/audit.py`（新增）+ `models`（新表）+ `api/canonical.py`（新增端点）
- **模块职责**：每条流式回答落一条 `StreamAudit`；提供 `GET /papers/{id}/qa/stream-audit` 查询。
- **需要遵守的接口契约**：§5.3 `StreamAudit`；§5.1 查询端点；Alembic expand-first。
- **业务逻辑要求**：
  1. 新表 `qa_stream_audits`：`id, paper_id, answer_id(index), mode, events JSONB, terminal, error_code, exception_type, elapsed_ms, created_at`；全部可空字段从宽，迁移只增不改。
  2. 写入挂钩在 `stream.py` 的终结点（final/error/异常收敛处/连接断开检测处）**各只写一次**；`events` 只存事件类型名序列（不存正文，控制体积）。
  3. 客户端断开且无终结事件 → `terminal='none'` 落一条（这是"前端被中断"的对账数据源）。
  4. 审计写入失败只记日志，**不得**阻断或改变流行为（尽力而为）。
  5. 查询端点按 created_at 倒序、limit ≤ 200。
- **输入输出说明**：输入 = 流生命周期事件；输出 = 审计行 + 查询响应。
- **单元测试验证要点**：
  - 成功路径：事件序列以 final 结尾 → 审计 `terminal='final'`、events 末位 'final'、elapsed_ms > 0。
  - 异常路径（mock LLM 抛错）→ `terminal='error'`、error_code 正确、exception_type 记录。
  - 超时路径（注入短 deadline）→ `terminal='error'`、error_code='STREAM_TIMEOUT'。
  - 模拟客户端断开 → `terminal='none'`。
  - 四种路径各只写一行（计数断言）；审计写库抛错时流仍正常终结。
  - 端点查询：按 paper 过滤、倒序、limit 生效。

---

### M8 指标解析统一（前端 `lib/evalMetrics.ts` + `EvalView`）

- **模块名称**：`frontend/lib/evalMetrics.ts`（新增）+ `components/views/EvalView.tsx`（重构指标段）+ `components/evaluation/MetricCard.tsx`（新增）
- **模块职责**：唯一指标解析函数，吃四种输入形态，归一出 `MetricView[]`；EvalView 删除本地 `toNumber()`（现 L48-50）与优先级拼装（现 L65-68），改调该函数。
- **需要遵守的接口契约**：§5.3 `MetricView`；§5.4 `METRIC_PARSE_FAILED`；纪律 1（not_evaluated 不填 0）。
- **业务逻辑要求**：
  1. 解析规则：`number` → measured 直接取值；`MetricValue` 对象 → 读 `{status,value,reason}`；`list[MetricEntry]` → 逐项取 `entry.value` 再按前两条递归；`dict` → 逐键递归。`null` → not_evaluated（reason 从 not_evaluated_reasons 查）。
  2. 归一优先级：canonical（exhibits）entry 优先；legacy dict 仅补 canonical 缺失的键（修复"对象占位挡住数字"的现 bug）。
  3. 不可识别形态（如 `{foo:1}` 无 status/value）→ `status='unparsable', source='unparsable', value=null`，console 告警；UI 渲染"数据异常（解析失败）"，**不得**渲染"未评测"。
  4. `parseOverall`：`overall_score`（人工）与 `ai_overall_score`（AI）分开返回，互不回退（人工无值时不得用 AI 值顶替）。
- **输入输出说明**：输入 = `/exhibits` 与 `/evaluation` 两个响应的原始 JSON；输出 = `MetricView[]` + 两个 overall。
- **单元测试验证要点**：
  - 同一值 0.3571 以四种形态输入 → 输出 value 全等 0.3571、status=measured。
  - **现 bug 回归**：canonical 给 `MetricValue{status:'measured', value:0.3571}`、legacy 同键给数字 → 取 canonical 值；canonical 给对象但 value=null（not_evaluated+reason）→ 显示未评测+reason，**不被 legacy 数字覆盖**（语义由后端决定，前端不擅自拯救）。
  - 无法识别输入（`{foo:1}`）→ unparsable，不静默。
  - paper 7 录制响应回放：显示值与已知四值（0.3571 / 1.0 / 1.0 / 0.6667）逐一相等。
  - `parseOverall`：仅 ai_overall_score 有值时 human=null（不冒充）。

---

### M9 评测口径展示（前端 EvalView/MetricCard）

- **模块名称**：`components/views/EvalView.tsx` + `components/evaluation/MetricCard.tsx`（接 M8）
- **模块职责**：人工口径与 AI 口径分区显示；not_evaluated 显示原因码 + 中文说明；`anchor_region_hit_rate` 类"设计上不可测"指标给出明确解释。
- **需要遵守的接口契约**：§5.3 MetricView；纪律 1/3；§1.4-4/5 的口径与可测性要求。
- **业务逻辑要求**：
  1. 顶部两卡：`overall_score`（人工真值，无人工确认时显示"未确认"而非数值）与 `ai_overall_score`（AI 口径，带"AI 评分（非人工真值）"徽标）——分开渲染，互不冒充。
  2. not_evaluated 指标卡片：显示 reason 码 + 中文说明映射表（如 `source_pdf_has_no_coordinate_rects` → "原文 PDF 未提供坐标矩形，该指标设计上不可测"）；reason 缺项时显示"原因未记录"并记 console 告警（不静默）。
  3. `anchor_region_hit_rate` 在 reason=`source_pdf_has_no_coordinate_rects` 时徽标为"不适用"（区别于"未评测"），说明文案写明"拒绝编造 IoU"。
  4. proxy 指标带 proxy 徽标（REFACTOR_SPEC L613 纪律，proxy 不冒充 measured）。
- **输入输出说明**：输入 = M8 输出的 MetricView[] + 两个 overall；输出 = 评测面板 UI。
- **单元测试验证要点**：
  - 仅 AI 分有值：AI 卡显示数值+"AI 评分"徽标；人工卡显示"未确认"，两处数值互不出现。
  - `anchor_region_hit_rate`（not_evaluated + 坐标原因码）→ 显示"不适用"与解释文案，**不混进**"未评测"分组。
  - not_evaluated 缺 reason → 显示"原因未记录" + console 告警断言。
  - proxy 指标渲染带 proxy 徽标；measured 不带。

---

### M10 投影层收敛（后端 `app/projection/`）

- **模块名称**：`backend/app/projection/`（新增）+ `schemas/adapters.py`（收敛）+ `modules/{claims,graph,scene,evaluation,qa}/legacy.py`（删副本）
- **模块职责**：canonical→legacy 唯一投影实现；消灭 D-48/D-60 事故的"两份投影只修一处"结构。
- **需要遵守的接口契约**：§4.7；`projection/CONTRACT.md`；legacy 端点响应字段一个不少（兼容硬约束）。
- **业务逻辑要求**：
  1. `schemas/adapters.py` 的 `to_legacy_*` 函数原样迁入 `app/projection/` 按域拆文件；原文件改 re-export + DeprecationWarning。
  2. 五处 `modules/*/legacy.py` 删除手写投影，仅保留"canonical 优先 + 旧表兜底"读取编排，投影一律 `from app.projection import ...`。
  3. 纯函数纪律：不查 DB、不抛 DomainError；非法输入返回 None + 日志。
  4. `CONTRACT.md` 列每个投影的输出字段清单（字段名 + 来源），契约测试以其为比对基准。
- **输入输出说明**：输入 canonical ORM 记录/DTO；输出 legacy 形态 dict/Pydantic。
- **单元测试验证要点**：
  - **双读一致性（核心）**：同一 canonical 记录经 legacy 端点与 canonical 端点兼容字段两条路径读取，响应逐字段 deep equal；五域（claims/graph/scene/evaluation/qa）各至少一例。
  - **静态门禁**：仓库 grep 断言 `def to_legacy_` 只出现在 `app/projection/`（CI 脚本，防副本再生）。
  - CONTRACT.md 漂移检查：解析投影输出模型字段集与清单比对，不一致即红。
  - 兼容回归：五域 legacy 端点快照测试（无则补最小快照）全绿。

---

### M11 验收套件入库（`scripts/acceptance/`）

- **模块名称**：`scripts/acceptance/`（新增入库）+ 根 `package.json`/Makefile 便捷命令
- **模块职责**：把 `.scratch/` 的 5 个端到端脚本（`verify_route_a.py / verify_graph.py / verify_e2e_extra.py / verify_metrics_live.py / verify_qa_stability.py`）迁移入库、统一机读输出、`run_all.py` 一条命令跑全。
- **需要遵守的接口契约**：§4.8 契约（退出码 + results.json）；§2.1-5 验收判据。
- **业务逻辑要求**：
  1. 迁移时逐脚本清理：去掉 `.scratch` 本地路径硬编码，base-url/paper-id 走参数或环境变量（默认 `http://localhost:8002`）。
  2. 每脚本输出统一 JSON 行：`{ script, status: pass|fail|error, checks: [...], elapsed_ms }`；`run_all.py` 串行执行、汇总 `results.json`、任一 fail/error → 退出码非 0。
  3. **前置健康检查**：后端 `/health`（或等价端点）不可达 → 立即以非零退出 + 明确报错"backend unreachable at {url}"，**不得**把后续检查标记为跳过或成功。
  4. `README.md` 写明：启动前提（docker-compose 四容器）、跑法、参数、退出码约定。
  5. `.scratch/` 维持 gitignore；被迁移的 5 个原文件删除，其余一次性诊断脚本不动。
- **输入输出说明**：输入 = 运行中的服务栈 + 参数；输出 = stdout JSON 行 + `results.json` + 退出码。
- **单元测试验证要点**：
  - 对健康栈跑 `run_all.py` → 退出码 0，results.json 含 5 条 status=pass。
  - 停掉 backend 容器（或指向错误端口）→ 非零退出，stderr 含 "unreachable"，results.json 不产生假 pass。
  - 单脚本可独立运行（`python scripts/acceptance/verify_route_a.py --base-url ...`）。
  - 干净克隆验证：clone 后不依赖 `.scratch/` 任何文件即可跑通。

---

### M12 阶段进度与断点续跑（后端 pipeline + 前端导入页）

- **模块名称**：`backend/app/modules/pipeline/`（progress/resume 扩展）+ `frontend` 导入页（`useJobEvents` 消费）
- **模块职责**：阶段进度事件可见；worker 中断后从断点续跑；AI 类阶段跳过即不重复计费。
- **需要遵守的接口契约**：§4.9 `StageEvent` 与幂等键格式；`POST /papers/{id}/process { from_stage? }`；性能约束（导入 ≤ 6 分钟）。
- **业务逻辑要求**：
  1. 阶段注册表：每阶段声明 `name / idempotent_key(revision) / run(ctx) / estimate_pct`。
  2. 进度事件：start/finish/fail/skip 写 jobs 表并经既有 jobs SSE 推送 `StageEvent{stage,status,progress_pct,message}`；前端导入页渲染阶段时间线。
  3. 幂等键：`sha256(revision_id + stage + 输入指纹)`；重跑时键命中且产物存在 → 跳过（事件 status='skipped'）。
  4. `POST /process`：不传 from_stage → 从第一个未完成阶段起（默认安全）；传 → 从指定阶段起。
  5. AI 类阶段（claims 起草、qa_bank 作答、evaluate 裁判）跳过路径不得触碰 ai 客户端。
- **输入输出说明**：输入 paper_id + 可选起点；输出 JobHandle + 阶段事件流。
- **单元测试验证要点**：
  - 模拟 worker 在 index 阶段后崩溃：重跑时 parse/textnorm/normalize/index 四阶段事件为 skipped，**mock ai 客户端调用计数 = 0**，后续阶段正常执行。
  - 重复执行同一已完成阶段：LLM 调用计数不增加。
  - `from_stage='evaluate'` → 仅 evaluate/publish 执行，前置阶段全 skipped。
  - 进度事件序列：start/finish（或 skip）成对，progress_pct 单调不减。
  - 前端：导入页对 skipped 阶段渲染"已跳过"，对 running 阶段渲染百分比。

---

## 附：任务依赖图

```
M1（渲染扩面+清单）──→ M3（门禁扩面，消费清单）
M2（四分类）        ──→ M3（证据路径门禁）
M4（策略放开） ──→ M5（空答不变量，挂在 M4 的返回路径上）
M5 ──→ M6（前端恢复以后端非空答为前提）──→ M7（审计对账前端恢复行为）
M8（解析统一） ──→ M9（口径展示）
M10（投影收敛）：独立，随时可做，建议 W1-W2 之间插入（改动面大但低风险）
M11（验收入库）：独立，但建议 W3 前完成，作为 W3/W4 的交付门禁
M12（进度续跑）：优化项，最后做
```
