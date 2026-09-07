# SPEC_REVISED — ResearchLens 重构规格（完全重写）

> 依据 `recon/OSS_DEEP_DIVE.md` 对 **Paper2Video / Preacher / Dify** 的深度研读，把 ResearchLens
> 重构为「**模块化流水线 + 厚实数据 + 高信息密度交互**」。本文档是模块化施工总图。
>
> 核心转变：由「单薄展示」→「每模块做厚、信息充足、可操作」；讲解员由「自动播放的廉价头像」→
> 「显式控制的场景化讲解播放器」。仍基于开源优秀项目复用缝合（只取架构思想，代码自研）。

---

## A. 总体架构（模块正交 · 单职责 · 可独立运行）

```
                 ┌─────────────── 前端（模块化视图）───────────────┐
   Landing/上传   │  论文地图 · 方法 · 证据链 · 研究图谱 · 讲解 · 问答 · 评测 · 论文阅读 │
                 └───────────────▲───────────────────────────────┘
                                 │ REST + SSE（任务追踪/流式）
                 ┌───────────────┴───────────────────────────────┐
                 │  后端 modules/（业务域子包，每模块=模型+服务+API+评价）│
                 │  parse→structure→claims→evidence→graph→scene→qa→eval │
                 │  + core(ai/任务追踪) + visual(程序化渲染)          │
                 └───────────────▲───────────────────────────────┘
                                 │ ORM
                 ┌───────────────┴───────────────────────────────┐
                 │  数据：SQLite/Postgres · AI：OpenAI兼容(多供应商降级)   │
                 └───────────────────────────────────────────────┘
```

**设计原则**（吸收三个项目精髓）：
1. **一模块一职责**（Paper2Video）：Slides/Subtitles/Speech…→ 对应 结构/断言/证据/场景/问答…
2. **自顶向下分层规划**（Preacher）：高层场景 → 低层步骤细节，每场景自包含（含讲解词+证据+图）。
3. **结构化中间表示**（Paper2Video/Dify）：LLM 只产出 JSON；视觉由程序渲染。
4. **Everything is an API**（Dify）：每个模块能力都暴露 REST；任务追踪 + SSE 可观测。
5. **观众/作者双维度评测**（Paper2Video）+ 分项打分（Preacher）= ResearchLens Evaluation。

---

## B. 模块 + 数据模型 + UI + 评价 契约

> 每个模块：**职责 / 数据模型（厚） / 前端视图（信息+操作） / 评价口径**。

### 1) parse（解析器）
- 职责：PDF → pages → blocks（段落/标题/图/表/公式），保留阅读顺序。
- 数据：`PaperPage{page_no, full_text, blocks:[{type,content,region}]}`。
- UI：论文阅读视图以此渲染「真页面」（段落+图+表+公式），可点击定位上方/下方。
- 评价：结构抽取准确率。

### 2) structure（结构/地图）
- 职责：blocks → sections（标题/kind/page/完整正文 body/key_points）+ Paper Map。
- 数据：`Section{heading,kind,page,summary,body,key_points[]}`；`Paper.map{problem,method,dataset,experiment,result,limitation}`。
- UI：论文地图 = 摘要 + **六个维度卡片（每卡正文述说 + 关键证据/图计数）** + **可展开的完整章节树（显示正文摘要+要旨）**。
- 操作：点击章节树 → 跳到该章节（论文阅读）或高亮其断言。
- 评价：结构抽取准确率、章节覆盖。

### 3) claims（断言）
- 职责：从正文提炼「可验证断言」，每条含 statement/type/confidence/rationale。
- 数据：`Claim{claim_id,statement,type,confidence,status,rationale}`。
- UI：证据链视图 = 断言列表（分组：RESULT/METHOD/LIMITATION/CONTEXT），每条可展开看 rationale。
- 操作：点击断言 → 联动右侧证据。
- 评价：断言抽取精度/召回。

### 4) evidence（证据 · Evidence Gate）
- 职责：把断言链接到**论文内证据**（页码/区块/区域/原文引用 quote）；无证据→unsupported，只标「AI 解释」。
- 数据：`Evidence{page,region,region_type,text(上下文句),quote(精确引文),confidence}`。
- UI：证据链视图右侧「证据面板」：每条证据显示**高亮的原文引用 + 页码 + 区域 + 可跳页**；
  无证据断言显示「仅 AI 解释」。
- 操作：点击「跳转到 p.6」→ 论文阅读视图高亮该处；点击证据 → 打开对应原图/表格。
- 评价：Citation Coverage、Claim-Evidence Alignment、**Unsupported Claim Rate（目标≈0）**。

### 5) graph（研究图谱）
- 职责：claims+evidence → 图（problem→method→experiment→claim→evidence），节点携带详情。
- 数据：`GraphNode{id,kind,label,props{text,claim_id,evidence}}`、`GraphEdge{source,target,label}`。
- UI：React Flow 图谱；**点击节点 → 右侧详情面板**（断言全文 / 证据 / 关联图 / 关联表）。
- 操作：点节点展开、双击定位、小地图缩放。
- 评价：图谱一致性、可点击可达。

### 6) scene（场景化讲解 · Presenter）
- 职责：自顶向下规划：高层场景（intro/problem/method/exp/result/limitation）→ 低层步骤 + 讲解词 + 证据 + 图。
- 数据：`Scene{order,kind,title,summary(多句),steps[{label,detail}],narration{script,subtitle,highlights[]},evidence_refs[],figure_refs[]}`。
- UI：**场景化讲解播放器**（非廉价头像）：
  - 左侧分镜列表；中间当前场景：标题+多句摘要+逐步要点+**讲解词（脚本）+ 字幕 + 引用的证据/原图**；
  - **显式控制**：播放/暂停/上一步/下一步；**无自动播放**；语音为**可选项（默认关，点图标才朗读）**；
  - 进度条可点。
- 操作：切场景、播放/暂停、展开证据、切换语音。
- 评价：讲解词与论文一致性（Alignment）、讲解覆盖（Professionalism）。

### 7) qa（证据问答）
- 职责：Retrieval→Evidence→Answer；支持多轮；**PresentQuiz 式出题**（生成题目→按证据作答判分）。
- 数据：`Question{q,a,confidence,evidence_refs[]}`、`Answer{...}`。
- UI：多轮聊天 + 每条答案带**引文（页码+原文引用）**；预设问题；「生成追问」按钮。
- 操作：提问、引用可点（跳页）、追问。
- 评价：Answer Grounding、Quiz 命中率。

### 8) eval（自动评测）
- 职责：综合评测，分「**观众**」与「**作者**」两个维度 + 关键指标 + PresentQuiz + 分项明细。
- 数据：`Evaluation{audience{},author{},metrics{},overall_score}`。
- UI：评测视图 = 总评 + **双维度雷达/卡片**（观众:忠实/易读；作者:原创凸显/可见度）+ **指标明细**
  （证据覆盖率/对齐/无证据率/引用准确/答案 grounded）+ **分项评测（1-5 或百分比）** + 逐断言明细表。
- 操作：切换维度、查看逐断言明细。
- 评价：ResearchLens Score。

### 9) visual（程序化渲染）
- 职责：把 table/figure/method_steps/graph 渲染成 **SVG/Canvas 原图**（零 GPU、零版权）。
- UI：方法视图用原图 + 分步动画；表格渲染为干净表格 + 关键发现高亮。
- 操作：缩放/高亮关键结果。
- 评价：视觉一致性、Aesthetic。

### 10) api / core
- 职责：REST + SSE；任务追踪（每模块 stage/status/记录）；AI 客户端（多供应商/降级/超时）。
- UI：上传页 + 处理进度条（按模块显示「正在解析…正在提取断言…」）。
- 操作：上传、轮询进度。
- 评价：稳定性、降级可用性。

---

## C. 「厚实数据」规范（解决「空空如也」的根因）
每篇演示论文数据必须达级：
- 正文：每章节 **≥2 段真实正文**（body），非 1 句摘要；**≥6 页**，每页含 blocks。
- 图表：**4~6 张原图**（SVG）+ **2~3 张表**（含 key_finding）。
- 断言：**8~12 条**，每条带 rationale + **≥1 条证据**（quote = 论文里的确切原句）。
- 场景：**6 个场景**，每个含多句 summary + 步骤 + 讲解词（脚本 2-3 句）+ 字幕 + 证据/图引用。
- 问答：≥4 组（每组含证据 + 置信度），可生成「追问」。

## D. 演示数据（3 篇原创论文）
- 计算机视觉 `slimseg-net` / 网络安全 `netguard` / 教育 AI `learnflow`（自给、自洽、学术可信）。

## E. 关键修复
- **讲解员不再自动播放 / 无廉价头像**：改为显式播放器，默认不发声，语音为可选开关。
- **每视图信息充足、可点可用**：数据达 C 级，操作达 B 级各模块所列。

## F. 技术栈（不变，重构模块化）
前端 Next.js14+TS+Tailwind+Framer+ReactFlow+pdfjs；后端 FastAPI+Pydantic+SQLAlchemy；
AI OpenAI兼容（DashScope qwen-plus，多供应商降级）；Postgres+pgvector/SQLite；Docker Compose；SSE。

## G. 拆分 Epic
- E1 数据模型+厚实演示数据（先做，解决空虚）
- E2 后端模块化（modules/* 子包）
- E3 前端模块化视图（每视图厚实 + 交互），重写 Presenter
- E4 评测（双维度+quiz+明细）
- E5 任务追踪/SSE + 上传
- E6 Docker + 端到端
