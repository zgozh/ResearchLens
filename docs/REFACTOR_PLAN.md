# ResearchLens 重构方案设计

> 版本：v1.0（2026-09-12）
> 性质：架构方案文档。不含完整业务实现代码；仅含接口签名与伪代码。
> 使用方式：第六章每条任务（M1–M12）可独立复制给编码模型逐个实现。每条任务末尾的"前置依赖"标明了实现顺序约束。
> 关联文档：`docs/REFACTOR_SPEC.md`（既有规格）、`docs/DECISIONS.md`（D-01…D-70 决策记录，本方案遵守其全部数据纪律）。

---

## 一、原有项目现状与问题诊断

### 1.1 项目定位与技术栈（事实）

- **产品**：ResearchLens —— 把一篇真实论文变成"可交互科研成果"：解析 → 结构化导读 → 断言/证据链 → 图表 → 研究图谱 → 方法动画 → 讲解分镜 → 证据问答 → 自动评测。
- **后端**：Python 3.12 / FastAPI / SQLAlchemy 2 + Alembic / PostgreSQL；Docker Compose 四容器（`backend:8000→8002`、`worker`、`frontend:3000→4002`、`db:5432`）。
- **前端**：Next.js App Router + React + Tailwind + framer-motion + `@xyflow/react`（图谱）+ KaTeX（公式）；前后端**不同源**，后端地址由 `absoluteApiUrl()` 拼接。
- **模型侧**：阿里云 DashScope（`qwen-plus` 对话 + `text-embedding-v3` 向量）；PDF 解析走 MinerU（云），产物含 `table_html`、LaTeX、`<sup>` 类行内标签。
- **数据双轨**：`legacy` 表（早期 demo/兼容）+ `canonical` 表（`claim_records/statements/validations/evidence_records/bindings/media/section_records/method_steps/map_items/pages/blocks/anchors/assets/chunks/chunk_vectors/answers/golden_sets`）；对外 API 同时提供 canonical 与 legacy 投影。
- **纪律性资产**：`docs/REFACTOR_SPEC.md`（规格，L613 关于"measured/proxy/overall_score"的纪律）、`docs/DECISIONS.md`（D-01…D-70 决策记录，含每处修复的实测证据）。

代码核实补充（2026-09-12 实地核对）：

- 媒体策略函数实际位于 `backend/app/modules/visual/policy.py`（任务书中的 `resolveMediaPolicy` 即此模块的策略判定逻辑）。
- QA 流式实现位于 `backend/app/modules/qa/stream.py`，答案闸门位于 `modules/qa/answer_gate.py`；已有 `deadline=120s` 与断流兜底文案。
- 前端已存在 `components/RichText.tsx`、`lib/mathHtml.ts`、`lib/sanitize.ts`、`lib/sourcePolicy.ts`——即"富文本内核"已有雏形，但**四处消费路径并未统一走它**（详见 P1）。
- 投影副本实证：`schemas/adapters.py` 提供 `to_legacy_claim/to_legacy_claim_summary` 等，同时 `modules/claims/legacy.py`、`graph/legacy.py`、`scene/legacy.py`、`evaluation/legacy.py`、`qa/legacy.py`、`evidence/legacy_resolver.py` 各自维护一份 canonical→legacy 的桥接/兜底逻辑（D-48/D-60 事故结构至今仍在）。

### 1.2 现有模块划分（事实）

- `backend/app/modules/`：`parse`、`papers`、`pipeline`、`claims`、`evidence`（gate/locator/semantic/repository/service/legacy_resolver）、`retrieval`、`graph`、`scene`、`qa`（service/stream/answer_gate/repository/legacy）、`evaluation`、`visual`（policy/crops/tables/pages_util/repository/service）、`ai`。
- `backend/app/api/`：`canonical.py`（canonical + 运维端点）、`routes.py`（legacy 兼容端点）。
- `backend/app/contracts/`：DTO/Pydantic 契约（`common/ai/documents/artifacts/evidence/graph/scene/qa/evaluation/jobs/retrieval`）。
- `backend/app/schemas/`：`adapters.py`（canonical→legacy 投影函数）、`canonical.py`、`schemas.py`。
- `frontend/components/`：`views/`（`MapView/PaperView/MethodView/GraphView/QAView/EvalView/PresenterView/ClaimView`）、`source/`（`SourceMedia/ExtractedTable/ExtractedFormula/SourceBadge`）、`reader/`（`PdfReader/AnchorOverlay/PageSelector`）、`evidence/`、`TableRender.tsx`、`MathText.tsx`、`LongText.tsx`、`RichText.tsx`、`FigureImage.tsx`、`MediaModal.tsx`；`hooks/`（`useQAStream/usePaperWorkspace/useJobEvents/useEvidenceNavigation`）；`lib/`（`api/sse/sanitize/mathHtml/sourcePolicy/contracts/types`）。

### 1.3 用户实测问题（本轮必须正面解决）

**P1【必须修复】富文本渲染三处路径不统一，导致"看论文像看乱码"**
- 现象：结构化导读/全文原文里出现 `Ashish Vaswani<sup>∗</sup> Google Brain avaswani@google.com`、`For the base model, we use a rate of $P _ { d r o p } = 0 . 1$`；原件媒体/公式介绍里出现 `$$ \operatorname{Attention}(Q,K,V)=…\tag{1} $$` 原文。
- 事实：正文走 `LongText → MathText`（有 KaTeX，但**不做行内标签白名单**，`<sup>` 被转义成字面量）；表格走 `TableRender/ExtractedTable` 的 `dangerouslySetInnerHTML`（**只做了 sanitize，未渲染 LaTeX**）；媒体/公式走 `SourceMedia/ExtractedFormula`（把**带 `$$` 定界符与 `\tag` 的原始串**直接交给 KaTeX）。前端虽有 `RichText.tsx` 雏形，但三处消费方没有统一接入。
- 影响：用户无法阅读；且**脏引文进入证据门判定**（见 P2）。

**P2【必须修复】证据链里"引用到这些证据却判未支持"**
- 事实：证据门（Evidence Gate，`modules/evidence/gate.py + semantic.py`）对每条陈述调用 LLM 做 supports/contradicts/insufficient 判定，送进去的 `evidence_text` 取自原文切片。当切片本身含 `$P _ { d r o p } = 0 . 1$`、`<sup>∗</sup>`、跨行 `$$…$$` 时，判定结果大量落到 `insufficient`（前端显示"未支持/证据不足"）。
- 需要：**在入库/判定前做文本规范化**（normalize-on-ingest），并让"未支持"给出**可解释原因**（判定理由 + 命中的引文原样 + 规范化前后对照）。

**P3【必须修复】原件媒体大量"不可用 / 未找到任何可展示原件资产"**
- 事实：`modules/visual/policy.py` 在"有源但无裁剪、无整页锚点"时判 `unavailable`；表格/公式媒体**本来就没有原图资产**。上一轮已加"有 `extracted.table_html/latex` 就给 extracted"的兜底，但用户仍在界面看到不可用标签 → 需核对**所有**媒体消费点（媒体列表、图谱节点、讲解配图、证据抽屉）是否都走同一策略函数。
- 代码核实：策略逻辑集中在 `visual/policy.py`，但前端 `lib/sourcePolicy.ts` 另有一份展示层策略判断，两处存在分叉风险，本次必须收敛为"后端一次判定、前端纯渲染"。

**P4【必须修复】证据问答在浏览器里"转圈 → 本次回答被中断或超时，没有生成内容"**
- 事实：同一问题**非流式** `POST /api/papers/{id}/qa` 在 5–20s 内可正常返回（含通用回答模式）；浏览器走 `POST /qa/stream`（SSE，实现于 `modules/qa/stream.py`，前端 `hooks/useQAStream.ts + lib/sse.ts`）。已在后端补 `deadline=120s`、断流兜底文案、`mode` 透传，但用户仍复现"被中断"。
- 需要：把**流式契约**当成一等公民排查——事件序列（`meta/status/citation/sentence/final/error`）必须**保证终结事件**（成功给 `final`，失败给 `error`），前端断流必须能区分"服务端未发终结事件 / 网络中断 / 服务重启"，并提供**可重试 + 可恢复**（例如按 `answer_id` 拉取已落库结果）。
- 另外：用户要求"**不受限问答**"——日常聊天要能答（当前 `mode=general` 已实现），论文问题没有证据时**要么给通用回答并明确标注**，要么明确回答"论文中没有提到 X"，**不允许出现空白或长时间无响应**。

**P5【必须修复】研究图谱布局：节点互相堆叠、连线纠缠、边标签看不清**
- 事实：`GraphView` 用"kind → 列（`col*250`）、同 kind 依次 `row*90`"的**手写网格**；实测一篇论文有 **39 节点/33 边**（导入论文更多），同 kind 节点纵向堆叠，边标签被节点遮住。
- 需要：真正的**分层/泳道布局 + 节点不重叠 + 边标签可见 + 大量节点可交互**（折叠、筛选、缩放、聚焦）。约束：**不引入重型图布局第三方库**（如 ELK/cytoscape），可用 `@xyflow/react` 原生能力 + 自研轻量分层算法。

**P6【必须修复】图片方向错误且无法旋转**
- 事实：部分 MinerU/PDF 图片方向反了；阅读器与媒体面板只能看，不能转。
- 需要：媒体查看器支持**旋转（90° 步进）/缩放/复位**，并把旋转状态限制在**视图层**（不改资产字节），关闭后复位。

### 1.4 其他已知缺陷（区分等级）

**必须修复**

1. **`anchor_region_hit_rate` 永远 not_evaluated**：原文无坐标矩形时不得编造 IoU；需在 UI/接口**显式说明不可测原因**，而不是混进"未评测"。
2. **导入后自动评测的时延/token 四项仍 not_evaluated**：题库作答的 `usage` 在重载答案时未恢复（`_row_to_answer` 丢失 usage）。
3. **同一条投影逻辑存在多份副本**：`schemas/adapters.py` 与 `modules/*/legacy.py` 各写一份（已核实：claims/graph/scene/evaluation/qa 五处 legacy 桥接并存），已发生"只修一处"事故（D-48/D-60），需收敛为**单一投影入口 + 契约测试**。
4. **导入链路的模型快照登记依赖调用方记得传 ctx**（D-67 根因），属于**易错接口**，应改为默认安全。

**建议优化**

5. 导入耗时已到 ~4 分钟（AI 起草参考断言 + 8 题作答），需要**阶段进度可见 + 可中断/可续跑**。
6. `qwen-plus` 结构化输出会被 `max_tokens` 截断（已加"压小要求 + 截断放大预算"），可进一步做**输出预算自适应**。
7. 评测"未评测"项分散在 15 个固定指标里，需要**统一的可测性说明模型**（每个 not_evaluated 带 `reason`）。
8. 前端渲染缺少**文本卫生回归门禁**（未配对 `$`、`<tag>`、控制符、`$$` 定界符残留）。

---

## 二、本次重构总体目标与硬性约束

### 2.1 业务目标

1. **可读**：任何来源（arXiv 网址 / 上传 PDF）导入后，导读、全文、表格、公式、媒体介绍**都不出现未渲染的 LaTeX、HTML 标签或乱码**。
   - 验收：对回归语料（≥3 篇真实论文，含 Attention Is All You Need）执行文本卫生扫描，"未配对 `$` / 裸 `<tag>` 字面量 / 控制符 / `$$` 定界符残留"命中数 = 0 或 100% 有 `TextIssue` 记录。
2. **可信**：证据链的每条"支持/未支持"都要有**可核对的原文与判定理由**；脏文本不得影响判定结果。
   - 验收：同批回归语料下，`insufficient` 判定占比相对重构前可量化下降；每条 insufficient 必带 `reason + quote_before + quote_after`。
3. **可用**：问答在浏览器里**必须给出终结结果**（答案 / 通用回答 / 明确"论文未提及" / 明确错误），不允许无限转圈或空白。
   - 验收：首字节 < 2s；任何路径（成功/失败/超时/服务重启）120s 内必有终结事件或前端恢复结果；三类默认问题（聊天/论文内可答/论文内不可答）均有非空输出。
4. **可看**：图谱在 40+ 节点规模下**不堆叠、连线可辨、标签可读**；图片可旋转查看。
   - 验收：100 节点内任意两节点包围盒不重叠；边标签与节点包围盒重叠率 = 0；交互（折叠/筛选/聚焦/缩放）帧率可用。
5. **可评**：导入即完成 AI 评测，指标要么有值、要么给出**不可测原因**。
   - 验收：导入完成后 `ai_overall_score` 有值，或全部未出值指标均带结构化 `reason`。

### 2.2 硬性约束

- **技术栈不可变更**：FastAPI + SQLAlchemy/Alembic + PostgreSQL + Next.js App Router + Tailwind + `@xyflow/react` + KaTeX；模型侧 DashScope（`qwen-plus` + `text-embedding-v3`）。
- **兼容原有对外接口**：`/api/papers*`、`/claims`、`/statements`、`/graph`、`/presentation`、`/evaluation`、`/qa`、`/qa/stream` 的既有字段不得删除；新增字段必须可选默认值。
- **不引入重型第三方库**：禁止引入图布局引擎、富文本编辑器框架、ORM 替换、状态管理大件；KaTeX 与 DOMPurify 级别的轻量库可用。
- **部署环境约束**：`docker-compose`（非 `docker compose`）四容器；schema 变更必须走 Alembic 迁移（可空/加宽类 expand-first）。
- **性能约束**：问答首字节 < 2s、终结事件 < 120s（超时必须给终结事件）；图谱 100 节点内交互不卡；单篇导入 ≤ 6 分钟。
- **数据纪律不可破坏**（写在 `docs/DECISIONS.md`，必须在方案里遵守）：
  1. 未评估的指标**不许填 0**，必须 `not_evaluated` + 原因；
  2. 机器构造的金标集**不当作人工真值**，AI 口径评分必须标明 basis；
  3. 证据必须可溯源（quote 逐字来自原文块），引用不上的句子不许发布；
  4. 展示层不得把"位置推断"当成"题注匹配"。

---

## 三、重构后整体架构设计

### 3.1 目录树（目标形态）

```
backend/app/
  core/                # 配置、DB、错误(DomainError)、时钟、安全
  contracts/           # DTO/契约（禁止业务逻辑）
    common.py          #   + NormalizedText/TextIssue/DomainError/MetricValue【新增】
    documents.py       #   + 富文本 AST 节点类型【新增】
    evidence.py        #   + EvidenceVerdict 扩展字段【扩展，全可选】
    evaluation.py      #   + 指标可测性模型【扩展】
    qa.py              #   + QAAnswer.mode 扩展枚举 + SSE 事件 DTO【扩展】
    visual.py          #   + MediaViewPolicy【新增】（若现有则在原文件扩展）
    ...                #   其余既有契约文件不动
  models/              # ORM（新增字段一律可空/带默认值，Alembic expand-first）
  modules/
    parse/             # PDF→块/页/媒体（MinerU + 兜底）【保持，产物交给 textnorm】
    textnorm/          # 【新增】文本规范化：MinerU artifacts → 干净正文 + 富文本 AST
      __init__.py      #   对外只暴露 normalize()/scan() 两个函数
      normalizer.py    #   主流程：分层规范化管道
      latex.py         #   $…$/$$…$$/\(…\) 识别、未配对检测、\tag 剥离、块级公式提取
      inline.py        #   行内标签白名单（sup/sub/i/b/br）→ AST 节点
      heuristics.py    #   作者/机构/邮箱行、全角半角、控制符、空格断裂 token 修复
      issues.py        #   TextIssue 产出与严重度分级
      repository.py    #   规范化结果/问题的落库（挂在 blocks/section_records 上）
    papers/            # 论文/修订/来源/资产【保持】
    pipeline/          # 阶段编排【重构：进度事件 + 断点续跑 + ctx 默认安全】
      stages.py        #   阶段注册表（新增 textnorm 阶段）
      progress.py      #   【新增】阶段进度事件（写 jobs + SSE 复用既有 jobs 通道）
      resume.py        #   【新增】断点续跑：阶段幂等键 + 已完成阶段跳过
    claims/            # 断言与陈述【保持；删除 legacy.py 内投影副本，改调 projection】
    evidence/          # 证据门 + 定位 + 绑定【重构：判定输入走 textnorm，判定输出可解释】
      gate.py          #   判定编排：输入规范化切片，输出 EvidenceVerdict
      semantic.py      #   LLM 判定：prompt 注入规范化文本，回收 reason
      locator.py       #   定位：保持；quote 逐字校验在规范化后的 plain 上做
    retrieval/         # 分块/索引/检索/融合【保持；分块输入改用规范化 plain】
    graph/             # 图谱数据【保持；删除 legacy.py 投影副本】
    scene/             # 讲解分镜【保持；配图走统一媒体策略】
    qa/                # 证据问答【重构 stream；保持 service/answer_gate】
      stream.py        #   SSE 契约：终结事件保证 + answer_id 早发 + 心跳
      service.py       #   mode 路由：generated/extractive/general/abstained/not_mentioned
      answer_gate.py   #   发布门：引用不上的句子不发布（纪律 3）【保持】
    evaluation/        # 评测【重构：可测性模型 + usage 恢复 + AI/人工口径分离】
    visual/            # 媒体展示策略【重构：policy 唯一判定，输出 MediaViewPolicy】
      policy.py        #   四态策略 original/extracted/page/unavailable + 原因码
    ai/                # 模型调用/预算/能力观测【扩展：输出预算自适应】
  projection/          # 【新增，收敛自 schemas/adapters.py + modules/*/legacy.py】
    __init__.py        #   唯一入口：to_legacy_*(canonical_record) 系列
    claims.py graph.py scene.py evaluation.py qa.py
    CONTRACT.md        #   投影字段清单（契约测试的比对基准）
  api/
    canonical.py       # 【保持路由；内部改调 projection】
    routes.py          # 【保持路由；内部改调 projection】
  schemas/             # 【收敛】只保留请求/响应 schema；adapters.py 删除或转为 re-export
frontend/
  app/                 # App Router 页面【保持】
  components/
    rich/              # 【新增】唯一富文本渲染内核
      RichText.tsx     #   <RichText value={NormalizedText|RichAST|string} />
      nodes.tsx        #   AST 节点 → React 元素（sup/sub/i/b/br/link/math）
      katex.ts         #   KaTeX 调用封装：失败降级为可读文本，绝不残留定界符
      sanitize.ts      #   从 lib/sanitize.ts 迁入并扩展白名单
    views/             # 【保持八个视图；GraphView 重构】
    source/            # SourceMedia/ExtractedTable/ExtractedFormula 全部改走 rich/
    reader/            # PdfReader/AnchorOverlay/PageSelector【保持】
    evidence/          # 证据抽屉：新增"规范化前后对照"与判定理由展示
    media/             # 【新增】媒体查看器
      MediaViewer.tsx  #   旋转(90°步进)/缩放/复位；旋转仅存视图 state
      MediaBadge.tsx   #   统一徽标：原件/再排版/整页/不可用 + 原因 tooltip
    graph/             # 【新增】图谱布局与交互
      layout.ts        #   轻量分层布局（泳道 + 层内分布 + 冲突消解）
      edgeLabel.ts     #   边标签避让
      GraphCanvas.tsx  #   <GraphCanvas layout focus filters />；折叠/筛选/聚焦
    TableRender.tsx MathText.tsx LongText.tsx RichText.tsx
                       # 【收敛】四个文件保留导出签名，内部全部委托 components/rich/
  hooks/
    useQAStream.ts     # 【重构】断流分类 + answer_id 恢复 + 一键重试
    lib/               # （lib 目录保持）
  lib/
    sse.ts             # 【重构】事件解析 + 终结事件检测 + 心跳超时
    sourcePolicy.ts    # 【删除或退化为纯展示映射】策略判定收归后端
```

**目录调整理由说明**：

- `textnorm/` 单列为模块而非塞进 `parse/`：parse 的职责是"把 PDF 变成块"，textnorm 的职责是"把块变成可信文本"，两者的变更原因不同（MinerU 升级 vs 渲染/判定质量问题），分开才能各自独立测试。retrieval 分块、evidence 判定、前端渲染三处都消费它的产物，放在 modules 顶层符合"被多方依赖"的位置。
- `projection/` 提升为顶层包：现状 `schemas/adapters.py` + 五处 `modules/*/legacy.py` 副本是 D-48/D-60 事故的结构根因。收敛为唯一入口后，契约测试只需对一个包做"两处读取逐字段相等"比对。
- 前端 `rich/` 与 `media/`、`graph/` 独立成目录：三者都是"多消费方共享的内核"，与一次性视图组件分开，便于在 M2/M4/M8 任务中独立交付、独立写渲染一致性测试。
- `RichText.tsx/MathText.tsx/LongText.tsx/TableRender.tsx` 保留旧路径只做 re-export：避免一次性改动所有 import，降低 M3 任务的冲突面。

### 3.2 组件数据流

**导入链路**（新增加粗阶段）：

```
POST /papers/from-url | /papers/upload
  → pipeline.ingest（建 paper/revision/source；ctx 由管线内部自动装配模型快照，
    调用方不传 ctx 也默认安全 —— 修复 D-67 易错接口）
  → 阶段序列（每阶段发进度事件，均可中断续跑）：
    acquire → parse（MinerU → pages/blocks/media 粗产物）
    → textnorm【新增】（blocks/section_records 正文规范化：
        产出 plain + rich AST + TextIssue[]，落库；
        后续所有阶段只消费规范化产物）
    → normalize（业务归一：章节、题注、锚点）→ media（策略判定）
    → index（retrieval 分块/向量化，输入=规范化 plain）
    → claims → verify（evidence gate，输入=规范化切片）
    → exhibits → qa_bank（AI 金标集 + 8 题作答，usage 完整落库）
    → evaluate（AI 裁判；指标可测性模型）→ publish
```

**渲染链路**：

```
GET /papers/{id}（detail 中带 normalized 字段，plain + rich AST）
  → 前端四处消费方（LongText 正文 / TableRender 表格 / evidence 证据引文 /
    SourceMedia+ExtractedFormula 媒体介绍）统一渲染入口：
      <RichText value={...} />
  → rich/ 内核：AST → React 节点；行内公式/块级公式 → KaTeX；
    KaTeX 失败 → 降级为去定界符的可读文本（绝不留 $ 或 $$）；
    行内标签仅放行 sup/sub/i/b/br/a(安全链接)，其余一律转义。
  → 向后兼容：detail 暂缺 normalized 字段时，前端对 string 输入
    走同一内核的"宽松模式"（先跑一份与后端同规则的轻量规范化再渲染），
    保证旧数据也不出乱码。
```

**问答链路**：

```
POST /papers/{id}/qa/stream（SSE）
  → 服务端：建 answer 行（status=streaming）→ 立即发 meta{answer_id, mode}
    → status（阶段提示，可多次）→ citation* → sentence*（流式正文）
    → 终结事件二选一：final{answer_id, mode, grounded, note} | error{code, retryable}
    → 心跳：每 15s 一发（注释帧 ": ping"），deadline 120s 到点必发 error{code:"STREAM_TIMEOUT"}
  → 前端 useQAStream：
    收到终结事件 → 正常收尾；
    连接断开且无终结事件 → 分类：网络中断 / 服务重启 / 服务端未发终结；
    → 若已拿到 answer_id：GET /papers/{id}/qa/answers/{answer_id} 拉取落库结果恢复；
    → 否则显示"可重试"按钮（同问重发）。
```

**证据链路**：

```
claims → evidence.gate.validate
  （输入必须是 textnorm 规范化后的切片 plain + 原文原样 raw，二者一并送入）
  → semantic LLM 判定（prompt 用 plain，要求输出 reason）
  → EvidenceVerdict{ verdict, confidence, reason, quote_before(=raw), quote_after(=plain) }
  → locator 在 plain 上定位锚点；quote 逐字校验对 raw 做（纪律 3：quote 逐字来自原文块）
  → bindings → graph / scene / qa（三处消费同一份 verdict，不再各自重判）
```

### 3.3 新增/移除依赖

**新增**：

| 依赖 | 侧 | 体积 | 理由 |
|---|---|---|---|
| 无强制新增 | — | — | 文本规范化、分层布局、SSE 强化全部零依赖自研（约束：不引重型库） |
| DOMPurify（可选） | 前端 | ~20KB gzip | 仅当现有 `lib/sanitize.ts` 的自研白名单在 M2 测试中被证明有绕过样本时才引入；默认复用现有 sanitize 并扩展标签白名单 |
| katex（既有） | 前端 | 已有 | 不新增 |

**移除/收敛的自研重复代码**：

| 对象 | 处置 |
|---|---|
| `schemas/adapters.py` 的投影函数 | 迁入 `projection/`，原文件删除或仅留 re-export + DeprecationWarning |
| `modules/claims|graph|scene|evaluation|qa/legacy.py` 中的投影副本 | 全部删除投影逻辑，仅保留"canonical 优先 + 旧表兜底"的读取编排，投影一律调 `projection/` |
| `frontend/lib/sourcePolicy.ts` 的策略判定部分 | 删除判定逻辑，退化为"后端 MediaViewPolicy → 展示文案/徽标"的纯映射 |
| `MathText.tsx` / `LongText.tsx` / `TableRender.tsx` / `RichText.tsx` 四份各自为政的渲染 | 收敛为 `components/rich/` 单内核，旧文件仅 re-export |

---

## 四、模块拆分与模块职责定义

> 每个模块按统一五段式：职责 / 依赖谁 / 被谁依赖 / 对外契约 / 不做什么。

### 4.1 `textnorm`【新增，后端】

- **职责**：把 MinerU/PDF 粗产物规范化为"干净正文 plain + 富文本 AST rich"，并产出全部文本问题 `TextIssue[]`。处理：`$…$` / `$$…$$` / `\(…\)` 三种定界符、未配对 `$`、`\tag{}` 剥离（保留编号为公式元数据）、行内标签白名单（`<sup>/<sub>/<i>/<b>/<br>`）、作者/机构/邮箱行识别、控制符与全角/半角混排、MinerU 特有的"token 间多余空格"（如 `$P _ { d r o p } = 0 . 1$`）。
- **依赖谁**：`core`（错误模型）、`contracts`（DTO）。**不依赖** parse/papers 之外任何业务模块，不依赖 ai（纯规则，零 LLM 调用——保证确定性、可单测、零成本）。
- **被谁依赖**：`pipeline`（导入阶段）、`retrieval`（分块输入）、`evidence`（判定输入）、`api/canonical`（detail 输出 normalized 字段）。
- **对外契约**：`normalize(block: RawBlock) -> NormalizedText`、`scan(text: str) -> list[TextIssue]`（供 M11 回归门禁复用）。
- **不做什么**：不做语义改写、不翻译、不纠错别字；不保证 LaTeX 语法可编译（只保证结构识别与定界符配对，编译失败由前端 katex 降级处理）；不碰媒体资产。

### 4.2 `rich`【新增，前端渲染内核】

- **职责**：唯一富文本渲染内核。输入 `NormalizedText`（优先）或裸 string（宽松模式），输出 React 节点。KaTeX 渲染行内/块级公式；白名单行内标签转语义元素；链接安全（`rel="noopener noreferrer"`、协议白名单）；KaTeX 失败降级为去定界符可读文本。
- **依赖谁**：`katex`、既有 sanitize 工具、`contracts` 类型（`lib/contracts.ts` 镜像后端 DTO）。
- **被谁依赖**：`LongText`（正文）、`TableRender`/`ExtractedTable`（表格单元格）、`evidence/`（引文）、`source/SourceMedia`/`ExtractedFormula`（媒体介绍）——四处强制同内核。
- **对外契约**：`<RichText value={NormalizedText | string} density="prose|compact" />`。
- **不做什么**：不做编辑（不是编辑器）、不做 Markdown 全语法（只处理 MinerU 产物子集）、不决定媒体展示策略（那是 media-view）。

### 4.3 `media-view`【新增/重构，前后端协同】

- **职责**：(a) 后端 `visual/policy.py` 收敛为唯一策略判定，输出四态 `MediaViewPolicy{ kind: original|extracted|page|unavailable, reason_code, assets }`；(b) 前端 `media/MediaViewer` 统一查看器：旋转（90° 步进）/缩放/复位，旋转仅存视图 state（不改资产字节），关闭自动复位；(c) `MediaBadge` 统一徽标与不可用原因文案。
- **依赖谁**：后端依赖 `papers`（资产）、`contracts`；前端依赖 `rich`（提取态的 table_html/latex 渲染）。
- **被谁依赖**：媒体列表、图谱节点配图、讲解分镜配图、证据抽屉——**四个消费点全部改为只读 `MediaViewPolicy`，禁止各自重判**。
- **对外契约**：后端 `resolve_media_policy(media_id) -> MediaViewPolicy`；前端 `<MediaViewer media assets policy onNavigate />`。
- **不做什么**：不做图片编辑/裁剪/持久化旋转；不做 OCR；不引入图片处理库（旋转用 CSS transform）。

### 4.4 `graph-layout`【新增，前端】

- **职责**：轻量分层布局与交互。泳道分层（按 kind 分泳道、按拓扑序分层）+ 层内重心法排序减少交叉 + 冲突消解（节点包围盒不重叠）；边标签放置在边中点并做节点避让；折叠（按 kind/按子树）、筛选、聚焦（ ego 网络）、缩放。纯 TS 实现，零依赖（`@xyflow/react` 只负责画）。
- **依赖谁**：`contracts` 的 graph DTO。
- **被谁依赖**：`views/GraphView`。
- **对外契约**：`layoutGraph(input: GraphLayoutInput) -> GraphLayoutOutput`（确定性：同输入同输出，seed 固定）；`<GraphCanvas layout="layered" focus? filters? />`。
- **不做什么**：不做力导向物理模拟（性能与稳定性不可控）；不持久化用户手拖位置到后端（仅存 session）；不引入 ELK/cytoscape/dagre（约束）。

### 4.5 `qa-stream`【重构，后端 `modules/qa/stream.py` + 前端 `useQAStream`】

- **职责**：SSE 事件契约的实现与保证：事件序列 `meta → status* → citation* → sentence* → (final|error)`；**终结事件保证**（任何退出路径——成功、LLM 异常、超时、发布门拦截——都必须发 `final` 或 `error`）；`answer_id` 在 `meta` 中早发；15s 心跳；120s deadline 到点发 `error{code:"STREAM_TIMEOUT"}`；前端断流分类与按 `answer_id` 恢复。
- **依赖谁**：`qa/service`（mode 路由与生成）、`qa/answer_gate`（发布门）、`retrieval`、`ai`、`core`。
- **被谁依赖**：`api/canonical.py` 的 `/qa/stream` 端点、前端 `useQAStream`。
- **对外契约**：见 §5.2 SSE 事件契约。
- **不做什么**：不做非流式端点逻辑（`POST /qa` 保持现状走 `qa/service`）；不做消息持久化之外的会话管理。

### 4.6 `evidence`【重构】

- **职责**：判定输入规范化（送 LLM 的 `evidence_text` 一律为 textnorm 产物 plain，同时保留 raw）、判定理由可解释（prompt 要求输出 reason，结构化回收）、未支持原因结构化（`EvidenceVerdict` 扩展字段）。
- **依赖谁**：`textnorm`、`ai`、`retrieval`、`contracts`。
- **被谁依赖**：`pipeline`（verify 阶段）、`claims`、`graph`、`scene`、`qa`。
- **对外契约**：`validate(statement, evidence_slice) -> EvidenceVerdict{ verdict, confidence, reason, quote_before, quote_after }`。
- **不做什么**：不改 verdict 三值枚举（supports/contradicts/insufficient 对外不变）；不在判定层做文本渲染。

### 4.7 `evaluation`【重构】

- **职责**：指标可测性模型（15 个固定指标每个带 `MetricValue{ status, value?, reason? }`，not_evaluated 必填 reason）；AI 口径与人工口径分离（AI 金标集评分一律标 `basis="ai_generated"`，纪律 2）；修复 `_row_to_answer` 丢失 usage 导致的时延/token 四项不可测；`anchor_region_hit_rate` 在无坐标矩形时给明确不可测原因而非编造 IoU（纪律 1）。
- **依赖谁**：`qa`（作答记录）、`evidence`、`ai`、`contracts`。
- **被谁依赖**：`pipeline`（evaluate 阶段）、`api`（evaluation 端点）、前端 `EvalView`。
- **对外契约**：`evaluate(paper_id, basis) -> EvaluationReport{ metrics: dict[str, MetricValue], basis }`。
- **不做什么**：不把 proxy 指标冒充 measured（REFACTOR_SPEC L613 纪律）；不做人工标注 UI。

### 4.8 `projection`【收敛，后端新增顶层包】

- **职责**：canonical→legacy 的**唯一**投影入口。所有 legacy 兼容端点（`api/routes.py`）与 canonical 端点中的 legacy 投影字段，一律经此包产出。
- **依赖谁**：`contracts`、`models`（只读）。
- **被谁依赖**：`api/routes.py`、`api/canonical.py`、`modules/*/legacy.py`（这些文件只保留读取编排）。
- **对外契约**：`to_legacy_claim(...)` / `to_legacy_graph(...)` / `to_legacy_scene(...)` / `to_legacy_evaluation(...)` / `to_legacy_qa(...)` 系列纯函数；`CONTRACT.md` 列出每个投影的字段清单。
- **不做什么**：不做 DB 查询（纯转换）、不做业务判定；不允许任何模块绕开它手写投影（契约测试强制）。

### 4.9 `pipeline`【重构】

- **职责**：阶段编排 + 进度可观测 + 可中断续跑 + ctx 默认安全。新增 `textnorm` 阶段；每阶段开始/完成/失败发进度事件（复用既有 jobs 通道）；阶段幂等键（paper_revision + stage + 输入指纹）使中断后重跑自动跳过已完成阶段、不重复计费；`ingest` 内部自动装配模型快照 ctx（调用方不传也安全，修复 D-67）。
- **依赖谁**：全部业务模块（编排者）、`ai`（快照）、`core`。
- **被谁依赖**：`api/canonical.py` 的 `/papers/*` 导入与 process 端点、worker。
- **对外契约**：`run(paper_id, from_stage=None) -> JobHandle`；阶段事件 DTO `StageEvent{ stage, status, progress_pct, message }`。
- **不做什么**：不实现任何阶段的具体业务（只编排）；不做跨论文批处理。

### 4.10 前端既有视图组件（收敛而非重写）

- `MapView/PaperView/MethodView/QAView/EvalView/PresenterView/ClaimView`：保持交互与路由不变，仅替换内部渲染/数据消费点（rich 内核、MediaViewPolicy、EvidenceVerdict 新字段展示）。
- `GraphView`：唯一重写的视图（M8），对外 props 不变。

---

## 五、完整接口契约规格

> 以下为签名级契约。`...` 表示既有字段保持不变。所有新增字段均可选且有默认值；既有字段不得删除、不得改语义。

### 5.1 HTTP 接口

```python
# ── 导入 ──────────────────────────────────────────────
POST /api/papers/from-url
  req:  { url: str, title?: str }
  resp: { paper_id: str, job_id: str, ... }                # 既有
  err:  400 INVALID_URL | 422 PDF_UNREACHABLE | 409 DUPLICATE_PAPER
  兼容: 不变。

POST /api/papers/upload
  req:  multipart file
  resp/err: 同上。兼容: 不变。

POST /api/papers/{id}/process
  req:  { from_stage?: str }                               # 【新增可选】断点续跑起点
  resp: { job_id: str, stages: list[StageEvent], ... }
  兼容: 不传 from_stage = 全量跑（现状行为）。

POST /api/papers/{id}/rebuild-derived
  req:  { stages?: list[str] }                             # 【新增可选】只重建指定派生层
  resp/err: 同上。

# ── 读取 ──────────────────────────────────────────────
GET /api/papers/{id}
  resp: PaperDetail{
          ...,
          normalized?: {                                   # 【新增】
            sections: list[{ section_id, plain: str, rich: RichAST }],
          },
          text_issues?: list[TextIssue],                   # 【新增】默认 []
        }

GET /api/papers/{id}/claims | /statements
  resp: 既有 + 每条 statement 可选挂 verdict_summary       # 【新增可选，不破坏既有】

GET /api/papers/{id}/graph
  resp: 既有 nodes/edges 字段不变
        + layout_hint?: { lanes: list[str] }               # 【新增可选】

GET /api/papers/{id}/presentation
  resp: 既有 + 配图媒体一律带 policy: MediaViewPolicy       # 【新增可选】

GET /api/papers/{id}/evaluation
  resp: EvaluationReport{
          basis: "ai_generated" | "human_confirmed",       # 【新增，默认 ai_generated】
          metrics: dict[str, MetricValue],                 # 【重构】原 number|null → MetricValue
          ...,
        }
  兼容: 顶层既有标量字段保留（deprecated 标注），前端新旧两读。

GET /api/papers/{id}/pages | /document
  resp: 既有 + blocks 带 normalized_plain/normalized_rich  # 【新增可选】

GET /api/papers/{id}/media
  resp: list[MediaItem{ ..., policy: MediaViewPolicy }]    # 【新增字段，必有值】

# ── 问答 ──────────────────────────────────────────────
POST /api/papers/{id}/qa
  req:  { question: str, mode_hint?: "auto"|"general" }    # mode_hint 新增可选
  resp: QAAnswer                                           # 见 5.3
  err:  422 QUESTION_EMPTY | 502 LLM_UNAVAILABLE(retryable)

POST /api/papers/{id}/qa/stream
  req:  同 /qa
  resp: text/event-stream                                  # 事件契约见 5.2
  保证: 首字节 < 2s（meta 事件）；任何路径 ≤120s 必有终结事件。

GET  /api/papers/{id}/qa/answers/{answer_id}               # 【新增】断流恢复
  resp: QAAnswer | { status: "streaming" }                 # 未完结时给状态
  err:  404 ANSWER_NOT_FOUND

# ── 金标集 ────────────────────────────────────────────
POST /api/papers/{id}/golden-set?source=builtin|ai
  resp: 既有 + items 带 basis 标记
POST /api/golden-set/confirm
  resp: 既有不变（人工确认 → 评测 basis 可升 human_confirmed）
```

错误响应统一包：

```python
{ "error": { "code": str, "message": str, "retryable": bool,
             "field_errors": dict[str, str] | null } }     # 对应 DomainError
```

### 5.2 SSE 事件契约（`/qa/stream`）

| 事件 | 字段 | 时机与保证 |
|---|---|---|
| `meta` | `{ answer_id, mode, paper_id }` | **连接建立后第一个事件**，< 2s 必发；`answer_id` 此刻已落库（status=streaming） |
| `status` | `{ stage, message }` | 可多次；检索/生成/闸门等阶段提示 |
| `citation` | `{ ref_id, quote, page, anchor? }` | 每条引用一发；quote 逐字来自原文块（纪律 3） |
| `sentence` | `{ text }` | 流式正文片段，顺序拼接即答案 |
| `final` | `{ answer_id, mode, grounded, note?, usage? }` | **成功路径的终结事件，有且仅有一次，此后服务端主动关流** |
| `error` | `{ code, message, retryable, answer_id? }` | **失败路径的终结事件，有且仅有一次**；含 LLM 异常、超时（`STREAM_TIMEOUT`）、发布门拦截（`ANSWER_GATED`） |
| 心跳 | `: ping`（SSE 注释帧） | 每 15s；前端 45s 无帧即判定断流 |

**前端断流判定与恢复**（`useQAStream` 必须实现的状态机）：

1. 收到 `final`/`error` → 正常收尾，不可重试状态。
2. 连接断开且无终结事件：
   - 已持有 `answer_id` → `GET .../qa/answers/{answer_id}`：
     - 返回完整 QAAnswer → 视为成功恢复（UI 标注"连接中断，已恢复结果"）；
     - 返回 `{status:"streaming"}` → 指数退避重拉（至多 3 次/30s），仍 streaming 则显示"可重试"；
     - 404/5xx 连续失败 → 显示"服务可能重启，可重试"。
   - 未持有 `answer_id`（meta 都没收到）→ 判定网络层失败，直接显示"可重试"按钮。
3. 任何状态下 120s 无终结事件 → 前端主动断开并按第 2 条处理（不无限等待）。

### 5.3 DTO 定义

```python
# contracts/common.py【新增】
class RichNode(TypedDict):        # 富文本 AST 节点（判别联合）
    type: Literal["text","sup","sub","i","b","br","link","math_inline","math_block"]
    text: str | None              # text/math 节点的内容（math 为纯 LaTeX，无定界符）
    children: list["RichNode"] | None
    href: str | None              # link 节点，协议白名单 http/https/mailto
    tag_no: str | None            # math_block 的 \tag 编号（元数据，不参与渲染定界符）

class NormalizedText(BaseModel):
    plain: str                    # 干净正文：无标签、无控制符、公式为纯 LaTeX 片段
    rich: list[RichNode]          # 富文本 AST
    issues: list["TextIssue"] = []

class TextIssue(BaseModel):
    code: Literal["UNPAIRED_DOLLAR","BLOCK_DELIMITER_RESIDUE","UNKNOWN_TAG",
                  "CONTROL_CHAR","MIXED_WIDTH","LATEX_SUSPECT"]
    severity: Literal["info","warn"] = "warn"
    excerpt: str                  # 问题片段（≤80 字符）
    offset: int | None = None

# contracts/visual.py【新增/扩展】
class MediaViewPolicy(BaseModel):
    kind: Literal["original","extracted","page","unavailable"]
    reason_code: Literal["OK","NO_SOURCE_ASSET","NO_CROP_NO_ANCHOR",
                         "EXTRACT_ONLY","ASSET_MISSING_ON_DISK"] = "OK"
    reason_text: str = ""         # 面向用户的可读原因（kind=unavailable 时必填）
    assets: dict[str, str] = {}   # role → url（original/crop/page/extracted）

# contracts/evidence.py【扩展，新字段全可选】
class EvidenceVerdict(BaseModel):
    verdict: Literal["supports","contradicts","insufficient"]   # 既有，不变
    confidence: float = 0.0
    reason: str = ""                # 【新增】判定理由（LLM 输出，结构化回收）
    quote_before: str = ""          # 【新增】引文原样（raw，逐字可核对，纪律 3）
    quote_after: str = ""           # 【新增】规范化后文本（送入判定的实际输入）

# contracts/evaluation.py【重构】
class MetricValue(BaseModel):
    status: Literal["measured","proxy","not_evaluated"]
    value: float | None = None      # not_evaluated 时强制 None（纪律 1：不许填 0）
    reason: str | None = None       # status=not_evaluated 时必填，如
                                    # "source_pdf_has_no_coordinate_rects" / "usage_missing_in_answer_rows"
    basis: Literal["ai_generated","human_confirmed"] | None = None

# contracts/qa.py【扩展】
class QAAnswer(BaseModel):
    ...,                              # 既有字段不变
    answer_id: str                    # 【新增】落库主键（断流恢复凭据）
    mode: Literal["generated","extractive","general","abstained","not_mentioned"]
                                      # 既有枚举 + not_mentioned【新增】
    grounded: bool = False            # 是否基于论文证据
    note: str | None = None           # mode=general → "以下为通用回答，非论文内容"；
                                      # mode=not_mentioned → "论文中没有提到 X"

# contracts/graph.py【新增】
class GraphLayoutInput(BaseModel):
    nodes: list[{ id, kind, label, width?, height? }]
    edges: list[{ id, source, target, label? }]
    lanes: list[str]                  # kind → 泳道 的排序
    seed: int = 42                    # 确定性布局

class GraphLayoutOutput(BaseModel):
    positions: dict[str, { x: float, y: float, lane: str, layer: int }]
    edge_labels: dict[str, { x: float, y: float }]   # 已避让节点
    collapsed: list[str] = []
```

### 5.4 错误模型

```python
class DomainError(Exception):
    code: str            # 稳定机器码，全大写蛇形
    message: str         # 面向用户
    retryable: bool = False
    field_errors: dict[str, str] | None = None
    http_status: int = 400
```

新增错误码（挂到既有错误注册表）：

| code | http | retryable | 含义 |
|---|---|---|---|
| `TEXT_NOT_NORMALIZED` | 500 | false | 下游模块收到未规范化文本（防御性，正常路径不应出现） |
| `STREAM_NO_TERMINAL_EVENT` | 500 | true | 流式生成未产生终结事件（服务端自检，理论不可达；出现即报警） |
| `STREAM_TIMEOUT` | 200(事件内) | true | 120s deadline 到点 |
| `ANSWER_GATED` | 200(事件内) | false | 发布门拦截（引用不上，纪律 3） |
| `MEDIA_NO_REPRESENTATION` | 200(字段内) | false | 媒体无任何可展示表示（随 MediaViewPolicy.unavailable 下发，非 HTTP 错误） |
| `ANSWER_NOT_FOUND` | 404 | false | answer_id 不存在 |
| `LLM_UNAVAILABLE` | 502 | true | DashScope 故障 |

### 5.5 前端组件契约

```tsx
// 富文本内核（唯一入口）
<RichText
  value={NormalizedText | RichNode[] | string}   // string → 宽松模式（前端轻量规范化）
  density?: "prose" | "compact"                   // 默认 prose
  onIssue?: (issues: TextIssue[]) => void         // 冒烟门禁埋点
/>

// 媒体查看器（旋转/缩放/复位，旋转仅视图层）
<MediaViewer
  media={MediaItem}
  assets={Record<Role, Url>}
  policy={MediaViewPolicy}                        // 后端一次判定，组件不再重判
  rotate?: boolean                                // 是否允许旋转，默认 true
  onNavigate?: (target: MediaRef) => void
/>
// 内部状态：rotation ∈ {0,90,180,270}（CSS transform，unmount 即复位）；
// zoom ∈ [0.25, 4]；reset() 一键复原。

// 图谱画布
<GraphCanvas
  layout="layered"                                // 本期只实现 layered；radial 预留
  focus?: string                                  // 聚焦节点 id（ego 网络）
  filters?: { kinds?: string[]; collapsed?: string[] }
  onNodeSelect?: (id: string) => void
/>
```

---

## 六、分模块开发任务清单

> 每条任务完整独立，可直接复制给编码模型。统一要求：遵守 §2.2 硬性约束与 §5 契约；新增 DB 字段一律可空 + Alembic expand-first 迁移；全部交付含单元测试。
> 实现顺序建议：M1 →（M2、M5 并行）→ M3 →（M4、M6、M7、M9 并行）→ M8 → M10 → M11 → M12。

---

### M1 textnorm（后端新增）—— 文本规范化与问题检测

- **模块名称**：`backend/app/modules/textnorm/`
- **模块职责**：把 MinerU/PDF 粗产物（blocks、section_records 正文、media 的 extracted.latex/table_html 之外的纯文本字段）规范化为 `NormalizedText{ plain, rich, issues }`，产出 `TextIssue[]`。纯规则实现，**禁止调用 LLM**。
- **需要遵守的接口契约**：§5.3 `NormalizedText / RichNode / TextIssue`；对外仅暴露：
  ```python
  def normalize(text: str, *, kind: Literal["body","caption","header"]) -> NormalizedText
  def scan(text: str) -> list[TextIssue]        # 供 M11 回归门禁复用
  ```
- **业务逻辑要求**：
  1. 公式识别：支持 `$…$`、`$$…$$`、`\(…\)` 定界符；`$$…$$` 跨行视为块级公式；`\tag{N}` 从公式体剥离存入 `tag_no`；定界符一律不进 AST 节点 text。
  2. 未配对 `$`：不成对的 `$` 不生成 math 节点、按字面文本保留，同时产出 `UNPAIRED_DOLLAR` issue。
  3. MinerU 空格修复：公式体内 `P _ { d r o p }` 类 token 间多余空格压缩（`_`/`^`/`{`/`}` 前后的空格规则化处理），但**不改动 plain 中文本语义的原始字符序**（plain 的公式段保留压缩后形式，raw 校验用原串）。
  4. 行内标签白名单：`<sup>/<sub>/<i>/<b>/<br>` → 对应 AST 节点；其他一切 `<…>` 序列按字面文本转义保留 + `UNKNOWN_TAG` issue。
  5. 作者/机构/邮箱行：识别"人名 + 上标 + 机构 + 邮箱"模式（`kind="header"` 时启用），上标符号（`∗†‡`）归入 sup 节点，邮箱归入 text，**不删除任何字符**。
  6. 卫生：剥离 C0/C1 控制符（`CONTROL_CHAR` issue）；全角/半角混排仅在公式体内归一（`MIXED_WIDTH` issue），正文不动。
- **输入输出说明**：输入为原始字符串 + 文本类别；输出 `NormalizedText`。落库由 `textnorm/repository.py` 负责（blocks 表加 `normalized_plain TEXT`、`normalized_rich JSONB`，可空，Alembic 迁移）。
- **单元测试验证要点**（全部基于真实 MinerU 样本 fixture）：
  - `Ashish Vaswani<sup>∗</sup> Google Brain avaswani@google.com` → sup 节点含 `∗`，plain 无 `<sup>` 字面量且无字符丢失（去标签后逐字比对）。
  - `$P _ { d r o p } = 0 . 1$` → math_inline 节点，内容为 `P_{drop}=0.1` 风格紧凑 LaTeX。
  - `$$ \operatorname{Attention}(Q,K,V)=…\tag{1} $$` → math_block 节点 + `tag_no="1"`，text 不含 `$$`、不含 `\tag`。
  - 孤立 `$`（如价格 `$10 and $20` 类误识别样本）→ 无 math 节点，issue 命中，plain 保留 `$`。
  - `<table>`、`<unk>` 等非白名单标签 → 转义字面量 + issue。
  - 幂等：`normalize(normalize(x).plain)` 不再产生新 issue（结构稳定性）。

---

### M2 rich 渲染内核（前端新增）—— 统一富文本渲染

- **模块名称**：`frontend/components/rich/`
- **模块职责**：实现 §5.5 `<RichText>`，把 `NormalizedText`/AST/裸 string 渲染为 React 节点。KaTeX 渲染公式；白名单行内标签转语义元素；链接安全；失败降级。
- **需要遵守的接口契约**：§5.3 `RichNode`、§5.5 `<RichText>` props；`lib/contracts.ts` 需同步后端 DTO 类型镜像。
- **业务逻辑要求**：
  1. 输入分派：`NormalizedText` → 直接渲染 `rich`；`RichNode[]` → 直接渲染；`string` → 走"宽松模式"（前端实现与 M1 同规则的轻量版规范化：定界符识别 + 白名单标签 + 未配对 `$` 处理；允许规则子集，但渲染结果不得出现残留定界符）。
  2. KaTeX 调用：`math_inline` → `katex.renderToString(tex, {displayMode:false, throwOnError:false})`；`math_block` → displayMode:true；`tag_no` 渲染为公式编号角标。
  3. **失败降级纪律**：KaTeX 抛错或返回空 → 渲染"去定界符的原始 LaTeX 文本"（等宽字体样式），**绝不允许 `$`/`$$`/`\tag` 字面量出现在 DOM**。
  4. 安全：link 节点仅放行 `http/https/mailto`，加 `rel="noopener noreferrer" target="_blank"`；任何未识别节点类型按 text 渲染；不引入 `dangerouslySetInnerHTML` 渲染非 KaTeX 内容（KaTeX 输出除外，其输出前经 sanitize）。
  5. 埋点：`onIssue` 回调把宽松模式发现的问题上报（M11 冒烟门禁用）。
- **输入输出说明**：输入 props；输出 React 元素树。零网络请求、零全局状态。
- **单元测试验证要点**（React Testing Library + jsdom）：
  - 同一 `NormalizedText` 分别经四个宿主（LongText/表格单元格/证据引文/媒体介绍的测试壳）渲染，**textContent 完全一致**（一致性基线）。
  - 恶意输入 `<img src=x onerror=alert(1)>`、`<script>…` → DOM 中为转义文本，无节点注入。
  - KaTeX 失败样本（如 `\badcmd{`）→ DOM 含可读 LaTeX 文本且 `textContent` 不含 `$`、`$$`、`\tag`。
  - 宽松模式：M1 的全部 fixture 串直接以 string 输入，textContent 不含 `<sup>` 字面量、不含 `$$`。
  - 链接：`javascript:alert(1)` href → 渲染为纯文本，无 `<a>`。

---

### M3 表格与公式渲染接入 —— 四处消费方统一走 rich

- **模块名称**：`frontend/components/{TableRender,MathText,LongText,RichText}.tsx` + `components/source/{ExtractedTable,ExtractedFormula,SourceMedia}.tsx`
- **模块职责**：把四个既有渲染组件与三个 source 组件的内部实现替换为 `components/rich/` 内核；旧文件保留导出签名（re-export + props 适配），不破坏既有 import。
- **需要遵守的接口契约**：§5.5 `<RichText>`；`MediaViewPolicy`（SourceMedia 的 policy 字段只读展示，不判定）。
- **业务逻辑要求**：
  1. `TableRender`/`ExtractedTable`：表格 HTML（`table_html`）仍走 sanitize 后的 `dangerouslySetInnerHTML`（结构表），但**每个单元格内的文本节点**经 rich 内核处理公式与行内标签（实现方式：sanitize 后对单元格文本做 rich 渲染的字符串模式，或 DOM 后处理——任选，但公式必须渲染）。
  2. `ExtractedFormula`：latex 字段先剥离 `$$`/`\tag`（调 M2 宽松模式工具函数），再交 KaTeX。
  3. `LongText`：优先使用 detail 的 `normalized` 字段；缺字段时回退 string 宽松模式。
  4. `MathText.tsx`/`RichText.tsx` 旧实现删除，改为 re-export `rich/RichText`（保留旧 props 的适配层，标记 deprecated）。
- **输入输出说明**：各组件 props 不变；内部渲染路径唯一。
- **单元测试验证要点**（对 M1 真实 fixture 渲染）：
  - `$1.0 \cdot 10^{20}$`、`$$…\tag{1}$$`、`O(n^{2} \cdot d)` 三个样本在表格/公式/正文三处均渲染为 KaTeX 输出（断言 `.katex` 节点存在）。
  - 三处渲染后的 textContent 均不含 `$`、`$$`、`\tag`、`<sup>` 字面量。
  - 回归：既有组件的快照测试（若无则补最小快照）不因 props 适配层而破坏。

---

### M4 媒体策略与查看器 —— 策略统一 + 旋转/缩放/复位

- **模块名称**：后端 `backend/app/modules/visual/policy.py`（重构）+ `contracts/visual.py`；前端 `frontend/components/media/`
- **模块职责**：(a) 后端输出唯一 `MediaViewPolicy`，前端所有消费点只读不判；(b) `MediaViewer` 提供旋转（90° 步进）/缩放/复位；(c) `MediaBadge` 统一徽标与不可用原因。
- **需要遵守的接口契约**：§5.3 `MediaViewPolicy`、§5.5 `<MediaViewer>`；§5.1 `GET /papers/{id}/media`（policy 必有值）、`/presentation` 配图带 policy。
- **业务逻辑要求**：
  1. 策略四态优先级：`original`（有原件资产字节可访问）→ `extracted`（有 `extracted.table_html/latex`，表格/公式媒体的正常归宿）→ `page`（有整页锚点可回看）→ `unavailable`（前三者皆无，`reason_text` 必填，如"该媒体为 MinerU 提取产物，原始 PDF 未保留对应区域"）。
  2. 消费点收敛清单（逐一改）：媒体列表（`media` 端点响应）、图谱节点配图、讲解分镜配图（presentation）、证据抽屉——四处全部删除本地判定，改读 policy 字段。
  3. 前端 `lib/sourcePolicy.ts` 删除判定逻辑，退化为 `policy → 徽标文案/颜色` 纯映射。
  4. 查看器：`rotation` state ∈ {0,90,180,270}，CSS `transform: rotate() scale()` 实现，**不改资产字节、不上传**；unmount 或点"复位"回到 0/100%；缩放范围 0.25–4 倍；旋转后对调容器宽高避免裁剪。
  5. 图床字节方向错误**不入库修复**（视图层解决，符合任务书 P6 要求）。
- **输入输出说明**：后端输入 media 记录 + 资产清单，输出 `MediaViewPolicy`；前端输入 policy + assets，输出查看器 UI。
- **单元测试验证要点**：
  - 后端：构造"无原图有 extracted.table_html"→ `kind=extracted`；"无原图无 extracted 有页锚点"→ `page`；三者皆无 → `unavailable` + `reason_code=NO_SOURCE_ASSET` + `reason_text` 非空；资产文件在磁盘缺失 → `ASSET_MISSING_ON_DISK`。
  - 契约测试：`/media`、`/presentation` 两处返回的同一 media 的 policy **逐字段相等**（防分叉）。
  - 前端：旋转 90° 后 `transform` 含 `rotate(90deg)`；关闭重开 → 复位；缩放按钮边界 0.25/4 截断。
  - 不可用徽标 tooltip 展示 `reason_text`。

---

### M5 证据门输入规范化与可解释未支持

- **模块名称**：`backend/app/modules/evidence/`（gate.py / semantic.py 重构）
- **模块职责**：判定输入一律使用 textnorm 产物；判定输出携带理由与规范化前后对照。
- **需要遵守的接口契约**：§5.3 `EvidenceVerdict`（新增 `reason/quote_before/quote_after`）；§4.6 职责边界；纪律 3（quote 逐字来自原文块）。
- **业务逻辑要求**：
  1. 取切片时同时取 `raw`（原文）与 `plain`（textnorm 产物）；blocks 表无 normalized 字段时**现算**（调 `textnorm.normalize`），并记 `TEXT_NOT_NORMALIZED` 警告日志（防御）。
  2. 送 LLM 的 `evidence_text` = `plain`；prompt 模板新增"必须输出 reason：一句话说明 supports/contradicts/insufficient 的依据，insufficient 须说明缺什么信息"。
  3. 输出结构化回收：LLM 返回 JSON `{verdict, confidence, reason}`，解析失败降级为 `insufficient + reason="llm_output_parse_failed"`（不抛错阻断管线）。
  4. `quote_before` = raw 切片（供用户逐字核对）；`quote_after` = plain（实际判定输入）。
  5. locator 的锚点定位在 plain 上做；落库 quote 字段保持 raw（纪律 3 不破坏）。
  6. 前端 `evidence/` 抽屉新增展示：判定理由、引文原样 vs 规范化后对照（折叠面板）。
- **输入输出说明**：输入 statement + evidence slice（raw+plain）；输出 `EvidenceVerdict` 落库（validations 表加 `reason TEXT`、`quote_before TEXT`、`quote_after TEXT`，可空迁移）。
- **单元测试验证要点**：
  - 脏切片（含 `$P _ { d r o p } = 0 . 1$`、`<sup>∗</sup>`、跨行 `$$…$$`）规范化后 mock LLM 判 supports → verdict=supports 且 `quote_after` 无 `$`/`<sup>` 残留、`quote_before` 与原块逐字一致。
  - mock LLM 返回 insufficient → 响应必带非空 `reason`。
  - mock LLM 返回非法 JSON → 降级 insufficient + `reason="llm_output_parse_failed"`，不抛异常。
  - 回归语料对比：同一批 statement，规范化前后两次判定的 supports 率不降低（用录制 fixture 断言）。

---

### M6 QA SSE 契约与断流恢复

- **模块名称**：后端 `backend/app/modules/qa/stream.py`（重构）+ `api/canonical.py` 端点；前端 `hooks/useQAStream.ts` + `lib/sse.ts`（重构）
- **模块职责**：实现 §5.2 SSE 事件契约全量保证与前端断流状态机。
- **需要遵守的接口契约**：§5.2 全部（事件字段、时序、保证、恢复协议）；§5.1 新增 `GET /papers/{id}/qa/answers/{answer_id}`；§5.4 错误码 `STREAM_TIMEOUT/ANSWER_GATED/ANSWER_NOT_FOUND`。
- **业务逻辑要求**：
  1. 建流即落库：进入 handler 先创建 answer 行（status=streaming）→ 立即发 `meta{answer_id, mode}`。
  2. 终结事件保证：用 try/except/finally 包裹生成全过程——成功发 `final`；任何异常（含 LLM 超时、解析失败、发布门拦截）捕获后发 `error`；finally 中若两个都没发过则补发 `error{code:"STREAM_NO_TERMINAL_EVENT"}` 并记告警日志（防御性兜底）。
  3. deadline 120s：到点未完成 → 中断生成、发 `error{code:"STREAM_TIMEOUT", retryable:true}`，answer 行落库为 partial（已产出的 sentence 片段保留）。
  4. 心跳 15s：无业务事件期间发 `: ping`。
  5. 恢复端点：按 answer_id 读落库 answer，streaming 中返回 `{status:"streaming"}`，完结返回完整 QAAnswer。
  6. 前端 `useQAStream` 实现 §5.2 状态机五条规则；45s 无帧判断流；恢复成功 UI 标注"连接中断，已恢复结果"；失败给"重试"按钮（同问重发新流）。
- **输入输出说明**：输入 `{question, mode_hint?}`；输出 SSE 事件流 + answer 行；恢复端点输入 answer_id 输出 QAAnswer。
- **单元测试验证要点**：
  - 后端：mock 生成成功 → 事件序列以 `final` 结尾且仅一次；mock LLM 抛异常 → 以 `error` 结尾；mock 生成挂起超过 deadline（注入短 deadline）→ 收到 `STREAM_TIMEOUT` error；任意路径断言"终结事件恰一次"。
  - 后端：`meta` 事件在 100ms 内发出（注入时钟断言）。
  - 前端（msw/mock EventSource 或自研假流）：中途断流 + 已持 answer_id → 触发恢复拉取并展示结果；恢复返回 streaming → 退避重拉至多 3 次后显示可重试；未持 answer_id 断流 → 直接可重试；收到 error 事件 → 展示 message，retryable=true 时给重试按钮。

---

### M7 问答"不受限"策略

- **模块名称**：`backend/app/modules/qa/service.py`（重构）+ `answer_gate.py`（保持）
- **模块职责**：实现 mode 语义全集：聊天类问题 → `general`；论文问题有证据 → `generated/extractive`；论文问题无证据 → `not_mentioned`（明确"论文中没有提到 X"）或 `general`（通用回答 + 明确标注）；`abstained` 仅用于发布门拦截场景。**任何输入都必须产出非空答案**。
- **需要遵守的接口契约**：§5.3 `QAAnswer{ mode, grounded, note, answer_id }`；纪律 3（引用不上的句子不发布，answer_gate 职责不变）；§2.1-3 三类默认问题必须有答案。
- **业务逻辑要求**：
  1. 意图路由：规则前置（问候/闲聊/与论文无关 → general）+ 检索兜底（论文相关问题但 retrieval 召回为空或分数低于阈值 → not_mentioned；用户明确要求"不管论文直接答"或 mode_hint=general → general）。
  2. `not_mentioned` 模板：`"论文中没有提到{X}"` + 可选"与论文最接近的内容是…"（若有低分召回，标注为"相关度低"）；`grounded=false`。
  3. `general` 模板：回答正文 + `note="以下为通用回答，非论文内容"`；**不带 citation**（不伪造溯源）。
  4. 发布门顺序：answer_gate 在 generated/extractive 模式上保持现有"引用不上不发布"；general/not_mentioned 模式天然无引用，不受门拦截但 `grounded=false`。
  5. 空白兜底：任何分支结束若 answer 文本为空 → 替换为 `not_mentioned` 模板或错误事件（不允许空字符串落库）。
- **输入输出说明**：输入 question + mode_hint + 检索结果；输出 QAAnswer（经 M6 的流式通道或非流式端点）。
- **单元测试验证要点**：
  - 三类默认问题（"你好，介绍一下你自己" / "这篇论文的核心方法是什么"（有证据）/ "这篇论文提到量子计算了吗"（无证据））→ 分别 general / generated|extractive / not_mentioned，且答案全非空。
  - general 回答：note 非空、citations 为空、grounded=false。
  - not_mentioned：note 含问题关键词、grounded=false。
  - mock 检索空 + 生成空串 → 落库答案非空（兜底模板）。

---

### M8 图谱分层布局与交互

- **模块名称**：`frontend/components/graph/`（新增）+ `views/GraphView.tsx`（重写，对外 props 不变）
- **模块职责**：自研轻量分层布局（零依赖）+ 折叠/筛选/聚焦/缩放交互。
- **需要遵守的接口契约**：§5.3 `GraphLayoutInput/Output`、§5.5 `<GraphCanvas>`；§2.2 性能约束（100 节点交互不卡）；不引入 ELK/cytoscape/dagre。
- **业务逻辑要求**：
  1. 泳道分层：kind → 泳道（纵向带）；泳道内按边的拓扑序分层（Kahn 算法取最长路径分层，环按启发式断边后置）；层内按重心法（barycenter）排序减少交叉，迭代 4 轮。
  2. 冲突消解：同层节点按排序依次放置，垂直间距 = max（节点高） + 24px；全图扫描断言任意两节点包围盒不重叠（算法保证 + 单测断言双保险）。
  3. 边标签：放边中点；与节点包围盒相交时沿边方向偏移至最近空位；仍相交则省略并计入 `edge_labels` 缺省（宁可不显示不可遮挡）。
  4. 交互：按 kind 折叠（折叠为聚合节点，边重定向）；kind 筛选；点击节点聚焦 ego 网络（一度邻居，其余淡化）；`@xyflow/react` 原生缩放/平移。
  5. 确定性：`seed` 固定，同输入布局逐位相同（快照测试可复现）。
- **输入输出说明**：输入 graph DTO（nodes/edges/lanes）；输出 positions + edge_labels；纯函数，无 IO。
- **单元测试验证要点**：
  - 真实样本（39 节点/33 边）+ 合成 80 节点/100 节点图：任意两节点包围盒最小间距 > 0；边标签与节点重叠数 = 0（省略的不计）。
  - 布局确定性：同输入两次调用输出 deep equal。
  - 含环图不死循环（断边启发式生效，分层数 ≤ 节点数）。
  - 折叠某 kind 后：该 kind 节点不渲染、聚合节点出现、关联边重定向到聚合节点。
  - 性能：100 节点布局计算 < 50ms（注入 performance.now 断言，CI 宽容阈值 200ms）。

---

### M9 投影层收敛 + 契约测试

- **模块名称**：`backend/app/projection/`（新增）+ `schemas/adapters.py`（收敛）+ `modules/{claims,graph,scene,evaluation,qa}/legacy.py`（删副本）
- **模块职责**：canonical→legacy 唯一投影入口；消灭"两份投影只修一处"事故结构。
- **需要遵守的接口契约**：§4.8 职责边界；`projection/CONTRACT.md` 字段清单；既有 legacy 端点响应字段一个不少（兼容性硬约束）。
- **业务逻辑要求**：
  1. 把 `schemas/adapters.py` 的 `to_legacy_*` 函数原样迁入 `projection/` 按域拆分；`adapters.py` 改为 re-export + DeprecationWarning（下个里程碑删除）。
  2. 五处 `modules/*/legacy.py` 删除全部手写投影代码，仅保留"canonical 优先 + 旧表兜底"读取编排，投影一律 `from app.projection import ...`。
  3. 纯函数纪律：projection 函数不做 DB 查询、不抛 DomainError（非法输入返回 None + 日志）。
  4. `CONTRACT.md`：列出每个投影函数的输入类型 → 输出字段清单（字段名 + 来源字段），作为契约测试比对基准。
- **输入输出说明**：输入 canonical ORM 记录/DTO；输出 legacy 形态 dict/Pydantic。
- **单元测试验证要点**：
  - **双读一致性（核心防事故测试）**：同一 canonical 记录，经 `api/routes.py` legacy 端点与 `api/canonical.py` 兼容字段两条路径读取，响应逐字段 deep equal；对 claims/graph/scene/evaluation/qa 五个域各至少一例。
  - 静态门禁：仓库 grep 断言 `def to_legacy_` 只出现在 `app/projection/` 下（CI 脚本）。
  - CONTRACT.md 漂移检查：脚本解析投影函数输出模型字段集与 CONTRACT.md 清单比对，不一致即失败。
  - 兼容回归：既有 legacy 端点快照测试（若无则对五域补最小快照）全部通过。

---

### M10 评测可测性模型 + 导入即评测

- **模块名称**：`backend/app/modules/evaluation/`（重构）+ `contracts/evaluation.py` + `pipeline` 的 evaluate/qa_bank 阶段
- **模块职责**：15 个固定指标全部接入 `MetricValue` 可测性模型；修复 usage 丢失；导入流程自动完成 AI 金标集 → 作答 → 评测闭环。
- **需要遵守的接口契约**：§5.3 `MetricValue`；§5.1 `GET /evaluation`（basis 字段）；纪律 1（not_evaluated 不许填 0）、纪律 2（AI 口径标 basis）；REFACTOR_SPEC L613（proxy 不冒充 measured）。
- **业务逻辑要求**：
  1. 指标注册表：15 个指标各声明 `compute() -> MetricValue`，无法计算时返回 `not_evaluated + reason`（机器可读 reason 码 + 人读文案），**禁止返回 0**。
  2. `anchor_region_hit_rate`：原文无坐标矩形 → `not_evaluated, reason="source_pdf_has_no_coordinate_rects"`；有矩形才计算 IoU（measured）。
  3. usage 修复：`_row_to_answer` 恢复 usage 字段（DB 已存则读出；迁移期老数据无 usage → 时延/token 四项 `not_evaluated, reason="usage_missing_in_answer_rows"`，新作答必须有 usage）。
  4. basis 分离：AI 金标集评分一律 `basis="ai_generated"`；`POST /golden-set/confirm` 后重评可升 `human_confirmed`。前端 EvalView 对 ai 口径全部带徽标说明。
  5. 导入即评测：pipeline 的 qa_bank（AI 起草金标 + 8 题作答）→ evaluate 顺序执行；任一阶段失败 → 对应指标组 not_evaluated + reason，**不阻断 publish**。
  6. AI 裁判输出预算：沿用"压小要求 + 截断放大预算"，并加输出预算自适应（按题目数线性估算 max_tokens，截断重试至多 2 次）。
- **输入输出说明**：输入 paper_id + basis；输出 `EvaluationReport` 落库 + 端点下发。
- **单元测试验证要点**：
  - 15 指标遍历：每个 MetricValue 满足"status=not_evaluated ⇔ value=None 且 reason 非空"（不变量断言）。
  - 无坐标矩形 fixture → anchor_region_hit_rate 为 not_evaluated + 指定 reason 码；有矩形 fixture → measured 且 0≤IoU≤1。
  - 老数据 answer 行（无 usage）→ 时延/token 四项 not_evaluated + `usage_missing_in_answer_rows`；新作答行 → measured。
  - 导入闭环集成测试（小 fixture 论文）：publish 后 GET /evaluation → ai_overall_score 有值，或全部未出值指标带 reason 清单。
  - AI 裁判 mock 截断 → 预算放大重试 ≤2 次，仍失败 → 对应指标 not_evaluated，不阻断流程。

---

### M11 文本卫生回归门禁

- **模块名称**：`backend/app/tests/hygiene/`（新增）+ 前端 `rich/` 冒烟测试
- **模块职责**：把"文本卫生"变成 CI 门禁：后端对回归语料扫描问题；前端对渲染输出扫描残留。
- **需要遵守的接口契约**：复用 M1 `scan()` 与 M2 `onIssue` 埋点；§2.1-1 验收标准。
- **业务逻辑要求**：
  1. 回归语料库：≥3 篇真实论文的 MinerU 产物快照（含 Attention Is All You Need），固化为 fixture（含已知脏样本：`<sup>` 行、未配对 `$`、`$$…\tag{N}$$`、控制符）。
  2. 后端门禁：对语料全量执行"normalize → scan(plain 输出）"二次扫描——规范化后的 plain 再扫必须 **0 个新 issue**（即 normalize 把自己该处理的都处理了）；raw 扫描的 issue 必须全部有 `TextIssue` 记录且 code 在枚举内。
  3. 前端门禁：语料 rich AST 经 `<RichText>` 渲染后，对 DOM textContent 正则扫描：`(?<!\$)\$(?!\$)` 未配对残留、`$$`、`<[a-z]+>` 标签字面量、`[\x00-\x08\x0b\x0c\x0e-\x1f]` 控制符——四者命中数必须 = 0。
  4. 门禁脚本挂 CI（后端 pytest 一个文件、前端 vitest 一个文件），失败阻断合并。
- **输入输出说明**：输入 fixture 语料；输出测试断言（无额外运行时产物）。
- **单元测试验证要点**（本任务自身即测试，验收 = 测试在 CI 常绿）：
  - 人为注入一个未处理的新脏模式 → 门禁如期变红（自验证测试）。
  - 三篇语料四门扫描（后端二次扫描 + 前端四正则）全绿。
  - issue 枚举漂移检查：TextIssue.code 的 Literal 集合与 scan() 实际可产出集合一致。

---

### M12 阶段进度与可续跑（优化项）

- **模块名称**：`backend/app/modules/pipeline/`（progress.py / resume.py 新增）+ `frontend/hooks/useJobEvents.ts`（扩展）
- **模块职责**：导入全过程阶段进度可见；worker 中断后可从断点续跑且不重复计费。
- **需要遵守的接口契约**：§5.1 `/process`（from_stage）与 `/rebuild-derived`（stages）；§4.9 `StageEvent`；性能约束（单篇导入 ≤ 6 分钟）。
- **业务逻辑要求**：
  1. 阶段注册表：每个阶段声明 `name, idempotent_key(paper_revision) -> str, run(ctx), estimate_pct`。
  2. 进度事件：阶段 start/finish/fail 写 jobs 表并经既有 jobs SSE 通道推送 `StageEvent{ stage, status, progress_pct, message }`；前端导入页展示阶段时间线与当前阶段。
  3. 幂等键：`sha256(paper_revision_id + stage + 输入指纹)`；阶段完成时记录；重跑时已完成的阶段（键命中且产物存在）直接跳过——AI 调用类阶段（claims 起草、qa_bank 作答、evaluate 裁判）跳过即不重复计费。
  4. 断点续跑：`POST /process { from_stage }` 从指定阶段起跑；不传则从第一个未完成阶段起跑（默认安全）。
  5. ctx 默认安全：`ingest` 内部自动装配模型快照（ai 模块快照登记表），调用方不传 ctx 不再导致快照缺失（修复 D-67 根因）；快照缺失时阶段失败并给明确错误而非静默。
- **输入输出说明**：输入 paper_id + 可选起点；输出 JobHandle + 阶段事件流；产物为各阶段落库数据 + 幂等键记录。
- **单元测试验证要点**：
  - 模拟 worker 在 index 阶段后崩溃（kill mock），重跑 `/process`：parse/textnorm/normalize/index 四阶段被跳过（断言 ai 调用计数为 0、阶段事件为 skipped），后续阶段正常执行。
  - 重复跑同一阶段：AI 类阶段的 LLM 调用计数不增加（mock ai 客户端计数器断言）。
  - `from_stage="evaluate"` → 仅 evaluate/publish 执行。
  - 进度事件序列：start/finish 成对出现，progress_pct 单调不减。
  - ctx 不传时 ingest 完成且快照登记记录存在（回归 D-67）。

---

## 附：任务依赖图与排期建议

```
M1 textnorm ──┬─→ M2 rich 内核 ─→ M3 渲染接入 ─┐
              ├─→ M5 证据门规范化              ├─→ M11 卫生门禁
              └─→ (M6/M7 无强依赖，可并行)      │
M9 投影收敛（独立，随时可做）                   │
M4 媒体策略（独立，M2 之后接前端更顺）          │
M8 图谱布局（独立）                            │
M10 评测模型 ──→ 依赖 M7 的 usage 完整落库      │
M12 进度续跑 ──→ 依赖 M1 落位（阶段表新增 textnorm）
```

建议波次：**W1 = M1 + M9 + M4（后端部分）**；**W2 = M2 + M5 + M6 + M7**；**W3 = M3 + M4（前端）+ M8 + M10**；**W4 = M11 + M12 + 全量回归**。
