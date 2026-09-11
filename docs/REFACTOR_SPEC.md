# ResearchLens 重构分析与实施契约

审阅日期：2026-09-08。交付性质：架构与接口规格，不包含业务实现。依据：当前工作区代码静态审阅；未运行真实 MinerU/DashScope 任务、浏览器验收或性能压测。文中的风险、目标和验收项不代表已经复现、修复或测得的效果。

本文六章构成后续编码基线。第五章使用结构化类型记法和函数签名，不是可执行实现。第六章各任务可独立交给编码模型，但必须同时提供本文件作为冻结契约。新增接口是设计稿，不表示仓库已经提供。

## 一、原有项目现状与问题诊断

### 1.1 实际架构与业务链路

现状为模块化单体雏形：FastAPI 路由调用 `modules` 门面，门面大量转发到 `services`，共享 SQLAlchemy 模型。前端 Next.js 工作台有八种视图，调用同一 REST 后端；并非已经实现清晰职责隔离的九个业务模块。

实际有两条不等价的导入路径：

1. URL/真实论文自举调用 `modules/pipeline/ingest.py`，组合 PyMuPDF、MinerU 和多次 Qwen 调用，生成论文页面、章节、媒体、断言、场景、图谱等。
2. 上传先保存文件和任务，随后 `/process` 调用 `services/pipeline.py`，主要执行 `services/parser.py` 的 pypdf 解析、断言和评估，不等于完整 MinerU 管线。
3. 展示时再由 `services/presentation.py` 临时猜测证据和图表关联；QA 使用生成的章节与断言构建上下文；评价大多统计字段存在性。
4. 前端已经通过 `FigureImage` 优先使用 `image_b64`，`TableRender` 已优先使用 HTML。因此问题不是“所有页面都只画 SVG”，而是原始信息丢失、来源标签不真实、组件降级不统一、关联契约缺位。

### 1.2 必须修复：P0 原件失真

| 编号 | 代码依据 | 已确认问题及影响 |
|---|---|---|
| D01 | [mineru.py](/D:/develop/workspace/ResearchLens/backend/app/services/mineru.py:163) | `_group_pages` 丢弃页眉页脚和页码块，只保留有文字页面，未保留完整块坐标。物理页、印刷页和原位公式的恢复基础被破坏。 |
| D02 | [mineru.py](/D:/develop/workspace/ResearchLens/backend/app/services/mineru.py:238) | `parse_result` 未形成持久化 bbox/公式对象；表格保留 HTML 但没有统一 PDF 裁剪资产。过滤后重新枚举图表，不是原论文编号。 |
| D03 | [mineru.py](/D:/develop/workspace/ResearchLens/backend/app/services/mineru.py:128) | HTML 转矩阵以正则截取，最多 12 行、12 列、单元格 60 字；合并关系、长数据和公式可丢失。不能作为原表保真兜底。 |
| D04 | [ingest.py](/D:/develop/workspace/ResearchLens/backend/app/modules/pipeline/ingest.py:46) | `_normal_figure` 丢弃图号；解析兜底为了凑足图片将整页截图作为 figure，另有数量截断。原图、页预览、衍生图语义混淆。 |
| D05 | [PaperView.tsx](/D:/develop/workspace/ResearchLens/frontend/components/views/PaperView.tsx:26) | 阅读视图不是原 PDF 阅读器，而是章节摘要/文本重新排版；公式再排版无法保证原字体、编号和版式。 |
| D06 | [MediaModal.tsx](/D:/develop/workspace/ResearchLens/frontend/components/MediaModal.tsx) | 弹层“原图”标签不区分示意 SVG、提取表格和原件；误导用户对真实性的判断。 |
| D07 | [FigureImage.tsx](/D:/develop/workspace/ResearchLens/frontend/components/FigureImage.tsx) | base64 MIME 固定 PNG，与部分提取图片实际编码可能不符；缺统一加载失败策略。 |
| D08 | [TableRender.tsx](/D:/develop/workspace/ResearchLens/frontend/components/TableRender.tsx) | 自制正则清理 HTML 不能构成可靠安全边界；图像组件也内联 SVG。上传内容存在主动内容注入风险。 |

**关键结论：MinerU 的“原始 HTML”是解析器输出原文，不等于 PDF 的像素原件。** 要最大限度保持表头合并、数值、符号、字体、编号与布局，默认展示同一份 PDF 的页面或区域裁剪；HTML 和 KaTeX 是可读、可复制的提取视图，不得冠以“原版”。

### 1.3 必须修复：P1 关联与定位

| 编号 | 代码依据 | 已确认问题及影响 |
|---|---|---|
| D09 | [ingest.py](/D:/develop/workspace/ResearchLens/backend/app/modules/pipeline/ingest.py:148) | 要求 LLM 估计章节页码，且生成 `body` 实为改写；入库页块为空。猜测无法稳定支持精确引用。 |
| D10 | [presentation.py](/D:/develop/workspace/ResearchLens/backend/app/services/presentation.py:15) | `_discover_evidence` 按同页或英文区域关键词匹配，既会漏中文，也会将同页不相干内容关联。 |
| D11 | [presentation.py](/D:/develop/workspace/ResearchLens/backend/app/services/presentation.py:46) | 图表依赖正则匹配图号；`p.1587` 不是图号，无法建立对应关系。逐场景重新开 Session 查询，形成额外查询。 |
| D12 | [page.tsx](/D:/develop/workspace/ResearchLens/frontend/app/paper/[slug]/page.tsx) | `jumpToPaper` 把图表映射到结果章节，没有以物理页和区域作为导航依据。 |
| D13 | [PaperView.tsx](/D:/develop/workspace/ResearchLens/frontend/components/views/PaperView.tsx) | 引文在生成摘要中做字符串高亮；传入引文即提示已定位，未以实际命中为依据。重复章节 kind 也可能产生重复定位 ID。 |
| D14 | [EvidenceRail.tsx](/D:/develop/workspace/ResearchLens/frontend/components/EvidenceRail.tsx) | `includes(fig_N)` 可将 `fig_1` 与 `fig_10` 混淆；按列表下标而非稳定 ID 导航；移动端缺少同等证据入口。 |
| D15 | [PresenterView.tsx](/D:/develop/workspace/ResearchLens/frontend/components/views/PresenterView.tsx) | 无可靠 linked 时仍展示原始引用字符串，不能证明对应原文；缺真正的阅读器联动。 |

“同页”只能产生检索候选，不能直接证明“支持这句话”；“定位成功”也不能直接证明“语义成立”。这两条必须分别校验。

### 1.4 必须修复：事实可信度、生命周期与安全

| 编号 | 代码依据 | 问题与优先级 |
|---|---|---|
| D16 | [qa.py](/D:/develop/workspace/ResearchLens/backend/app/services/qa.py:75) | QA 上下文主要来自 AI 章节/断言且截断，不是完整原文。存在“AI 输出给 AI 作证”的循环。P0。 |
| D17 | [qa.py](/D:/develop/workspace/ResearchLens/backend/app/services/qa.py:94) | grounded 受拒答措辞影响；先答后独立找引用；可用章节摘要补造高置信证据；题库回答也未强制检查引用有效性。P0。 |
| D18 | [ingest.py](/D:/develop/workspace/ResearchLens/backend/app/modules/pipeline/ingest.py:378) | LLM 给出非空 evidence 即标 SUPPORTED；图谱对断言统一生成支持边。没有事实发布闸门。P0。 |
| D19 | [routes.py](/D:/develop/workspace/ResearchLens/backend/app/api/routes.py:89) | URL 路由先建占位论文，worker 再按另一 slug 导入，可能产生另一 paper_id；返回 ID 一直 pending。下载在返回前同步执行，超时可达 120 秒。P0。 |
| D20 | [ingest.py](/D:/develop/workspace/ResearchLens/backend/app/modules/pipeline/ingest.py:325) | 同 slug 删除重建论文，破坏稳定 ID；关联表并非全部有 ORM 级联，数据库约束配置不一致会进一步放大风险。P0。 |
| D21 | [routes.py](/D:/develop/workspace/ResearchLens/backend/app/api/routes.py:214) | 上传全量读入后才检查大小，同名文件覆盖风险；URL 无完整 SSRF、重定向、大小及内容验证。P0。 |
| D22 | [mineru.py](/D:/develop/workspace/ResearchLens/backend/app/services/mineru.py:81) | 批任务 `extract_result` 非空即返回，未等待子任务 done；真实服务可能尚未产出 ZIP。P1。 |
| D23 | [mineru.py](/D:/develop/workspace/ResearchLens/backend/app/services/mineru.py:314) | 即使已有本地字节仍优先解析远程 URL；远程内容更新时，解析结果与保存 PDF 可能不是同一文件。P0。 |
| D24 | [routes.py](/D:/develop/workspace/ResearchLens/backend/app/api/routes.py:237) | 缺论文存在检查、任务幂等与并发保护；BackgroundTasks/启动 daemon 不持久，进程重启丢工作。P1。 |
| D25 | [pipeline.py](/D:/develop/workspace/ResearchLens/backend/app/services/pipeline.py) | 缺文件可被静默跳过；异常后事务回滚处理不完整；任务结束与论文状态可能不一致。P1。 |
| D26 | [ingest.py](/D:/develop/workspace/ResearchLens/backend/app/modules/pipeline/ingest.py:271) | slug 构造可超过模型 String(64)，SQLite 不一定暴露、Postgres 可能拒绝。P1。 |
| D27 | [runtime.py](/D:/develop/workspace/ResearchLens/backend/app/core/runtime.py) | 配置文件写入缺原子性；模型切换缺能力与管理权限限制，聊天可误选 embedding 模型。P1。 |

安全要求是工程威胁模型，不是本次已完成的渗透测试。MinerU ZIP 还需覆盖路径穿越、展开体积/数量限制、嵌套目录；图像过滤阈值需声明坐标单位并保留排除原因，不能把启发式过滤结果当“全部正确”。

### 1.5 耦合、可维护性与性能

**【必须修复】**

- `core/db.py` 的启动 `create_all + ALTER` 捕获并忽略迁移错误，不能证明数据库已达预期版本。采用正式版本迁移及启动版本检查。
- 大量云调用位于长数据库事务中；SQLite 写锁与失败恢复风险高。拆分为短事务、阶段产物和原子发布。
- 前端详情、图谱、讲解、评估、断言串行请求；无断言时最长约 100 秒全页等待；完成后仅刷新部分数据。改为独立加载、版本一致的并行查询。
- 详情一次返回所有 base64、正文和媒体，页文字又截断 4000 字；既重又不足以作原文证据。新增轻量 manifest 与分页原文，保留旧响应。
- `evaluation.py` 把证据存在性当 grounding/视觉一致性，量纲混杂，空数据也可能有分数；GET 还写数据库。必须区分代理指标与人工标注指标。
- `backend/evals/benchmark.py` 的 citation_accuracy 重复乘 100，空结果可触发 `None * 100`；匹配不是一对一，召回率可虚高。需要先修评测再论证竞赛收益。
- `docker-compose.yml` 当前默认主机端口是 3000/8000，LLM 默认 OpenAI/gpt-4o-mini，而非要求的 3002/8002、DashScope/qwen-plus；仅数据库有持久卷，上传与 runtime 配置不持久。

**【建议优化】**

- 把 `modules/*` 从 re-export 改为真正的应用服务与数据所有者；旧 `services` 暂作兼容适配，避免一次搬迁全部文件。
- AIClient 复用 HTTP 连接；在调用方使用 Pydantic 结构验证，不仅 JSON parse；增加全局 deadline、取消、调用预算和配置快照。
- 嵌入能力已有但未接入检索；优先实现中文词法检索，再增量启用云 embedding，不以向量服务健康作为主链路前提。
- `_fill_map` 的 JSON 原位修改需验证 SQLAlchemy 脏检测，改为整体赋值或显式追踪；这是静态风险，未做运行复现。
- MethodStep 生成未保证前端要求的 id；方法步骤仅取尾部文本、图 importance 均 medium，内容覆盖与主图选择需改为有据的产物。
- 实际 `source_mode=real` 在 UI 可能被显示为演示模式。来源类型与采集方式应分离，不能用非 upload 就等于 demo。

## 二、本次重构总体目标与硬性约束

### 2.1 业务目标与非目标

定位为“从论文中提炼**可追溯的研究陈述**，并支持核验、讲解和问答”，不是自动证明科研成果真实、可复现或可直接产业化。Evidence-first 验证的是论文依据及支持关系，不能替代同行评审、实验复现和企业实测。

交付主线：原件保真 → 精确定位 → 逐句证据闸门 → 可恢复生成 → 检索式问答 → 可解释演示。八个视图保留，其中结构、方法、证据链、图谱、讲解、QA 为六展项，阅读与评估是核验底座。

第一版不做全网爬虫、企业 CRM、自动实验执行、跨论文大规模知识图谱、自治 Agent 集群、自建 GPU 模型和新增 TTS 服务。可将需求文本作为单篇论文 QA 的输入，输出“适用性假设/待验证条件”，不冒充已验证产业匹配。

### 2.2 硬性约束

| 约束 | 不可突破的实施边界 |
|---|---|
| 技术栈 | 保留 FastAPI/Pydantic v2/SQLAlchemy 2，SQLite/Postgres+pgvector；Next.js 14/React 18/TS/Tailwind v3/React Flow/Framer Motion/lucide/KaTeX。 |
| AI 与解析 | 继续 DashScope OpenAI 兼容调用，默认 qwen-plus；MinerU 优先、PyMuPDF 降级。API 地址和模型能力以环境配置与实际探测为准，不硬编码未经验证的供应商承诺。 |
| API 兼容 | 现有全部 GET/POST `/api/*` 的 URL、默认成功状态码 200、已使用字段及字段类型保留；新增字段/接口可选启用。不用“换 v2”逃避兼容。 |
| 部署 | Compose 主机 3002/8002，容器内部仍 3000/8000；Postgres+pgvector；本地 SQLite 单 worker；CPU + 云服务，无 GPU。 |
| 性能 | 导入后台执行；新 UI 使用 manifest、懒加载媒体/PDF；QA 可取消并提供进度；旧大响应不作为新工作台启动依赖。 |
| 依赖 | 不引入 LangChain/LangGraph、Celery、Redis、Elasticsearch、本地大模型或向量模型运行时；新增轻量依赖见第三章。 |
| 降级 | MinerU 失败仍可阅读 PDF、获取 PyMuPDF 原文；LLM 失败保留源材料与已验证产物；embedding 失败回退词法检索；不得用假数据伪装正常成功。 |
| 数据 | paper_id/slug 稳定；保留原文件、解析原始产物、版本和迁移备份；现有真实与模拟数据均不得无提示删除或混同。 |

### 2.3 验收指标：目标而非已有效果

以下是初始预算，必须在固定硬件、网络、文档规模和并发下测基线再确认。建议基准：4 vCPU/8 GB、20–40 页中文 PDF、10 个并发阅读/2 个并发 QA，冷/热缓存分开报告。

| 指标 | 候选验收门槛 |
|---|---|
| 原件资产完整性 | 展示为“PDF 原件”的资产 100% 可回溯 source SHA256、页与生成变换；不能只检查图片相似度。 |
| 定位 | 人工标注的明确定位样本物理页正确率 100%；有有效坐标的样本区域命中率 ≥98%；未知项单独统计，禁止删掉困难样本。 |
| 引用 | 人工标注可回答 QA 的引文原文匹配率 100%，支持关系 precision 目标 ≥95%；自动闸门不等于人工真值。 |
| 拒答 | 不可回答集正确拒答率目标 ≥90%，同时报告可回答集误拒率，防止全部拒答刷分。 |
| 延迟 | manifest 服务端 p95 <500 ms；工作台可操作 p95 <2 s；QA 首进度 <1 s，首个经验证答案句目标 <8 s，整体软预算 20 s、硬预算 30 s。 |
| 体积 | 常见论文 manifest 不含 base64/全文，目标 <150 KB；超大论文分页降载。旧接口体积单独保留并监测。 |
| 恢复 | worker 被终止后在租约过期窗口恢复；同一阶段重复执行不得产生重复已发布产物；离线仍能完整打开源 PDF。 |
| 演示价值 | 对比现版测“找出处耗时”、引用错误率、人工核验步骤数、每篇云调用次数/费用、每问 token 与 p95。费用按实际账单口径，不虚构节省。 |

## 三、重构后整体架构设计

### 3.1 方案选择

选择**模块化单体 + 版本化证据底座 + 数据库任务状态机 + 有界 Agent 工作流**。不改成微服务，不通过多起几个聊天角色来冒充 Agent。

- 纯前端替换图片：不能恢复已丢失坐标/页码，否决作为完整方案。
- 全量 Agent 自主规划：成本、稳定性、审计难控制，不适合竞赛主链路。
- 确定性阶段执行 + 局部 Agent 决策：让模型选择补检索、修正或拒绝，代码控制工具、预算、数据写入和发布权限，作为采用方案。

### 3.2 完整目标目录

下树列出目标业务源码、测试及部署入口；省略 `.git`、node_modules、虚拟环境、构建产物与用户上传数据。`__init__.py` 在每个 Python package 中按需存在。现有无关配置/文档保留，历史 demo 数据文件不改名。

```text
ResearchLens/
  README.md
  .env.example
  docker-compose.yml
  docs/
    REFACTOR_SPEC.md
    ARCHITECTURE.md
    ASSET_LICENSES.md
    DECISIONS.md
    OSS_REUSE.md
    SPEC_REVISED.md
    TASKS.md
    contracts/
      legacy-openapi.json
      canonical-openapi.json
      migration-map.md
      verification-report.md
  backend/
    Dockerfile
    requirements.txt
    alembic.ini
    migrations/
      env.py
      script.py.mako
      versions/
        0001_legacy_baseline.py
        0002_source_revision_anchor.py
        0003_verified_artifacts.py
        0004_jobs_retrieval_audit.py
    app/
      main.py
      worker.py
      api/
        routes.py
        legacy.py
        documents.py
        assets.py
        evidence.py
        jobs.py
        qa_stream.py
        dependencies.py
      contracts/
        common.py
        documents.py
        evidence.py
        artifacts.py
        ai.py
        retrieval.py
        jobs.py
        evaluation.py
      core/
        config.py
        db.py
        runtime.py
        errors.py
        security.py
        logging.py
        clock.py
      models/
        models.py
        source.py
        artifacts.py
        jobs.py
        retrieval.py
        audit.py
      schemas/
        schemas.py
        adapters.py
      modules/
        papers/{__init__.py,service.py,repository.py,storage.py,download.py}
        parse/{__init__.py,service.py,normalize.py,pages.py,mineru_adapter.py,pymupdf_adapter.py}
        visual/{__init__.py,service.py,repository.py,crops.py,tables.py,policy.py}
        evidence/{__init__.py,service.py,repository.py,locator.py,gate.py,legacy_resolver.py}
        ai/{__init__.py,service.py,transport.py,validation.py,capabilities.py}
        claims/{__init__.py,service.py,repository.py,prompts.py}
        retrieval/{__init__.py,service.py,repository.py,chunking.py,lexical.py,vector.py,fusion.py}
        graph/{__init__.py,service.py,repository.py}
        scene/{__init__.py,service.py,repository.py,narration.py}
        qa/{__init__.py,service.py,repository.py,answer_gate.py,stream.py}
        pipeline/{__init__.py,service.py,repository.py,stages.py,supervisor.py,tools.py,ingest.py,seed_real.py}
        evaluation/{__init__.py,service.py,repository.py,metrics.py,golden.py}
      services/
        ai.py
        parser.py
        mineru.py
        claims.py
        evaluation.py
        graph.py
        presentation.py
        qa.py
        pipeline.py
      seed/
        demo_papers.py
        common.py
        svgkit.py
        paper_visionlens.py
        paper_netguard.py
        paper_learnflow.py
    evals/
      benchmark.py
      fixtures/
        manifest.json
        labels.json
    tests/
      unit/
        test_documents.py
        test_parse.py
        test_visual.py
        test_evidence.py
        test_ai.py
        test_claims.py
        test_retrieval.py
        test_graph.py
        test_scene.py
        test_qa.py
        test_jobs.py
        test_evaluation.py
      contract/{test_legacy_api.py,test_canonical_api.py,test_events.py}
      integration/{test_sqlite.py,test_postgres.py,test_migrations.py,test_recovery.py}
      fixtures/{legacy_responses.json,mineru_manifest.json,synthetic_cases.json}
  frontend/
    Dockerfile
    package.json
    package-lock.json
    next.config.mjs
    next-env.d.ts
    tsconfig.json
    tailwind.config.ts
    postcss.config.mjs
    playwright.config.ts
    app/
      layout.tsx
      globals.css
      page.tsx
      upload/page.tsx
      paper/[slug]/page.tsx
    components/
      Logo.tsx
      ui.tsx
      Timeline.tsx
      FigureImage.tsx
      TableRender.tsx
      MediaModal.tsx
      RichText.tsx
      MathText.tsx
      EvidenceRail.tsx
      source/{SourceMedia.tsx,SourceBadge.tsx,ExtractedTable.tsx,ExtractedFormula.tsx}
      reader/{PdfReader.tsx,PageImageReader.tsx,AnchorOverlay.tsx,PageSelector.tsx}
      evidence/{EvidenceDrawer.tsx,CitationLink.tsx,VerificationStatus.tsx}
      jobs/{JobProgress.tsx,AgentTrace.tsx}
      views/
        MapView.tsx
        MethodView.tsx
        ClaimView.tsx
        GraphView.tsx
        PresenterView.tsx
        QAView.tsx
        EvalView.tsx
        PaperView.tsx
    hooks/{usePaperWorkspace.ts,useEvidenceNavigation.ts,useJobEvents.ts,useQAStream.ts}
    lib/{api.ts,types.ts,contracts.ts,sourcePolicy.ts,sanitize.ts,sse.ts,cn.ts}
    tests/{media.spec.ts,reader.spec.ts,evidence.spec.ts,qa.spec.ts,workspace.spec.ts}
  data/                         # gitignore；Compose backend-data 卷对应目录
    sources/
    parser-raw/
    assets/
    runtime.json
```

花括号是目录树的紧凑文件列表，不是运行时约定。`services/*` 和现有 `modules/pipeline/ingest.py` 在迁移期仅保留旧签名适配；所有内部调用转向 `modules/*` 公共入口后，另一次版本变更才移除旧门面。数据库表拆分不强迫同时删除旧模型。

### 3.3 数据流、调用与事务

```text
上传 / URL / seed
  -> Paper + Job（一次建立稳定 paper_id，快速返回）
  -> worker 安全获取 PDF -> SourceDocument(hash，不可变)
  -> MinerU（解析相同字节） / PyMuPDF
  -> Page + Block + PageLabelMap + Media + Anchor + raw parser assets
  -> 原文索引
  -> Analyst 提取 ClaimDraft -> Verifier 检验定位/支持/限定条件
  -> Evidence Gate（代码强制）-> 可发布断言/待核验项
  -> Scene/Method/Graph/预置 QA -> 再逐句检查 -> Evaluation
  -> 原子切换 published_revision_id
  -> manifest / 旧 DTO / 阅读器 / 六展项

用户 QA -> scoped retrieve -> 可选 rerank -> AnswerDraft
  -> 逐句 gate -> citation + verified sentence SSE -> final
  -> 审计记录（模型版本、检索结果、校验原因、耗时，不展示思维链）
```

数据分三层：不可变源资料、可重建解析产物、可撤销/版本化生成产物。解析文字必须保留 `origin=source_extraction`，生成摘要只能是 `origin=generated`，后者不能作为一级证据。

数据库命令仅在本模块内开短事务；云调用不得持有写事务。pipeline 在阶段完成后记录产物 digest，并在最终短事务中切换论文发布指针及任务状态。读取永远固定 revision；新版本失败不覆盖旧版本。跨模块不传 ORM Session/实体，传 DTO 与 ID；旧兼容函数内部允许接收旧 Session，但不把它带入云调用。

### 3.4 原件显示策略

| 视图 | 强制要求 | 可保留的程序化补充 |
|---|---|---|
| map | 涉及具体原论文图表时展示原件缩略图，点击打开同一 media_id | 结构导航、章节拓扑；每项生成说明绑定 statement_id。 |
| method | 方法原图用 PDF/MinerU 可核验裁剪；步骤引用打开实际原图/公式 | React Flow/动画作为“方法解释”，禁止冒充原论文流程图。 |
| claim | 数据支持卡默认原表/图裁剪，附精确引用和限定条件 | 证据强弱、矛盾标记，不另画“原数据曲线”。 |
| graph | 点击证据节点进入原件定位，边有关系证据 | 图谱本身是派生组织结构，不是论文原图。 |
| presenter | 涉及内容只列已验证 links；原图、原表、原公式默认 | 与讲解句绑定的高亮覆盖层；不得改变底图数值、标题或颜色编码。 |
| qa | 每个事实句可点开原证；表格问题默认原表局部 | 引用片段/对比解释；重算值标“计算结果”，记录输入证据和计算规则。 |
| eval | 媒体保真检查打开原件并列核对 | 评测统计图可以程序绘制，必须标明样本、公式和评测版本。 |
| paper | 真 PDF 为默认阅读面；公式编号、字体由 PDF 保留 | 可切换提取文本；KaTeX/HTML 明确为再排版模式，原编号来自解析/人工标注，不自动编造。 |

原件模式优先：可验证的 PDF 区域裁剪 → 与同一源文件绑定且可追溯的 MinerU 裁剪 → 对应整页预览 → 明示不可用。整页预览必须标“整页”，不能变成 Figure。无区域时不能声称已精准高亮。跨页表格以多个有序裁剪呈现，不拼接重排成伪原表。

提取表格保留 rowspan/colspan、文本和公式标签；由 DOMPurify 严格白名单清理后内联到受约束容器，禁止脚本、事件、iframe、SVG、外链图片、任意样式和危险 URL。原始 HTML 原封存储为审计产物但不直接执行。清理破坏结构时退回原件，不退回截断矩阵冒充原件。

### 3.5 Agent 能力与竞赛交互

Supervisor 是有界决策器，允许 `accept / retrieve_more / repair / abstain`，不允许自由生成工具名、任意 URL、SQL 或命令。Analyst 只看当前原文块及候选媒体；Verifier 看候选陈述和原证；Presenter 只读已验证陈述。角色可共享 Qwen，不必并发或使用不同模型；独立复核降低同一路径偏差，但不等于独立真值。

固定管线中只在“证据不足/数值矛盾/引用歧义”时进入最多两轮补检索/修正。每轮记录输入块 ID、工具、结果状态、简短可展示理由、token/耗时；禁止公开隐式思维链。达到预算即降级为待核验，不让模型决定绕过 gate。

| 真实痛点 | 交互与差异化 | 可论证而非口号式价值 |
|---|---|---|
| 学生组会读不懂方法，AI 摘要难找出处 | 点击一句讲解，原文/方法图同步定位；切换“解释/原件” | 测定位耗时、核验步骤、理解测验；与单纯摘要页对照。 |
| 创新大赛答辩容易过度宣称效果 | “质疑这句话”触发条件检索，展示适用边界、冲突/缺证与拒答 | 现场演示从无依据断言转为有依据结论；测错误断言流出率。 |
| 湾区企业技术调研难判断论文是否适用 | 输入任务/数据/部署约束，输出引用支持的条件与待验证假设 | 区分“文献报告”与“企业可用”；测约束遗漏率，不宣称自动完成技术尽调。 |
| 引用在截图、PPT、口述间断裂 | 导出证据清单，含 claim、版本、页、区域、hash、验证状态 | 支持复核同一版本；默认不打包原论文全文，避免无必要的内容再分发。 |
| 展示服务偶发断网 | 显示已完成原件与有据产物，任务时间线标注失败和降级 | 断服务现场仍可核验；报告恢复成功率与数据一致性。 |

### 3.6 依赖增删

| 依赖 | 处理与理由 |
|---|---|
| Alembic | 新增后端运行/迁移依赖；SQLAlchemy 配套版本迁移，替代静默 ALTER。锁定经 SQLite/Postgres 测试的版本。 |
| DOMPurify | 新增前端运行依赖；专用于提取 HTML 的安全白名单清理，避免自行维护安全正则。浏览器端清理，SSR 不渲染不可信 HTML。 |
| @playwright/test | 新增前端开发依赖，用于 PDF/媒体/高亮/移动端端到端验收，不进入运行镜像依赖层。 |
| react-pdf | 仓库已声明，复用而非新增；PDF.js worker 与实际安装版本匹配并本地托管，动态加载阅读器。 |
| PyMuPDF/httpx/KaTeX 等 | 复用现有依赖。向量通过现有 SQLAlchemy/psycopg 参数化 SQL 操作；无需新增 Python pgvector 包作为第一版前提。 |
| pypdf | 先保留旧管线兼容；所有解析收敛并通过回归后再删除，不能先删后修。 |
| 后端测试 | 优先标准库 unittest + 已有 httpx；不要求新增 pytest/队列/向量服务。 |

新增版本不凭本文猜测；实施时锁文件并检查许可证、支持平台与安装体积。未读取到可核实的在线文档正文，本次不把第三方的具体版本行为作为已验证结论。

## 四、模块拆分与模块职责定义

### 4.1 所有权与依赖矩阵

“依赖”指公共应用服务调用，不是数据库外键；共享 DTO 放 contracts，不为方便而互相导入内部 repository。

| ID / 模块 | 职责及拥有的数据 | 依赖 | 被依赖 |
|---|---|---|---|
| M00 基础契约与数据治理 | DTO、错误、配置、模型定义、迁移、时钟、安全原语；不写业务策略 | 标准库/框架 | 全部模块 |
| M01 papers | 稳定论文、源文件、修订版、资产字节存储、安全下载、原件读取 | M00 | parse/visual/检索输入/pipeline/API |
| M02 parse | MinerU/PyMuPDF 适配，Page/Block/页码映射，原始解析产物 | M00、M01 | visual/evidence/claims/retrieval/pipeline |
| M03 visual | Media 识别、原件裁剪/缩略图、提取表格公式、来源显示策略 | M00、M01、M02 | evidence/claims/scene/API |
| M04 evidence | Anchor、引用匹配、关系、校验报告、发布闸门和审计 | M00、M02、M03、M05 | claims/graph/scene/QA/pipeline/evaluation |
| M05 ai | 供应商传输、结构验证、模型快照、预算、embedding | M00 | claims/evidence/retrieval/scene/QA/pipeline |
| M06 claims | Claim、结构概览、方法步骤的提取与逐句状态，不写源文 | M00、M02、M03、M04、M05 | scene/graph/QA/pipeline/evaluation |
| M07 retrieval | 原文 chunk、中文词法、可选向量、融合、可选重排 | M00、M02、M03、M05 | QA/pipeline |
| M08 graph | 有出处的节点/边与孤立/争议状态，不猜支持边 | M00、M04、M06 | pipeline/API |
| M09 scene | 场景、讲解、字幕、可追溯的媒体关联 | M00、M03、M04、M05、M06 | pipeline/API |
| M10 qa | 检索式问答、逐句校验、流式事件、缓存与预置 QA | M00、M04、M05、M06、M07 | pipeline/API |
| M11 pipeline | DB 队列、阶段、租约、角色工具、预算、原子发布协调 | M00–M10、M12 | API/worker/seed |
| M12 evaluation | 代理指标、golden 评测、人工标注导入与报告 | M00、M04、M06；其他产物以 DTO 输入 | pipeline/API |
| M13 API 兼容层 | 旧 DTO 投影、新资源接口、权限、流式传输 | 各公共服务 | 前端/旧消费者 |
| M14 前端工作台 | 八视图、原件组件、读者定位、流式 QA、移动证据入口 | M13 HTTP 契约 | 用户 |
| M15 演示与交付 | 真实/模拟 seed、Compose、备份恢复、契约/E2E 验收 | M00/M01/M11/M13/M14 | 运维/演示 |

### 4.2 边界规则

1. M05 不依赖业务模块；M04 接收共享 `StatementDraft`，不调用 M06，从而避免 claims ↔ evidence 循环。
2. M12 接收 `EvaluationInput`，不调用 pipeline，不触发生成。M11 显式收集输入后调用评估。
3. 模块命令负责其产物短事务；跨模块发布仅由 M11 调用 M01 的发布命令，按 revision 完整性条件与版本 CAS 检查。
4. `Asset` 的字节/hash/path 归 M01，`Media` 的图表/公式语义及裁剪关系归 M03；M02 不直接写 Figure/Claim。
5. 原文字段只允许解析模块写入；生成模块禁止把摘要写回 Page/Block。旧 `Section.body` 可继续承载兼容内容，但新增 origin 必须揭示其性质。
6. 新业务公开入口仅为第五章服务方法和 HTTP API；repository、模型与辅助函数是私有实现，不形成跨模块调用契约。

## 五、完整接口契约规格

### 5.1 全局规则与基础类型

以下为规格版本 `rl.contract/1`。记法：`name:type` 必填，`name?:type` 可省略，`T|null` 可显式为空，`T[]` 有序数组，`A+B` 合并结构。未声明的新增输入字段拒绝，历史宽松请求单独适配；新输出不使用业务含义不明的 `Any`。时间统一 UTC ISO8601，前端按用户时区显示。

| 类型 | 定义 |
|---|---|
| `Id` | UUID 字符串；后端可用数据库 UUID 或 String(36)。不从图号/列表下标生成。 |
| `PaperId / JobId / LegacyEvidenceId` | 正整数，保留已有 int 身份；新记录也不得改成 UUID 响应。 |
| `RevisionId / AssetId / AnchorId / BlockId / MediaId / StatementId` | 各自语义的 Id，不可混用；revision 内引用必须校验同 paper/source。 |
| `PublicClaimId` | 非空 ASCII 字符串，长度 ≤32；旧 `claim_07` 保留，只在 `(paper_id,revision_id)` 内唯一。 |
| `Hash` | 小写 SHA256 十六进制 64 位；用于字节一致性，不当语义真实性证明。 |
| `Score` | 有限 float，0..1；NaN/Infinity 拒绝；未评估必须 null，不能默认 0.95。 |
| `Scope` | `{paper_id:PaperId,revision_id:RevisionId}`；HTTP 不指定 revision 时在请求开始固定当前 published/readable revision，整个请求不漂移。 |
| `Point / Rect / Quad` | `[x,y]` / `[x0,y0,x1,y1]` / 四点数组；归一化到 0..1，有限数，矩形 x0<x1/y0<y1，四边形不自交。 |
| `Origin` | `source_extraction / generated / synthetic`。 |
| `ArtifactRef` | `{kind:claim|statement|section|method_step|scene|graph_node|graph_edge|answer,id:string}`；注册表验证类型、scope、存在性。 |
| `Warning` | `{code:string,message:string,stage:string|null}`，message 不含 token、文件绝对路径或论文大段原文。 |
| `PageResult<T>` | `{items:T[],next_cursor:string|null,total:int}`；limit 默认 50、最大 200；cursor 不透明且绑定 scope/筛选。 |
| `CallContext` | `{request_id:Id,scope:Scope|null,deadline_at:datetime,cancel_token:CancelToken,model_snapshot:ModelSnapshot|null,budget:Budget}`；CancelToken 为仅进程内的 `is_cancelled()->bool` 端口，不序列化。 |
| `Budget` | `{max_calls:int,max_input_tokens:int,max_output_tokens:int,max_wall_ms:int,max_repair_rounds:int}`；非负，repair 最大 2。费用只记录实际 usage，缺价格时不猜费用。 |
| `DomainError` | `{code:ErrorCode,message:string,retryable:bool,request_id:Id,field_errors:FieldError[],retry_after_ms:int|null}`；`FieldError={path:string,reason:string}`。 |

错误码与 HTTP：`NOT_FOUND:404`，`INVALID_INPUT:422`，`CONFLICT/REVISION_MISMATCH/AMBIGUOUS_REFERENCE:409`，`UNSUPPORTED_MEDIA:415`，`PAYLOAD_TOO_LARGE:413`，`FORBIDDEN:403`，`RATE_LIMITED:429`，`DEPENDENCY_UNAVAILABLE:503`，`DEADLINE_EXCEEDED:504`，`INTERNAL_ERROR:500`。`CANCELLED` 用于已建立的流/任务终态，不使用非标准 499 响应。`EVIDENCE_REJECTED` 是可预期业务结果，放 ValidationReport/Answer 中，不映射为 500。

服务函数失败抛类型化 DomainError；可用降级结果不抛依赖异常，而在 output 的 warnings、capabilities、quality 中明确表达。HTTP 旧错误保留 `detail` 字符串或 FastAPI 422 detail 数组，可加 `error:DomainError`；已有明确 400 行为保留，不全量改 422。禁止把完整外部报错回传用户。

### 5.2 文档、页码、块与定位契约

| 结构 | 完整字段 |
|---|---|
| `PaperRecord` | `{id,slug:string≤64,title:string,source_mode:demo|real|upload,provenance_class:synthetic|source_document,status:pending|processing|ready|failed,published_revision_id:RevisionId|null,readable_revision_id:RevisionId|null,created_at,updated_at}`。metadata 扩展沿用 PaperOut 的作者/摘要等字段。 |
| `SourceDocument` | `{id:Id,paper_id,sha256:Hash,asset_id:AssetId,byte_size:int,mime:"application/pdf",page_count:int,source_url:string|null,original_filename:string|null,acquisition:upload|url|seed,created_at}`；source_url 去除访问凭据，不能持久化 token query。 |
| `Revision` | `{id:RevisionId,paper_id,source_document_id:Id|null,kind:source|legacy|synthetic,state:staging|readable|published|superseded|failed,parser_name:string,parser_version:string,normalizer_version:string,prompt_version:string,model_snapshot_id:Id|null,artifact_digest:Hash|null,quality:complete|partial|source_only,warnings:Warning[],created_at}`。legacy/synthetic 可无源，不能产生 verified 原文事实。 |
| `Page` | `Scope+{id:Id,pdf_page_index:int≥0,pdf_page_no:int≥1,page_label:string|null,label_status:verified|candidate|ambiguous|unknown,width_pt:float>0,height_pt:float>0,rotation:0|90|180|270,cropbox_pdf:[float,float,float,float],text:string,text_origin:source_extraction,preview_asset_id:AssetId|null,extraction_quality:text|ocr|image_only|empty}`。 |
| `PageLabelMapping` | `Scope+{id:Id,page_label:string,pdf_page_index:int,method:pdf_metadata|printed_ocr|manual,status:verified|candidate|ambiguous,source_block_ids:BlockId[],confidence:Score|null,review_id:Id|null}`；允许标签重号，不设标签唯一。 |
| `Block` | `Scope+{id:BlockId,page_id:Id,ordinal:int,kind:heading|paragraph|caption|table|equation|image|header|footer|page_number|other,text:string,origin:source_extraction,anchor_id:AnchorId|null,media_id:MediaId|null,section_path:string[],raw_ref:RawRef,language:string,content_hash:Hash}`。图像块无文本可为空。 |
| `RawRef` | `{asset_id:AssetId,record_path:string,native_id:string|null,bbox_values:float[]|null,bbox_units:pixel|point|normalized|unknown,coordinate_frame:string|null}`；record_path 是受控解析索引，不是可执行表达式。 |
| `CoordinateTransform` | `{raw_to_canonical:float[9],canonical_to_pdf_unrotated:float[9],adapter_version:string}`；3×3 仿射/齐次矩阵，可逆，写入经过实际 PDF 旋转/CropBox 测试的值，不假定 MinerU 某固定单位。 |
| `Anchor` | `Scope+{id:AnchorId,source_document_id:Id,precision:region|page,segments:AnchorSegment[],transform:CoordinateTransform|null,raw_ref:RawRef|null,created_at}`。 |
| `AnchorSegment` | `{page_id:Id,pdf_page_index:int,page_label:string|null,rect:Rect|null,quads:Quad[],block_ids:BlockId[],quote_spans:QuoteSpan[]}`；page-only 必须 rect=null/quads=[]。 |
| `QuoteSpan` | `{block_id:BlockId,start_cp:int≥0,end_cp:int>start_cp,source_text:string,match_method:exact|normalized,normalizer_version:string|null}`；边界是 Unicode code point，半开区间；source_text 必须等于原 Block 的该切片。 |
| `NavigationTarget` | `Scope+{anchor_id:AnchorId,segment_index:int≥0}`；前端不可用 section kind/fig_no 代替它。 |
| `NavigationResult` | `{target:NavigationTarget,status:region_highlighted|page_opened|unavailable,reason:string|null}`；只有区域实际渲染完成才能报 region_highlighted。 |

统一坐标系为“已应用旋转、可见 CropBox 的正向页面，左上角原点、右/下为正、宽高归一化”。Page.width_pt/height_pt 是该正向页面尺寸；cropbox_pdf 保留原 PDF 坐标用于变换。阅读器依照同一 viewport 做正逆变换，不通过 CSS 猜偏移。矩阵计算必须由适配器结合实际版本验证，不在本文伪造通用公式。

所有物理页面都入库，包括空白/纯图页。PDF 内索引 0-based 是唯一位置主键；兼容 `page` 与 `page_no` 始终投影为 `pdf_page_index+1`，印刷页只放 page_label。legacy 无法确认物理页时保留旧值为 `legacy_page` 扩展、canonical anchor 为空，兼容 page 输出 0 表示未知；新 UI 禁止把 0 转成第一页。

`p.1587` 先作为印刷页候选查映射；存在多个映射即 ambiguous，不猜全局固定偏移。只有唯一且已验证映射可定位页面，但仍不能仅凭同页建立语义支持关系。页码人工修订以审计记录派生新解析 revision，不原位修改已发布 Anchor。

### 5.3 资产与图表公式契约

| 结构 | 完整字段 |
|---|---|
| `Asset` | `{id:AssetId,paper_id,revision_id:RevisionId|null,sha256:Hash,mime:string,byte_size:int,width_px:int|null,height_px:int|null,kind:source_pdf|parser_raw|crop|thumbnail|page_preview|extracted_html|synthetic_svg,url:string,created_at}`；url 为后端受控资源地址，不暴露磁盘路径。 |
| `Media` | `Scope+{id:MediaId,kind:figure|table|equation|page_preview,original_label:string|null,legacy_no:int|null,caption:string,anchor_ids:AnchorId[],original_asset_ids:AssetId[],thumbnail_asset_id:AssetId|null,extracted:ExtractedMedia|null,provenance:MediaProvenance,excluded:bool,exclusion_reason:string|null}`。 |
| `MediaProvenance` | `{representation:pdf_crop|mineru_crop|extracted|synthetic,source_document_id:Id|null,source_sha256:Hash|null,raw_asset_id:AssetId|null,transform:crop|resize|none,renderer_version:string|null,verification:source_bound|unverified|synthetic}`；resize 资产可用于预览，原件打开使用非缩略版本。 |
| `ExtractedMedia` | `{table_html:string|null,table_cells:TableCell[],latex:string|null,equation_label:string|null,origin:"source_extraction",warnings:Warning[]}`；table_html 是不可信提取 HTML，不预设已经安全。 |
| `TableCell` | `{row:int≥0,col:int≥0,rowspan:int≥1,colspan:int≥1,text:string,is_header:bool,anchor_id:AnchorId|null}`；保留完整数据，不截断内容。 |
| `MediaViewPolicy` | `{default_mode:original|extracted|synthetic|unavailable,original_asset_ids:AssetId[],fallback_page_ids:Id[],label:string,warnings:Warning[]}`；真实 source 缺原图不允许返回 synthetic。 |
| `MediaLinkCandidate` | `{media_id:MediaId,via_anchor_ids:AnchorId[],method:explicit_block_ref|caption_ref|same_page|legacy_regex,score:Score|null,reason:string}`；候选不等于已验证链接。 |

同一张图的子图可以共享父图资产但有不同 Media/Anchor；跨页表格是一个 Media 配多个有序 Anchor/Asset。原始编号与兼容整数编号分离，`图 2(a)`、`表 S1`、`(3)` 不强制变整数。兼容编号在该 revision 内唯一并持久化，GET 不重编。

MinerU crop 只有能确认来自同一 PDF 字节且关联到正确页/区域，才标 source_bound；不能验证区域时可作为“解析器提取图”查看，不能叫精确原件或伪造 Anchor。页截图不作为缺失图号的填充。示意 SVG 仅来源于受控 seed，需禁止主动内容；真实来源模式永不回退示意 SVG。

### 5.4 Evidence-first、断言与生成产物

| 结构 | 完整字段 |
|---|---|
| `StatementDraft` | `Scope+{id:StatementId,claim_id:PublicClaimId,text:string,kind:fact|inference|quote|transition,citations:CitationCandidate[],qualifiers:string[]}`；claim_id 为公开陈述身份，讲解/QA 的新事实也必须注册，不允许仅有孤立文本。 |
| `CitationCandidate` | `{block_id:BlockId,proposed_quote:string,media_id:MediaId|null}`；LLM 只能选择已提供的块 ID，不允许生成可信页码/坐标。 |
| `EvidenceRecord` | `Scope+{id:Id,legacy_id:LegacyEvidenceId|null,claim_id:PublicClaimId,source_document_id:Id,anchor_id:AnchorId,source_page:int≥1,source_region:AnchorSegment[],source_text:string,quote_spans:QuoteSpan[],media_ids:MediaId[],confidence:Score|null,confidence_method:string|null,locator_status:exact|page_only,support_status:supports|contradicts|insufficient|unreviewed,validation_id:Id}`。source_text 由服务端原文拼接，拼接规则保留分段边界；source_page 为首个 segment 的物理页，其余页保留在 source_region。未能定位者仅保留 CitationCandidate，不创建假的 EvidenceRecord。 |
| `ValidationReport` | `Scope+{id:Id,statement_id:StatementId,locator_valid:bool,quote_valid:bool,scope_valid:bool,semantic_status:supports|contradicts|insufficient|unreviewed,numeric_status:pass|fail|not_applicable|unreviewed,qualifier_status:pass|fail|unreviewed,decision:verified|inference|contested|unverified|rejected,evidence:EvidenceRecord[],reasons:ValidationReason[],assessor:rule|model|human,assessor_version:string,confidence:Score|null,created_at}`。 |
| `ValidationReason` | `{code:missing_source|wrong_scope|quote_mismatch|ambiguous_page|coordinate_missing|unsupported_entailment|numeric_mismatch|qualifier_missing|contradiction|budget_exhausted|external_unavailable|passed,message:string,block_ids:BlockId[]}`。 |
| `VerifiedStatement` | `StatementDraft+{validation:ValidationReport,evidence_ids:Id[],origin:generated|source_extraction,display_class:verified_fact|attributed_quote|inference|unverified|transition}`；保留候选引用只作审计，公开展示依赖 evidence_ids。 |
| `ClaimRecord` | `Scope+{id:Id,legacy_id:int|null,claim_id:PublicClaimId,statement_id:StatementId,type:RESULT|METHOD|LIMITATION|CONTEXT,status:verified|inference|contested|unverified|rejected,rationale:string,evidence_ids:Id[],confidence:Score|null,visibility:exhibit|answer_only}`；QA 新陈述默认 answer_only，不污染六展项的断言列表。 |
| `Binding` | `Scope+{id:Id,from:ArtifactRef,to:ArtifactRef|SourceRef,relation:supports|contradicts|illustrates|mentions,method:explicit_block_ref|caption_ref|verified_claim_join|manual|legacy_candidate,validation_id:Id|null,state:verified|candidate|rejected,reason:string,score:Score|null,created_at}`。 |
| `SourceRef` | `{kind:evidence|media|anchor|block,id:Id}`；多态目标必须存在、同 scope，禁止任意字符串链接。 |
| `ArtifactText` | `{text:string,spans:StatementSpan[]}`；完整覆盖所有非空白文字，禁止摘要正文之外的“无引用副文案”。 |
| `StatementSpan` | `{start_cp:int,end_cp:int,statement_id:StatementId}`；不重叠、按序，所指 statement 文本与切片一致。 |
| `SectionRecord` | `Scope+{id:Id,heading:string,kind:string,source_block_ids:BlockId[],anchor_ids:AnchorId[],summary:ArtifactText,key_points:ArtifactText[]}`。章节 heading 若为原文拷贝绑定 block；生成标题纳入 statement。 |
| `MapArtifact` | `Scope+{id:Id,items:MapItem[]}`；`MapItem={id:Id,kind:problem|method|result|limitation,text:ArtifactText,claim_ids:PublicClaimId[],anchor_ids:AnchorId[]}`。 |
| `MethodStepRecord` | `Scope+{id:Id,order:int,label:ArtifactText,detail:ArtifactText,phase:string|null,claim_ids:PublicClaimId[],media_ids:MediaId[],binding_ids:Id[]}`。 |

事实发布条件：同源同版本、引文存在、物理页明确、语义支持成立、涉及数字/单位/比较对象/适用条件的检查通过。坐标未知但页和引文正确时可以展示“页级依据”，不能说“精准定位”；如果产品配置要求该展项必须区域级，则降为待核验。confidence 仅是校验强度/模型评分，必须记录方法，不宣称概率校准。

`quote` 只能展示“论文原文如此表述”，不等于系统验证了现实科学真伪。`inference` 必须显式标推断并绑定依据；没有依据的候选陈述显示待核验或隐藏，不进入事实区。`transition` 只允许不含实质主张的衔接语，通过规则/人工白名单控制，不能用此类别绕过事实检查。

核验流程顺序固定：范围/身份 → 原文精确或可回溯规范化匹配 → 页/区域 → 数字/单位/条件 → 语义支持 → decision。规范化允许空白、连字等已定义转换，必须带回原始 offset map；模糊相似只产生候选，不伪造精确 quote。OCR 来源保留 OCR 标记，存在疑似识别错误时回看图片或降低状态。

所有生成的 map、方法步骤、图谱标签、scene、narration、QA 事实句均使用 ArtifactText/VerifiedStatement，不只保护 Claim 页面。历史伪造 evidence 不自动迁成 verified；无原件的 synthetic 明确不参与真实论文质量指标。

### 5.5 图谱、场景与讲解

| 结构 | 完整字段 |
|---|---|
| `GraphArtifact` | `Scope+{id:Id,nodes:GraphNodeRecord[],edges:GraphEdgeRecord[]}`。 |
| `GraphNodeRecord` | `{id:Id,kind:problem|method|experiment|claim|evidence|limitation,label:ArtifactText,claim_id:PublicClaimId|null,evidence_id:Id|null,anchor_ids:AnchorId[],status:verified|inference|contested|unverified}`。 |
| `GraphEdgeRecord` | `{id:Id,source:Id,target:Id,relation:supports|contradicts|illustrates|depends_on|mentions,label:ArtifactText,binding_ids:Id[],status:verified|candidate}`；端点必须在该图内。 |
| `SceneRecord` | `Scope+{id:Id,order:int,title:ArtifactText,kind:string,summary:ArtifactText,step_ids:Id[],statement_ids:StatementId[],claim_ids:PublicClaimId[],binding_ids:Id[],media_ids:MediaId[],narration:NarrationRecord}`。 |
| `NarrationRecord` | `{script:ArtifactText,tts_text:ArtifactText,subtitle_cues:SubtitleCue[],audio_url:string|null}`；无新增音频服务时 audio_url=null，不生成假链接。 |
| `SubtitleCue` | `{id:Id,start_ms:int|null,end_ms:int|null,text:ArtifactText}`；无真实时间轴时两时间都 null，禁止猜时间却标同步字幕。 |
| `PresentationArtifact` | `Scope+{id:Id,scenes:SceneRecord[],warnings:Warning[]}`。 |

Scene 涉及媒体的生成路径只能为“scene 的已验证 statement → Claim/Evidence → verified Binding → Media”；图号/印刷页字符串仅作 legacy_candidate。明确的原文“见图 X”也先解析候选，再验证该图确实说明当前句，不用同页全部图表填满。没有关联就显示无已验证媒体，不能生成看似合理的链接。

### 5.6 AI 与检索契约

| 结构 | 完整字段 |
|---|---|
| `ModelSnapshot` | `{id:Id,provider:"dashscope",base_url:string,chat_model:string,embedding_model:string|null,embedding_dimension:int|null,capability_version:string,temperature:float,created_at}`；不含密钥，密钥服务端即时解析。 |
| `ModelCapabilities` | `{model:string,purposes:(chat|embedding)[],json_schema:bool|null,json_object:bool|null,streaming:bool|null,embedding_dimension:int|null}`；null 是未知，不凭模型名猜支持。 |
| `ChatMessage` | `{role:system|user|assistant,content:string}`；论文内容总在不可信资料边界，不当 system 指令。 |
| `CompletionRequest<T>` | `{messages:ChatMessage[],output_schema:SchemaRef<T>,max_output_tokens:int,temperature:float,model_snapshot:ModelSnapshot}`；SchemaRef 为版本化受控 Pydantic 类型名，不接受用户任意 schema。 |
| `CompletionResult<T>` | `{value:T,usage:Usage,model:string,mode:json_schema|json_object,attempts:int,warnings:Warning[]}`；`Usage={input_tokens:int|null,output_tokens:int|null,elapsed_ms:int}`。 |
| `EmbeddingBatch` | `{model:string,dimension:int,vectors:float[][],input_hashes:Hash[],usage:Usage}`；数量/顺序与输入一致，每项长度相同、有限，空间按 model+dimension+normalization_version 隔离。 |
| `Chunk` | `Scope+{id:Id,block_ids:BlockId[],anchor_ids:AnchorId[],text:string,section_path:string[],media_ids:MediaId[],content_hash:Hash,token_estimate:int,embedding_space:string|null}`。 |
| `RetrievalRequest` | `{scope:Scope,query:string,top_k:int=5,mode:lexical|hybrid="hybrid",max_context_tokens:int=6000,rerank:bool=true}`；top_k 范围 1..20。 |
| `RetrievalHit` | `{chunk_id:Id,block_ids:BlockId[],anchor_ids:AnchorId[],media_ids:MediaId[],text:string,lexical_score:float|null,vector_score:float|null,rrf_score:float,rerank_score:float|null,rank:int}`。 |
| `RetrievalResult` | `{scope:Scope,hits:RetrievalHit[],mode_used:lexical|hybrid,warnings:Warning[],elapsed_ms:int}`。 |
| `IndexResult` | `{scope:Scope,chunk_count:int,vector_count:int,embedding_space:string|null,status:ready|lexical_only|failed,warnings:Warning[]}`。 |

AIClient 按 json_schema → json_object 回退，但两者都必须 Pydantic 验证及语义 gate。schema 错误和 read timeout 只在预算内重试；401/403 不盲重试。默认 QA 最多 4 次云调用、两轮候选修复以内；具体分配包含 embedding、检索重排和验证，不能每层重新拥有一份预算；不足时先跳过重排，再减少生成，不省略 gate。导入初始总预算为 60 次云调用、180000 输入/30000 输出 token、10 分钟墙钟，均配置化，不能保证所有论文在预算内完整生成。输入过长必须切块/预算分配，禁止无记录地截论文头尾。

检索只索引 source_extraction，不索引 AI 摘要作为一级支持证据。中文使用字符 bigram + 拉丁术语/数字/单位；保留章节、图题、表头及行列上下文。跨块引文明确多个 spans，不允许因 chunk overlap 重复计为多份独立证据。

Postgres 可用 pgvector；SQLite 必须词法可用，可选仅在小规模内做 CPU 精确向量余弦。云 embedding 不可用/模型维度变化时不中断已有索引和 QA；旧向量空间保持只读直到新空间完成。RRF 候选各路默认 30、总候选上限 60、RRF 常数 60；重排最多 12 候选，超过预算跳过。上述参数配置化并进入评测版本。

### 5.7 问答与流式协议

| 结构 | 完整字段 |
|---|---|
| `QARequest` | `{question:string长度1..2000,top_k:int=5,revision_id?:RevisionId}`；旧请求接受边界外 top_k 时先适配 clamp 到 1..20 并记录 warning，避免旧消费者因新增约束突然 422。 |
| `AnswerRecord` | `Scope+{id:Id,question:string,text:ArtifactText,statements:VerifiedStatement[],evidence:EvidenceRecord[],grounded:bool,confidence:High|Medium|Low,note:string,mode:generated|extractive|cached|abstained,model_snapshot_id:Id|null,usage:Usage,warnings:Warning[]}`。 |
| `QAStreamEvent` | `{event_id:int≥1,request_id:Id,type:meta|status|citation|sentence|final|error,data:QAEventData}`，根据 type 使用下列唯一数据结构。 |
| `QAMeta` | `{scope:Scope,answer_id:Id,deadline_at:datetime}`。 |
| `QAStatus` | `{stage:retrieving|reranking|drafting|verifying|degraded,message:string}`；只展示工作状态，不包含未验证答案或思维链。 |
| `QACitation` | `{evidence:EvidenceRecord}`。 |
| `QASentence` | `{statement:VerifiedStatement}`；verified_fact/attributed_quote 通过 gate 后发送，inference 明确标识，unverified 草稿不发送为答案。 |
| `QAFinal` | `{legacy:AskResponse,answer:AnswerRecord}`。 |
| `QAError` | `{error:DomainError,partial:bool}`；partial 只说明已发经验证片段存在，不代表完整 grounded。 |

现有非流式 `/qa` 与新增流式共用同一服务。`AskResponse.answer` 来自 final text，grounded 仅在答案包含实质内容、所有事实句有验证通过的证据且没有混入未支持推断时为 true；纯拒答 false，部分支持或推断为 false 并逐句标识。High/Medium/Low 是兼容评级，不映射为伪精确概率。

SSE 使用 `POST + fetch + ReadableStream`，不是只能 GET 的 EventSource；Content-Type 为 `text/event-stream`，每帧含 `id/event/data`，JSON 在 data 行，空行分隔。UTF-8 支持跨 chunk 解码；10 秒 heartbeat 用注释帧，不计事件序号。发送 citation 后才发送引用它的 sentence，最后恰有一个 final 或 error；不得二者同时出现。客户端断开触发取消并释放资源。

QA 流本版不承诺断线续传，不接受 Last-Event-ID；断线 UI 显示中断、重问开启新 request。final 只在整个 Answer 完成持久化后发送。终态前中断的有效片段可作审计，不能作为完整缓存结果。建立流前按普通 HTTP 返回错误；建立流后用 error 事件。30 秒硬 deadline 到达时可完成明确拒答/已有完整降级答案并 final，否则 error。

离线策略：同 revision 且 gate 版本仍有效的缓存 → 从原文返回明确署名的引用片段 → 拒答。禁止复用跨 revision 的缓存、用题库非空字符串判 grounded 或把摘要充当 source_text。预置题库同样是 QARecord，经同一 gate 生成。

### 5.8 持久任务、Agent 工具与事件

| 结构 | 完整字段 |
|---|---|
| `JobSpec` | `{paper_id:PaperId,revision_id:RevisionId|null,kind:ingest|reprocess|evaluate,source:SourceInput|null,review_ids:Id[],idempotency_key:string|null,model_snapshot:ModelSnapshot,budget:Budget}`。review_ids 默认空，非空只允许 reprocess，必须来自相同旧 scope。 |
| `SourceInput` | `{kind:stored,source_document_id:Id}` 或 `{kind:pending_upload,asset_id:AssetId}` 或 `{kind:url,url:string,title:string}`；URL 获取归后台阶段。 |
| `JobRecord` | `{id:JobId,paper_id,revision_id:RevisionId|null,state:queued|running|retry_wait|succeeded|partial|failed|cancelled,stage:Stage,progress:float0..1,attempt:int,lease_owner:string|null,lease_until:datetime|null,fence:int,cancel_requested:bool,error:DomainError|null,model_snapshot:ModelSnapshot,created_at,updated_at}`。 |
| `Stage` | `acquire|parse|normalize|media|index|claims|verify|exhibits|qa_bank|evaluate|publish`。 |
| `StageResult` | `{stage:Stage,status:succeeded|partial|failed|skipped,artifact_ids:Id[],artifact_digest:Hash|null,usage:Usage,warnings:Warning[],error:DomainError|null}`。 |
| `JobLease` | `{job_id:JobId,worker_id:string,fence:int,expires_at:datetime}`。 |
| `JobEvent` | `{event_id:int≥1,job_id:JobId,occurred_at:datetime,type:stage_started|stage_finished|tool_started|tool_finished|retry_scheduled|degraded|completed|failed|cancelled,data:JobEventData}`。 |
| `JobEventData` | `{stage:Stage,progress:float,message:string,tool:ToolName|null,artifact_ids:Id[],elapsed_ms:int|null,usage:Usage|null,error:DomainError|null}`；字段完整但不适用时为 null/[]。 |
| `ToolName` | `retrieve_blocks|get_blocks|get_media|validate_statement|submit_candidate`；不含任意 I/O 工具。 |
| `ToolCall` | `{id:Id,role:analyst|verifier|presenter,name:ToolName,args:ToolArgs}`。 |
| `ToolArgs` | retrieve_blocks 用 RetrievalRequest；get_blocks 用 `{scope,block_ids:BlockId[]}`；get_media 用 `{scope,media_ids:MediaId[]}`；validate_statement 用 StatementDraft；submit_candidate 用 `{statement:StatementDraft}`。 |
| `ToolResult` | `{call_id:Id,status:ok|rejected|error,payload:RetrievalResult|Block[]|Media[]|ValidationReport|StatementDraft|null,error:DomainError|null}`；由工具名唯一确定 payload 类型。 |
| `SupervisorDecision` | `{action:accept|retrieve_more|repair|abstain,statement_id:StatementId,reason_code:string,next_query:string|null}`；reason_code 为受控原因枚举，复用 ValidationReason.code。 |

工具权限：Analyst 可 retrieve/get/submit；Verifier 可 get/validate；Presenter 可 get_media，仅从输入读取已验证 statements。submit_candidate 只提交候选，永不发布。工具按 context Scope 再验参，禁止模型扩展检索到其他论文。

队列保证 at-least-once，不声称 exactly-once。唯一阶段键为 `(revision_id,stage,input_digest,algorithm_version)`；外部云重复调用可能仍发生，但幂等提交只能产生一份有效产物。Postgres 用行锁/跳过已锁行领取；SQLite 单 worker 用短事务条件更新。租约默认 60 秒、20 秒 heartbeat；每次提交校验 fence，过期 worker 不得写入。长外部调用由独立心跳维持，心跳不得复用业务 Session。

queued → running → succeeded/partial/failed/cancelled；running 遇瞬时故障进入 retry_wait 再回 running。最多三次阶段尝试且受总预算限制；下载/鉴权/格式错误按 retryable 区分。cancel_requested 后不再发新工具调用，进行中的网络调用尽力取消，未完成产物不发布。

仅解析完成可设置 readable_revision_id，允许用户看原件；生成产物全部过 gate 后可 published/complete；部分生成失败可 published/partial，未验证区块不作为事实。源资料获取失败则 failed；已有 published revision 保持可读。Job 外部状态兼容映射：queued→pending，running/retry_wait→running，succeeded/partial→done，failed/cancelled→failed，同时新增 state/quality/warnings 消除信息损失。

Job SSE 为 `GET /jobs/{id}/events`，支持 Last-Event-ID/after；同 job 的 event_id 严格递增，至少保留 7 天，可重复重放，客户端去重。先按序重放，再监听新事件；发现 cursor 早于保留范围返回 409 + 最小可用游标，客户端重新 GET job。event_id 永不因清理重置；重放到 completed/failed/cancelled 后关闭连接。

### 5.9 评估、复核与导出

| 结构 | 完整字段 |
|---|---|
| `MetricValue` | `{value:float|null,unit:ratio|percent|count|ms|tokens,numerator:float|null,denominator:float|null,sample_size:int,method:string,status:measured|proxy|not_evaluated}`。 |
| `EvaluationInput` | `{scope:Scope,statements:VerifiedStatement[],media:Media[],bindings:Binding[],answers:AnswerRecord[],navigation_checks:NavigationCheck[],golden:GoldenSet|null}`。 |
| `NavigationCheck` | `{anchor_id:AnchorId,page_correct:bool,region_iou:Score|null,latency_ms:int}`。 |
| `GoldenSet` | `{id:string,version:string,source_hashes:Hash[],claims:GoldenClaim[],questions:GoldenQuestion[],anchors:GoldenAnchor[]}`。 |
| `GoldenClaim` | `{id:string,scope:Scope,text:string,expected_support:supports|contradicts|insufficient,acceptable_block_ids:BlockId[]}`。 |
| `GoldenQuestion` | `{id:string,scope:Scope,question:string,answerable:bool,required_points:string[],acceptable_block_ids:BlockId[]}`。 |
| `GoldenAnchor` | `{id:string,scope:Scope,expected_page_index:int,expected_rect:Rect|null,source_label:string}`。 |
| `EvaluationReport` | `Scope+{id:Id,version:string,overall_score:float|null,metrics:MetricEntry[],golden_id:string|null,computed_at:datetime,warnings:Warning[]}`；`MetricEntry={name:string,value:MetricValue}`，指标名来自下述固定集合。 |
| `ReviewRequest` | `{scope:Scope,target:ArtifactRef|SourceRef,decision:confirm|reject|correct_page_label,reason:string,corrected_page_index:int|null,page_label:string|null,expected_validation_id:Id|null}`。 |
| `ReviewRecord` | `{id:Id,request:ReviewRequest,reviewer:string,created_at:datetime,applied_revision_id:RevisionId|null,job_id:JobId|null}`；reviewer 从认证上下文取，不能信任请求自报身份。 |
| `EvidenceExport` | `{schema_version:"rl.contract/1",scope:Scope,source_sha256:Hash|null,claims:ClaimRecord[],statements:VerifiedStatement[],evidence:EvidenceRecord[],media:Media[],validations:ValidationReport[],generated_at:datetime}`；资产仅列清单，不内嵌论文全文/PDF/base64。 |

固定指标：`source_asset_coverage`、`anchor_page_accuracy`、`anchor_region_hit_rate`、`quote_exact_rate`、`support_precision`、`support_recall`、`unsupported_fact_escape_rate`、`unanswerable_refusal_rate`、`answerable_false_refusal_rate`、`qa_first_verified_ms`、`qa_total_ms`、`ingest_ms`、`input_tokens`、`output_tokens`、`recovery_success_rate`。无分母/null 数据返回 not_evaluated，不当 0/100；百分比只转换一次。

自动流水线只可报告可直接测量项或 proxy；support precision/recall 等必须有标注集才叫 measured。候选 Claim 与 golden 一对一匹配，不能一个命中撑起多个 TP。金标数据集至少覆盖中文、双栏、旋转、跨页表、扫描件、缺证与矛盾。只在包含人工真值的核心指标均可测时计算 overall_score：100×(0.4 support_precision + 0.2 quote_exact_rate + 0.2 anchor_page_accuracy + 0.2 unanswerable_refusal_rate)；否则 canonical null，旧 overall_score 为 0 并标 not_evaluated。该加权分是产品评测约定，不是科学可信度概率。

人工复核不直接改旧版本事实：confirm/reject 写不可变审计并触发校验新 revision；correct_page_label 必须提供 page_label、有效 physical index 和 reason。M04.review 只保存记录，初始 applied_revision_id/job_id 均为 null；M13 再调用 M11.enqueue，以 `review:{review_id}` 为幂等键、JobSpec.review_ids 传入复核记录，响应投影带 job_id，M04 不反向调用 pipeline。重复提交同 scope/target/expected_validation_id/decision/reason 的复核返回同记录；入队失败返回 503 并保留待执行记录，重试只补入队。

M11 创建派生 revision，读取复核 DTO；页码修订通过 M02.apply_page_overrides 应用，语义复核作为新 gate 输入保留 human assessor 及原 validation ID，不无条件信任原模型结果。完成后 M11 调用 M04.mark_review_applied，仅追加应用结果，不改 ReviewRequest。旧发布版本保持直至新 revision 完成，旧导出仍可复核。需要源文件权限的导出部署由使用方控制，本文不承诺任何具体论文授权。

### 5.10 模块公共函数签名

统一签名采用 `service.method(inputs, ctx:CallContext) -> Output`；内部实体读取使用 scope，除明确无状态纯函数外均校验存在性。表中多方法以分号分隔，均是必须实现的公开边界，不表示公开所有 repository。

| 模块 | 公开函数与输入 → 输出 | 主要失败/特殊行为 |
|---|---|---|
| M00 | `load_settings()->Settings`；`load_model_snapshot()->ModelSnapshot`；`check_schema()->SchemaStatus`；`require_admin(credential:string|null)->Actor` | 配置错误启动失败；迁移不符不得静默继续；Actor={name:string,is_admin:bool}，SchemaStatus={current:string,required:string,compatible:bool}。 |
| M01 | `create_paper(input:PaperCreate)->PaperRecord`；`store_source(paper_id,stream:ByteStream,metadata:SourceMetadata,ctx)->SourceDocument`；`fetch_source(paper_id,url:string,ctx)->SourceDocument`；`create_revision(paper_id,source_id:Id|null,kind,ctx)->Revision` | URL/文件校验，超限终止；字节只保存一次，不同步跑解析。 |
| M01 | `get_paper(paper_id)->PaperRecord`；`get_revision(scope)->Revision`；`put_asset(input:AssetWrite,stream:ByteStream,ctx)->Asset`；`open_asset(asset_id,range:ByteRange|null)->AssetRead`；`publish(scope,expected_revision:RevisionId|null,digest:Hash,quality,ctx)->PaperRecord` | open 重新检验所属论文访问权限；发布 CAS 防覆盖；只接受 gate 完整性清单。 |
| M01 | `get_metadata(paper_id)->LegacyPaperMetadata`；`list_papers(source_modes:(demo|real|upload)[]|null)->PaperRecord[]`；`get_source(scope)->SourceDocument`；`get_assets(scope,ids:AssetId[])->Asset[]` | 原件资产可 revision=null，但 paper 必须相同；无源 NOT_FOUND；批量查询不得逐资产开 Session。 |
| M02 | `parse(source:SourceDocument,ctx)->ParseResult`；`persist(scope,result:ParseResult,ctx)->ParseSummary`；`get_pages(scope,cursor:string|null,limit:int)->PageResult<Page>`；`get_blocks(scope,ids:BlockId[])->Block[]`；`resolve_page_label(scope,label:string)->PageResolution` | MinerU 失败返回带 warnings 的 PyMuPDF 结果；未知/多义返回 PageResolution，不选第一页。 |
| M02 | `get_page(scope,pdf_page_no:int)->PageContent`；`apply_page_overrides(scope,overrides:PageLabelOverride[],ctx)->ParseSummary` | 只修改 staging revision；源文件 hash 必须与被复核旧版一致；旧版 Anchor 不变。 |
| M03 | `build_media(scope,parsed:ParseSummary,ctx)->MediaBuildResult`；`get_media(scope,ids:MediaId[])->Media[]`；`list_media(scope,kind:Media.kind|null,cursor,limit)->PageResult<Media>`；`get_policy(media:Media)->MediaViewPolicy`；`ensure_page_preview(scope,pdf_page_no:int,ctx)->Asset` | 裁剪失败退页级；无资产不编造；无效坐标 INVALID_INPUT；页预览按 source hash/页/渲染参数幂等缓存，独立于语义 revision，不改已发布事实。 |
| M04 | `validate(draft:StatementDraft,ctx,review:ReviewRecord|null=null)->ValidationReport`；`save_report(report,ctx)->ValidationReport`；`get_evidence(scope,ids:Id[])->EvidenceRecord[]`；`get_anchor(scope,id:AnchorId)->Anchor` | gate 失败为 report；错误版本拒绝；保存时复查 source hash/引用关系。review 仅受信编排器传入，校验同源派生关系及原 validation；人工确认不能跳过引文/身份检查，也不能确认已修改的陈述。 |
| M04 | `resolve_legacy(scope,refs:LegacyRef[])->ResolutionReport`；`bind(input:Binding,ctx)->Binding`；`get_bindings(scope,from:ArtifactRef)->Binding[]`；`review(input:ReviewRequest,actor:Actor,ctx)->ReviewRecord`；`export(scope,claims:ClaimRecord[],statements:VerifiedStatement[],media:Media[])->EvidenceExport` | legacy 候选不可自动 verified；review 需 admin/CAS；导出由 API 收集 DTO 传入，M04 不调用 M06，避免循环。 |
| M04 | `get_reviews(scope,ids:Id[])->ReviewRecord[]`；`mark_review_applied(review_id:Id,new_scope:Scope,job_id:JobId,ctx)->ReviewRecord` | 必须同 paper/同 source；追加应用结果且幂等，不能改原 request；旧 applied 结果冲突时报 CONFLICT。 |
| M05 | `complete<T>(request:CompletionRequest<T>,ctx)->CompletionResult<T>`；`embed(texts:string[],snapshot:ModelSnapshot,ctx)->EmbeddingBatch`；`get_capabilities()->ModelCapabilities[]`；`set_chat_model(model:string,actor,ctx)->ModelSnapshot` | 全局预算共享；供应商 schema 不可用回退并验证；不允许 embedding-only 模型设为 chat。 |
| M06 | `extract(scope,block_ids:BlockId[],ctx)->ClaimDraftBatch`；`verify_and_store(batch:ClaimDraftBatch,ctx)->ClaimBuildResult`；`build_structure(scope,ctx)->StructureArtifact`；`list_claims(scope)->ClaimRecord[]`；`get_claim(scope,claim_id)->ClaimRecord` | draft 永不直接作为 SUPPORTED；生成文字全部注册 statements。 |
| M06 | `get_structure(scope)->StructureArtifact`；`get_statements(scope,ids:StatementId[])->VerifiedStatement[]`；`register_statement(draft:StatementDraft,visibility:exhibit|answer_only,ctx)->ClaimRecord` | 注册只建立 unverified 身份；verify_and_store 在短事务保存最终状态。scene/QA 新陈述先注册再校验，拒绝绕过注册直接插入 evidence。 |
| M07 | `index(scope,ctx)->IndexResult`；`retrieve(request:RetrievalRequest,ctx)->RetrievalResult` | 空检索是 hits=[] 非异常；向量/重排失效返回词法结果与警告。 |
| M08 | `build(scope,claims:ClaimRecord[],ctx)->GraphArtifact`；`get(scope)->GraphArtifact` | 找不到现成图返回空图带明确生成状态，由 HTTP 扩展传递；不存在论文 404。 |
| M09 | `build(scope,structure:StructureArtifact,claims:ClaimRecord[],ctx)->PresentationArtifact`；`get(scope)->PresentationArtifact` | 无依据仅空场景/原文模板；禁止生成假 linked，GET 不调 LLM、不写库。 |
| M10 | `answer(scope,request:QARequest,ctx)->AnswerRecord`；`stream(scope,request,ctx)->AsyncIterator<QAStreamEvent>`；`build_bank(scope,questions:string[],ctx)->AnswerRecord[]` | 无证据是 abstained 结果；非流式/流式共享 final gate；缓存命中重新核版本。 |
| M11 | `enqueue(spec:JobSpec,ctx)->JobRecord`；`get_job(job_id)->JobRecord`；`claim_next(worker_id:string,ctx)->JobLease|null`；`heartbeat(lease,ctx)->JobLease`；`run_stage(lease,stage:Stage,ctx)->StageResult` | lease/fence 过期 CONFLICT；无工作 null；不在 API handler 运行全管线。 |
| M11 | `cancel(job_id,actor,ctx)->JobRecord`；`retry(job_id,actor,ctx)->JobRecord`；`events(job_id,after:int)->AsyncIterator<JobEvent>`；`dispatch(call:ToolCall,ctx)->ToolResult`；`decide(reports:ValidationReport[],ctx)->SupervisorDecision[]` | retry 创建新任务，引用可复用产物，不改旧终态；工具超权拒绝；流保留规则见 5.8。 |
| M12 | `compute(input:EvaluationInput,ctx)->EvaluationReport`；`get(scope)->EvaluationReport`；`run_golden(input:EvaluationInput,ctx)->EvaluationReport` | get 不计算/不写；未评估返回显式 not_evaluated 报告；不存在论文 404。 |
| M13 | `to_legacy_paper`、`to_legacy_claim`、`to_legacy_graph`、`to_legacy_presentation`、`to_legacy_answer`、`to_legacy_evaluation`，精确输入/输出签名见下段 | 输入为对应 canonical 产物及 scope 只读快照，输出 5.11 对应旧 DTO，不允许运行时 Any。 |
| M14 | `resolveMediaPolicy(media,assets:Asset[])->MediaViewPolicy`；`navigate(target:NavigationTarget)->Promise<NavigationResult>`；`startQA(scope,request,onEvent:(QAStreamEvent)->void)->AbortController`；`watchJob(job_id,onEvent:(JobEvent)->void)->Unsubscribe` | 取消清理 fetch/订阅；失效 target 显示 unavailable；Unsubscribe 为无参 void 函数。 |
| M15 | `seed_catalog(mode:synthetic|real,ctx)->SeedReport`；`verify_release(profile:sqlite|compose)->ReleaseReport` | 模拟与真实分开幂等；真实 seed 不要求 LLM 健康才能读取原件。 |

补充输入/输出完整定义：

- `Settings={database_url:string,data_dir:string,max_upload_bytes:int,max_download_bytes:int,allowed_source_hosts:string[],public_deployment:bool,admin_token_configured:bool,job_lease_seconds:int,qa_deadline_ms:int,mineru_enabled:bool}`；其他已有配置继续保留，不在 Settings 中暴露密钥。
- `PaperCreate={title:string,source_mode:demo|real|upload,provenance_class:synthetic|source_document,idempotency_key:string|null}`；`SourceMetadata={original_filename:string|null,source_url:string|null,acquisition:upload|url|seed}`。
- `ByteStream` 是可关闭的异步 bytes 迭代器；`ByteRange={start:int≥0,end_inclusive:int|null}`；`AssetWrite={paper_id,revision_id:RevisionId|null,kind:Asset.kind,mime:string,width_px:int|null,height_px:int|null}`；`AssetRead={asset:Asset,stream:ByteStream,total_size:int,range:ByteRange|null}`。
- `ParseResult={scope:Scope,source:SourceDocument,pages:Page[],blocks:Block[],anchors:Anchor[],label_mappings:PageLabelMapping[],media_candidates:ParsedMediaCandidate[],raw_asset_ids:AssetId[],parser_name:string,parser_version:string,warnings:Warning[]}`；parse 的 ctx.scope 必填且须对应 source，不能偷偷创建另一 revision。
- `ParsedMediaCandidate={kind:Media.kind,original_label:string|null,caption:string,anchor_ids:AnchorId[],raw_ref:RawRef,extracted:ExtractedMedia|null,embedded_asset_id:AssetId|null,excluded:bool,exclusion_reason:string|null}`。
- `ParseSummary={scope,page_count:int,block_ids:BlockId[],anchor_ids:AnchorId[],media_candidates:ParsedMediaCandidate[],raw_asset_ids:AssetId[],quality:complete|partial|source_only,warnings:Warning[]}`；`PageResolution={status:resolved|ambiguous|unresolved,candidates:PageLabelMapping[]}`。
- `PageLabelOverride={review_id:Id,source_sha256:Hash,page_label:string,pdf_page_index:int}`；只影响新版本映射，重复标签必须保留原本的歧义信息。
- `MediaBuildResult={scope,media:Media[],warnings:Warning[]}`；`LegacyRef={text:string,page:int|null,region:string|null}`；`ResolutionReport={scope,resolved:SourceRef[],candidates:MediaLinkCandidate[],unresolved:LegacyRef[],warnings:Warning[]}`；resolved 仅表示定位已解出，不表示支持已验证。
- `ClaimDraftBatch={scope,drafts:StatementDraft[],warnings:Warning[]}`；`ClaimBuildResult={scope,claims:ClaimRecord[],statements:VerifiedStatement[],warnings:Warning[]}`；`StructureArtifact={scope,sections:SectionRecord[],map:MapArtifact,method_steps:MethodStepRecord[]}`。
- M13 的公共适配签名固定为 `to_legacy_paper(paper:PaperRecord,metadata:LegacyPaperMetadata,revision:Revision|null)->PaperOut`；`to_legacy_claim(claim:ClaimRecord,statement:VerifiedStatement,evidence:EvidenceRecord[])->ClaimOut`；`to_legacy_graph(graph:GraphArtifact,statements:VerifiedStatement[])->GraphOut`；`to_legacy_presentation(presentation:PresentationArtifact,media:Media[],evidence:EvidenceRecord[],statements:VerifiedStatement[])->PresentationOut`；`to_legacy_answer(answer:AnswerRecord)->AskResponse`；`to_legacy_evaluation(report:EvaluationReport)->EvaluationOut`。
- `LegacyPaperMetadata={subtitle:string,authors:string[],year:int,domain:string,abstract:string,tags:string[],map_summary:Record<string,string>,pdf_url:string,method_steps:LegacyMethodStep[]}`，LegacyMethodStep 定义见 5.11。详情组装由 HTTP 查询层处理，不把可变 ORM 实例穿过适配层。
- `SeedReport={paper_ids:PaperId[],job_ids:JobId[],skipped_keys:string[],warnings:Warning[]}`；`ReleaseReport={profile:string,checks:ReleaseCheck[],passed:bool}`；`ReleaseCheck={name:string,status:pass|fail|skipped,evidence_path:string|null,message:string}`。

### 5.11 现有 HTTP API 与旧结构：逐项保留

以下 17 项覆盖当前 routes.py 的 GET/POST 路由，不改 URL。路径 PaperId/JobId 必须正整数；claim_id 按原字符串解析；GET 不触发 seed、LLM 或计算写库。存在论文但产物未完成可返回原空结构并新增 generation_status；不存在论文统一 404。

| 方法与 URL | 输入 | 成功 200 输出 | 特定错误/兼容要求 |
|---|---|---|---|
| GET `/api/health` | 无 | `{status:string,demo_mode:bool,version:string}` | 可新增 dependencies/warnings，但健康检查不做计费云调用。 |
| GET `/api/demo` | 无 | `DemoPaperListItem[]` | 保留真实 curated 与 synthetic 集合，新增 provenance_class 供分组。 |
| POST `/api/demo/load` | `{slug:string}` | `PaperOut` | 未找到 404；seed 不在 GET 中做。 |
| GET `/api/models` | 无 | `{models:string[],active:string}` | 可新增 capabilities；models 保留字符串数组。 |
| POST `/api/models` | `{model:string}` | `{active:string}` | 非允许 chat 模型 422；受限部署未认证 403；原子持久化，不改变进行中 job 快照。 |
| POST `/api/papers/from-url` | `{url:string,title?:string=""}` | `{paper_id:int,status:"processing",slug:string,job_id?:int}` | 入队后返回，不等待下载；不合法 URL 保留 400，超限/安全失败在任务可见；最终仍是同 paper_id。 |
| GET `/api/papers` | 无 | `PaperOut[]` | 默认不改成分页 envelope；可选查询过滤不影响无参行为。 |
| GET `/api/papers/{paper_id}` | 可选 revision_id | `PaperDetail` | 默认仍含旧字段与媒体 base64；新增新 UI 不依赖此重响应。 |
| GET `/api/papers/{paper_id}/claims` | 可选 revision_id | `ClaimSummary[]` | 仅 exhibit claims；空是合法，不代表一直加载。 |
| GET `/api/papers/{paper_id}/claims/{claim_id}` | 可选 revision_id | `ClaimOut` | 同 scope 查找，否则 404；可访问 answer_only 引用的 claim。 |
| GET `/api/papers/{paper_id}/graph` | 可选 revision_id | `GraphOut` | 不得自动把 unsupported 变 supports。 |
| GET `/api/papers/{paper_id}/presentation` | 可选 revision_id | `PresentationOut` | figure_refs/table_refs 仍为兼容整数列表，由持久关联投影。 |
| POST `/api/papers/{paper_id}/qa` | 旧 AskRequest / QARequest | `AskResponse` | 依赖失效可返回有标记的降级/拒答 200；不能产出假证据。 |
| GET `/api/papers/{paper_id}/evaluation` | 可选 revision_id | `EvaluationOut` | 读取缓存；无评估显式状态，不临时计算伪分。 |
| POST `/api/papers/upload` | multipart `file` | `{paper_id:int,job_id:int,status:"pending"}` | demo_mode=true 保留现有 400；流式限额 413，非 PDF 415；写入 pending 后自动可领取。 |
| POST `/api/papers/{paper_id}/process` | 无必填 body | `{paper_id:int,job_id:int,status:"running"}` | 幂等复用当前活动 job；新增真实 state，避免把排队误当实际执行。无论文 404。 |
| GET `/api/jobs/{job_id}` | 无 | `{job_id:int,stage:string,stage_label:string,status:string,paper_id:int}` | 新增 state/progress/error/quality/warnings/revision_id；不改变旧字符串类型。 |

旧类型字段完整清单，除已有可选字段外不省略：

```text
PaperOut = id:int, slug:string, title:string, subtitle:string,
  authors:string[], year:int, domain:string, abstract:string, tags:string[],
  source_mode:string, status:string, map_summary:object, pdf_url:string,
  method_steps:LegacyMethodStep[]
DemoPaperListItem = slug,title,subtitle,domain:string, year:int,
  tags:string[], abstract,accent,source_mode:string
PaperDetail = PaperOut + sections:SectionOut[], figures:FigureOut[],
  tables:TableOut[], method_steps:LegacyMethodStep[],
  pages:{page_no:int,text:string}[], accent:string
SectionOut = heading,kind:string, page:int, summary,body:string, key_points:string[]
FigureOut = fig_no:int, caption:string, page:int, glyph_svg,image_b64:string,
  importance,description:string
TableOut = table_no:int, caption:string, page:int, content:JSONScalar[][],
  table_html,key_finding:string
EvidenceOut = id?:int|null, page:int, region,region_type,text,quote:string,
  confidence:float
ClaimSummary = claim_id,statement,type:string, confidence:float,
  status:string, evidence_count:int
ClaimOut = id?:int|null, claim_id,statement,type:string, confidence:float,
  status,rationale:string, evidence:EvidenceOut[]
GraphOut = nodes:{id,label,kind:string,props:object}[],
  edges:{id,source,target,label:string}[]
SceneOut = order:int, title,kind,summary:string, steps:LegacyMethodStep[],
  evidence_refs:JSONValue[], figure_refs:int[], table_refs:int[],
  narration:{script?:string,tts_text?:string,subtitle?:string,audio_url?:string},
  linked:EvidenceOut[]
PresentationOut = scenes:SceneOut[]
AskRequest = question:string(1..2000), top_k:int=5
AskResponse = answer:string, grounded:bool, confidence:string,
  evidence:EvidenceOut[], note:string
EvaluationOut = overall_score:float, metrics:object
LegacyMethodStep = id:string,label:string,phase?:string,detail?:string,
  text?:string,figure_ref?:int,color?:string
JSONScalar = string|number|bool|null
JSONValue = JSONScalar|JSONValue[]|{string:JSONValue}
```

这是对新生成兼容输出的收敛规范。旧库中 `content/steps/evidence_refs/linked` 原本允许 Any，迁移适配器必须保留旧有效值或输出逐项迁移警告，不能以新 DTO 验证导致整个旧详情 500；legacy 快照保留原响应，canonical 明确未验证。前端 `content:string[][]` 与后端 Any 不一致，新增类型适配为 JSONScalar，单元格显示使用显式字符串转换，禁止执行内容。

旧 evidence.id 继续数字，新 ID 放 `evidence_id` 扩展；Claim 的 public claim_id 不等于 DB 主键。旧 confidence 无法表达 null 时投影 0 并新增 `confidence_assessed:false`；SUPPORTED 状态只投影 verified→SUPPORTED，其余→UNSUPPORTED，新增 verification_status 区分 contested/inference/unverified。不为“兼容”保留错误的 grounded=true。

所有旧 DTO 可加 `revision_id`、`provenance_class`、`anchor_id`、`media_id`、`statement_ids`、`verification_status` 等与对应 canonical 类型一致的字段。旧字符串图号引用保存在 `legacy_refs`，但不进入 verified linked。旧 Figure.image_b64 输出保持可读取格式并新增 image_mime；默认不悄悄改成 URL。PDF 地址统一为受控原件路由。

根 GET `/` 如已有服务元信息继续保留；HTTP/OpenAPI 快照必须在首次实现前由运行旧版本采集，本次静态审阅不冒充已冻结实际响应。

### 5.12 新增 HTTP API：严格类型与资源边界

除流/二进制资源外成功 200；所有 API prefix 为 `/api`。列表遵守 PageResult，revision_id 默认解析见 5.1，未知 revision 404，revision 与 paper 不一致 409。

| 方法与 URL | 输入 | 输出 | 错误/行为 |
|---|---|---|---|
| GET `/papers/{paper_id}/manifest` | revision_id? | `PaperManifest` | 不含全文、base64、原 HTML；服务端只读。 |
| GET `/papers/{paper_id}/document` | revision_id?；Range header? | PDF 字节，Content-Type application/pdf，Accept-Ranges bytes，ETag=源 hash | 合法范围 206，无效/多范围不支持时 416；无源 404；同源内联只读。 |
| GET `/papers/{paper_id}/pages` | revision_id?，cursor?，limit? | `PageResult<PageSummary>` | 只元数据，不一次返回全文。 |
| GET `/papers/{paper_id}/pages/{pdf_page_no}` | revision_id? | `PageContent` | 路径物理页 1-based；超范围 404。 |
| GET `/papers/{paper_id}/pages/{pdf_page_no}/preview` | revision_id? | 页预览图片字节，正确 MIME/ETag | 调用 M03.ensure_page_preview；有限分辨率、并发限制和超时；无源/越界 404，渲染暂不可用 503。PDF.js 失败时按需请求，不预生成整篇阻塞首页。 |
| GET `/papers/{paper_id}/media` | revision_id?，kind?，cursor?，limit? | `PageResult<Media>` | 仅默认返回未排除媒体，管理审计可查排除项。 |
| GET `/papers/{paper_id}/media/{media_id}` | revision_id? | `{media:Media,assets:Asset[],policy:MediaViewPolicy}` | 同 scope，否则 404/409。 |
| GET `/assets/{asset_id}` | Range?；无任意 path 参数 | 资产字节，正确 MIME/ETag/Content-Length | 原始 HTML/SVG 默认 attachment 或 text/plain；不可作为跨域主动页面。 |
| GET `/papers/{paper_id}/anchors/{anchor_id}` | revision_id? | `Anchor` | 不存在 404；无区域返回 page precision，不伪造矩形。 |
| GET `/papers/{paper_id}/evidence/{evidence_id}` | revision_id? | `{evidence:EvidenceRecord,validation:ValidationReport}` | 不串用 legacy numeric ID。 |
| GET `/papers/{paper_id}/statements` | revision_id?，ids:逗号分隔 Id，最多 100 | `{items:VerifiedStatement[]}` | 任一 ID 不属 scope 则整个请求失败，禁止静默省略造成对应错乱。 |
| GET `/papers/{paper_id}/exhibits` | revision_id? | `ExhibitBundle` | 中等体积正文，媒体 URL 引用，不含 base64；独立于 manifest 加载。 |
| POST `/papers/{paper_id}/qa/stream` | QARequest | SSE QAStreamEvent | 5.7 协议，不支持断线续传。 |
| GET `/jobs/{job_id}/events` | after?:int；Last-Event-ID? | SSE JobEvent | 两 cursor 同时给必须相等，否则 422；过期 409。 |
| POST `/jobs/{job_id}/cancel` | 无 body；管理认证 | `JobRecord` | 重复取消幂等；已完成返回原终态，不撤销发布。 |
| POST `/jobs/{job_id}/retry` | 无 body；管理认证 | `JobRecord` | 仅失败/partial/cancelled；活动任务冲突 409；返回新 job_id。 |
| POST `/papers/{paper_id}/reviews` | ReviewRequest，scope.paper_id 与路径一致 | `ReviewRecord` | 管理认证；reason 必填；过期 expected_validation_id 409。 |
| GET `/papers/{paper_id}/evidence-export` | revision_id? | `EvidenceExport`，Content-Disposition attachment | synthetic source_hash 为 null，明确标记；禁止悄悄导出源 PDF。 |

```text
PageSummary = Page 去掉 text，但保留 extraction_quality/preview_asset_id
PageContent = {page:Page,blocks:Block[],anchors:Anchor[]}
Capability = {name:pdf|text|media|claims|graph|presentation|qa|evaluation,
              state:ready|partial|pending|unavailable,reason:string|null}
PaperManifest = {paper:PaperOut,revision:Revision|null,
  provenance_class:synthetic|source_document,source:SourceDocument|null,
  page_count:int,section_index:{id:Id,heading:string,anchor_ids:AnchorId[]}[],
  media_index:{id:MediaId,kind:Media.kind,label:string|null,thumbnail_asset_id:AssetId|null}[],
  assets:Asset[],capabilities:Capability[],active_job:JobRecord|null,warnings:Warning[]}
ExhibitBundle = {scope:Scope,structure:StructureArtifact,
  claims:ClaimRecord[],statements:VerifiedStatement[],
  graph:GraphArtifact,presentation:PresentationArtifact,
  evaluation:EvaluationReport,capabilities:Capability[]}
```

PaperManifest.paper 保持 PaperOut 的字段类型，但此新接口中的 map_summary/method_steps 为空，由 exhibits 承载，避免重复大文本；旧详情接口不受影响。manifest.assets 只包含首批缩略图/源文档元数据，不包含原件字节。暂无可读 revision 时 manifest.revision/source 为 null、section/media 为空，exhibits 返回 409 CONFLICT 与 pending 原因；不能创建假的已发布 scope。

`exhibits` 体积对超长论文同样要预算，第一版限制生成规模而不截原文：默认 ≤40 个 exhibit claims、≤12 场景、≤30 方法步骤，超出保留候选不发布到展项，提示覆盖范围；原文/全部媒体不截断。调整限制写入配置版本。读取接口可用 revision ETag 缓存，不做每次现场重算。

### 5.13 前端公共边界与一致性

| 组件/Hook | Props/输入 | 输出/事件 |
|---|---|---|
| SourceMedia | `{media:Media,assets:Asset[],mode?:original|extracted,onOpen:(MediaId)->void,onNavigate:(NavigationTarget)->void}` | 统一来源标签和加载/失败状态；不得自行回退真实→synthetic。 |
| PdfReader | `{scope:Scope,document_url:string,initial_target:NavigationTarget|null,onLocated:(NavigationResult)->void}` | 动态加载 PDF；只渲染当前页邻近窗口；响应新 target 的序列号，旧完成回调作废。 |
| AnchorOverlay | `{anchor:Anchor,segment_index:int,viewport_width:number,viewport_height:number}` | 同一页面坐标覆盖；无区域时不画假框；保持不遮挡原文可读性。 |
| ExtractedTable/Formula | `{media:Media,onShowOriginal:(MediaId)->void}` | 清理后的提取视图；KaTeX trust=false、禁止危险宏，渲染失败显示可转原件的状态。 |
| CitationLink | `{evidence:EvidenceRecord,onNavigate:(NavigationTarget)->void}` | 展示“PDF 第 N 页 / 印刷页 label”，未知 label 不显示。 |
| EvidenceDrawer | `{scope:Scope,evidence_ids:Id[],open:bool,onClose:()->void}` | 桌面 rail 与移动抽屉共享内容/导航，不因断点隐藏核验能力。 |
| usePaperWorkspace | `{paper_id:PaperId}` | `{manifest:LoadState<PaperManifest>,exhibits:LoadState<ExhibitBundle>,refresh:()->Promise<void>}`。 |
| useEvidenceNavigation | `{scope:Scope}` | `{target:NavigationTarget|null,navigate:(NavigationTarget)->Promise<NavigationResult>}`。 |
| useJobEvents / useQAStream | 分别为 job_id；scope+QARequest | 返回 `{state:StreamState,events:对应事件[],error:DomainError|null,cancel:()->void}`；QA 另有 start(request)。 |

`LoadState<T>={status:idle|loading|ready|error,data:T|null,error:DomainError|null}`；`StreamState=idle|connecting|streaming|completed|failed|cancelled`。canonical 类型由 OpenAPI 校验/生成脚本同步 TS，旧 lib/types.ts 与 lib/api.ts 保留接口名和调用签名，新方法增量增加。

先请求 manifest 得到 revision，再并行获取同 revision 的 exhibits/所需页等，不能把不同 revision 的 claim/scene 混屏。任务完成后重新取 manifest、按新 revision 清理旧查询并加载所有相关展项，不仅刷新 claims/eval。空断言是已完成的空态。图/PDF/大表懒加载，取消 stale fetch，所有渲染回调核对请求序号。

首页真实/模拟分别分组、来源徽标明确；保留现有首页但不以首页美化代替工作台。方法动画是解释层，讲解文字高亮绑定 statement，不绑定数组下标；SourceMedia、旧 FigureImage/TableRender 在迁移期共享同一 sourcePolicy。

### 5.14 存储约束、迁移与安全契约

数据库必须落实而不只靠 prompt：

- 唯一约束：`(paper_id,revision_id,claim_id)`、`(revision_id,pdf_page_index)`、`(revision_id,legacy_fig_no)`/表号、`(job_id,event_id)`、阶段幂等键；slug ≤64。
- 所有跨表引用带 scope 校验；可表达的同 scope 关系采用复合 FK/唯一键；多态 Binding/ArtifactRef 通过统一 artifact registry 的复合外键校验，禁止悬空/跨论文边。
- 索引：paper 的 published/readable 指针、block `(revision_id,page_id,ordinal)`、evidence `(revision_id,claim_id)`、binding `(revision_id,from_kind,from_id)`、job `(state,lease_until)`、检索 scope/chunk。
- SQLite 开启 foreign_keys，每连接设置；并发配置采用 WAL/busy_timeout 并在本地测试；JSON 更新整体赋值或可追踪容器。Postgres 启用 pgvector 扩展失败只降级检索，不阻断原件读取。
- 原 PDF 与解析 raw、裁剪资产内容寻址；存储先写临时文件、hash 校验、原子 rename，再落引用。失败临时文件按 TTL 回收；禁止在数据库记录尚未发布时删除旧资产。
- 不对已发布版本做原位重解析；修正页码/坐标/验证产生新 revision。旧版本保持可读，删除/保留策略需另行明确授权，不在重构中隐式删除。

迁移序列：备份并统计 → 验证旧表结构后建立 Alembic baseline（不能无检查 stamp）→ 新增表/可空列 → 回填 legacy revision 与来源类别 → 有 PDF 的离线重解析/校验 → 双读对照 → 新 UI 切换 → 后续再停止旧写入。重复迁移幂等，失败回滚并报错；SQLite 重建表时测试 FK/索引/数据总量；Postgres 测试约束差异。历史 page 无法证明时 unverified，不按常量偏移批量“修正”。

发布回滚指切回旧应用读投影/旧发布 revision，不是破坏性 downgrade 删除新数据。上线前保留数据库和 backend-data 卷备份并实测恢复；若迁移尚未通过，服务 readiness 失败而非静默降级到未知 schema。

外部输入全部不可信：URL 限 http/https、拒凭据/私网/loopback/link-local/云元数据地址，逐次重定向重新检查 DNS/目标地址并限制跳数，防 DNS rebinding；默认公开部署用允许域名单，受控下载出口确保实际连接 IP 也校验，不能只在请求前解析一次。PDF 流式限体积、魔数及 PyMuPDF 可打开性检查，随机/内容寻址文件名，避免覆盖和路径穿越。

MinerU 必须处理与保存源文件相同字节：优先其受支持的上传流程；如使用远程 URL 必须能确认解析输入与 SourceDocument hash 相同，否则本地 PyMuPDF 降级。ZIP 只在专用目录解包，路径/展开总量/单项大小/数量受限，原始 JSON/HTML 永不当指令执行。

论文中的提示注入不得改变 system、角色、scope、工具白名单与预算；模型不能直接访问环境变量、文件系统或网络。日志默认只存 ID/hash/摘要错误，原文与模型输入在受控审计存储，配置保留期，禁止记录 token。

部署默认为单语料空间，不虚构多租户隔离能力；若开放公网，必须设置访问范围、上传限流/配额与管理认证。模型切换/复核/取消/重试用 X-Admin-Token 或同等服务端会话校验，token 不写 NEXT_PUBLIC_*。本地显式 `PUBLIC_DEPLOYMENT=false` 可保持旧无认证演示，不能把该模式暴露公网。

## 六、分模块开发任务清单

### 6.1 执行规则与依赖顺序

每个任务是可复制的独立委托块，须向编码模型同时提供 `docs/REFACTOR_SPEC.md` 和仓库。实现者只能改本模块及明确列出的集成入口；跨模块先使用第五章 DTO 和测试替身，不另造协议。不允许用空实现、mock 真实数据、删除旧字段或修改评分算法来通过验收。

先给现状补 characterization/契约测试，再实现。每个任务交付：变更文件清单、自动测试结果、降级样例、兼容差异说明。下面所有测试均为待实施验收，不是本次已通过的测试。

依赖顺序：M00 → M01/M05 → M02 → M03 → M04/M07 → M06 → M08/M09/M10/M12 → M11 → M13 → M14 → M15。M13 可先做旧接口快照，M14 可按契约用静态 fixtures 开发；不能先依赖未冻结字段。M04 与 M07、M08 与 M09 可各自并行，不交叉写文件。

发布分四个可回滚检查点：A 仅源文件/页码/原件及旧接口兼容；B 全局 Evidence Gate 与真实阅读器；C 可恢复 Agent 工作流与流式检索 QA；D 金标评测和竞赛演示。A/B 未通过不得先上线“多 Agent 演示”掩盖原件/证据错误。

### 6.2 M00：基础契约与数据治理

**任务委托：实现 ResearchLens 的公共 DTO、错误、配置与数据库迁移底座，不改业务规则。**

- 模块职责：拥有 `contracts/*`、`core/{config,db,errors,clock,security}`、新增 ORM 定义及 `migrations/*`；现有 `models.py` 和旧 schema 兼容保留。
- 遵守契约：第五章 5.1–5.9 的完整结构、5.10 的 M00 函数、5.14 存储约束；PaperId/JobId 保持 int，canonical ID 为 UUID 字符串，Scope 必须包含 paper_id/revision_id。
- 业务逻辑：先从实际旧库建立可验证 baseline，再增量迁移；不得无检查 stamp、捕获迁移失败后继续启动。实现 SQLite FK/WAL/busy timeout、Postgres 索引与复合约束；generated/source_extraction 分离、JSON 更新可追踪。
- 输入输出：配置 → Settings/ModelSnapshot；旧数据库 → 新版本数据库及迁移报告；服务错误 → DomainError；管理凭据 → Actor。不能把密钥放入快照和 API。
- 单元测试：字段边界、非法 ID/NaN/坐标拒绝；Scope 混用失败；错误响应保留旧 detail；配置缺失报明确错误。
- 集成验证：空库/有数据 SQLite、Postgres 各升级一次并重复执行；注入迁移失败验证原数据；FK、唯一键、slug 长度和 JSON 保存；备份恢复计数一致。
- 交付限制：不删除旧列，不全量重写现有业务 import；对无法回填的历史记录写 legacy/unverified，不猜页码。

### 6.3 M01：论文、原文件与资产存储

**任务委托：建立稳定 paper_id 与不可变源文件/修订版，统一上传、URL 和 seed 的数据入口。**

- 模块职责：`modules/papers/*` 管理论文、SourceDocument、Revision、Asset 字节；不执行 LLM、不解析论文内容。
- 遵守契约：5.2/5.3/5.10 的 M01 公共函数及 PaperCreate/SourceInput/ByteStream；source hash 必须对应实际保存 PDF，publish 使用 expected_revision CAS。
- 业务逻辑：内容寻址、临时文件原子发布、同名不覆盖；流式限体积/PDF 验证；URL 逐跳校验、限制重定向并防内网连接；下载在 worker 中执行。绝不通过删除 Paper 重导入。
- 输入输出：文件流或受控 URL + paper_id → SourceDocument；AssetWrite + 字节流 → Asset；AssetId/Range → AssetRead；完整 staging revision + digest → 发布指针切换。
- 单元测试：同名不同 PDF、相同 PDF、中文标题、slug 碰撞/长度；无权限路径、伪 PDF、体积超限、中断写入清理；Range 首尾/越界；跨 paper 资产访问。
- 集成验证：URL 返回 paper_id 与最终产物完全相同；断下载不影响旧 published；并发 publish 仅一个 CAS 成功；实际网络连接地址校验而非仅字符串黑名单。
- 交付限制：不把远程 URL 内容未经 hash 关联交给解析器；无源 synthetic 可以存在，但不得获得 source_bound 状态。

### 6.4 M02：MinerU/PyMuPDF 解析与页码坐标

**任务委托：收敛两条解析链路，保留完整原文、物理页、块、坐标、原始编号和解析审计产物。**

- 模块职责：`modules/parse/*`；现有 `services/mineru.py/parser.py` 仅作兼容代理，PyMuPDF 是统一失败降级。
- 遵守契约：5.2 Page/Block/Anchor/CoordinateTransform、5.10 ParseResult/ParseSummary 与 M02 函数；pdf_page_index 0-based，page_label 独立；原文唯一 origin=source_extraction。
- 业务逻辑：解析保存的同一份字节，正确等待 MinerU 批结果终态；ZIP 安全解包并识别嵌套路径；保留空白/纯图页、页码块、公式/表格/图标题与 bbox 单位；缺坐标就是 page-only。原始解析响应存只读 raw asset。
- 输入输出：SourceDocument + staging Scope → ParseResult；persist → ParseSummary；读取返回完整 Page/Block；印刷页查询返回 resolved/ambiguous/unresolved，不估计固定页差。
- 单元测试：双栏中文 reading order、标题跨页、PDF 旋转 90/180/270、非零 CropBox、空白页、纯图页、印刷页重复/罗马数字/1587；四角/裁剪 round-trip；Unicode offsets。
- 集成验证：伪 MinerU pending/done/failed/缺 ZIP/嵌套 ZIP；超时和 token 缺失触发 PyMuPDF；扫描件无 OCR 时图片可读但原文不可答；重试同版本不重复 page/block。
- 交付限制：不得填估计页码，不截断 source text；无法恢复旧证据区域需明确 unverified，不能伪造 bbox。

### 6.5 M03：原件媒体与提取表示

**任务委托：实现图、表、公式的原件资产与提取表示分离，统一所有视图的媒体来源策略。**

- 模块职责：`modules/visual/*` 管理 Media 语义与裁剪，Asset 字节经 M01 存储；不执行前端重绘冒充原件。
- 遵守契约：5.3 的 Media/MediaProvenance/ExtractedMedia/TableCell/MediaViewPolicy，5.10 M03 函数，3.4 八视图显示政策。
- 业务逻辑：优先从同源 PDF 坐标裁剪图表/公式，保存 mime/hash/尺寸/renderer_version；复用可核验 MinerU crop；保留原编号、跨页表有序资产、子图关系。整页只当 page_preview；提供按需幂等页预览供 PDF.js 失败兜底，限制分辨率/并发/超时；不凑数量、不重编原标签。
- 输入输出：ParseSummary → MediaBuildResult；Media → MediaViewPolicy；MediaId → 媒体、原件资产与提取 HTML/LaTeX。缩略图和原件分开，不将 base64 内嵌到 manifest。
- 单元测试：含 rowspan/colspan 的中文表、长单元格、超过 12×12 表格、公式编号/符号；多页表顺序；JPEG/PNG MIME；图题与图号不一致候选；误过滤可追溯。
- 集成验证：原件 hash 可追溯、裁剪坐标与 PDF 对齐；丢资产时页预览降级；真实论文无原图绝不出现 seed SVG；无效外部 HTML 仅作为不可信提取材料传递。
- 交付限制：不重新拟合图表数值，不把 HTML/KaTeX 标“原版”；不静默截断矩阵作为显示兜底。

### 6.6 M04：证据、绑定与事实发布闸门

**任务委托：实现全系统 Evidence Gate，使已验证事实、推断、争议和缺证内容有不可绕过的状态边界。**

- 模块职责：`modules/evidence/*`；拥有引用、Anchor 读取、ValidationReport、Binding、人工复核与证据清单导出；不依赖 claims 内部实现。
- 遵守契约：5.4 StatementDraft/EvidenceRecord/ValidationReport/Binding/ArtifactText，5.9 Review/Export，5.10 M04 函数；每个事实包含 claim_id/source_page/source_region/source_text/confidence，未知置信度必须标明未评估。
- 业务逻辑：验证 source/scope/hash、原文偏移、物理页、数字/单位/比较对象/条件、语义支持；引用由服务端从原文填充。同页/正则只能生成候选。仅 gate 通过才可 verified，定位成功不等于支持成立。
- 输入输出：StatementDraft + 可选受信 ReviewRecord → ValidationReport；旧字符串 → ResolutionReport；关系候选 → candidate/verified/rejected Binding；ReviewRequest → 审计记录；Scope + 调用方提供的 claims/statements/media DTO → EvidenceExport。复核仅适用于同源派生版且陈述未变，不跳过身份和原文检查。
- 单元测试：伪造 quote、AI 摘要当原文、跨论文 ID、错 revision、空证据高 confidence、同页不相关、fig_1/fig_10、印刷页歧义、数字/单位或“仅在...”被删；规范化匹配反映原始 offsets。
- 集成验证：无 LLM 时不自动通过语义 gate；原文署名引用可降级；manual review 不覆盖历史版本；导出有 hash/状态但无 PDF/base64；移动/桌面均能使用相同 Anchor。
- 交付限制：不得仅以 evidence 非空或模型自报置信度判 SUPPORTED；不得把模型推理过程当审计理由展示。

### 6.7 M05：AI 调用与模型治理

**任务委托：在现有 DashScope OpenAI 兼容 AIClient 上增加类型验证、预算、取消与模型快照，不替换供应商。**

- 模块职责：`modules/ai/*` 和旧 `services/ai.py` 适配，runtime 原子持久化；不包含 QA/解析/断言业务。
- 遵守契约：5.6 ModelSnapshot/Capabilities/CompletionRequest/EmbeddingBatch，5.1 Budget/CallContext，5.10 M05 函数。
- 业务逻辑：json_schema→json_object 后仍用同一 Pydantic schema 验证；HTTP 连接复用；读超时等可重试错误受统一 deadline/call budget 约束；401/403 不循环重试；运行中 job 模型不随 runtime 修改漂移。
- 输入输出：messages + SchemaRef + snapshot → CompletionResult<T>；texts → 有顺序/维度校验的 EmbeddingBatch；管理模型修改 → 新 ModelSnapshot。
- 单元测试：schema 不支持、错误 JSON、类型错、缺字段、合法 JSON 但语义非法留给 M04；read timeout、取消、预算耗尽；embedding 错序/维度变化/NaN；chat 误选 embedding-only 拒绝。
- 集成验证：runtime.json 并发写不破损、重启生效；API key 不出现在日志/响应；无服务明确 DomainError，不返回伪业务数据。
- 交付限制：不新增重型 Agent 框架，不实现 GPU embedding，不因增加多角色给每层重复发放预算。

### 6.8 M06：断言、结构概览与方法步骤

**任务委托：从原文块提取有来源的研究陈述，并生成逐句可追溯的结构/方法展项。**

- 模块职责：`modules/claims/*` 管理 Claim、VerifiedStatement、Section/Map/MethodStep 生成产物；调用 M04 gate，不直接修改 Page/Block。
- 遵守契约：5.4 ClaimRecord/StatementDraft/ArtifactText/SectionRecord/MapArtifact/MethodStepRecord；5.10 M06 函数；public claim_id ≤32、同 revision 唯一，MethodStep.id 必填。
- 业务逻辑：按章节分配原文预算而非只读头 14k/尾 7k；LLM 从 block_id 候选选引用，服务端补页；先候选，再 gate，再入已验证产物；结论保留数据集、指标、条件、局限。
- 输入输出：Scope + BlockId[] → ClaimDraftBatch → ClaimBuildResult；验证过的原文/断言 → StructureArtifact；列表默认 exhibit，不暴露 QA 临时陈述为展项。
- 单元测试：空论文/LLM 不可用；claim_id 碰撞；statement spans 完整覆盖；正文里 unsupported 不可通过 summary 泄漏；方法图关联不能靠猜图号；公式条件不能被摘要省略。
- 集成验证：同输入重复生成提交幂等；旧接口 ClaimSummary/Out 可投影；结构和方法说明中的每个事实可追到 source；源文本不被生成摘要覆盖。
- 交付限制：不为了填满展项捏造 claims，不将高 confidence 替代验证；生成规模受预算限制并报告覆盖情况。

### 6.9 M07：原文检索与可选向量融合

**任务委托：建立 CPU 可用、中文优先的原文检索底座，提升 QA 引用召回，不让 embedding 成为单点依赖。**

- 模块职责：`modules/retrieval/*`；拥有 Chunk、词法/向量索引、融合排序；不生成最终答案。
- 遵守契约：5.6 Chunk/RetrievalRequest/Hit/Result/IndexResult，5.10 M07 函数；检索必须限定 Scope；top_k 1..20、上下文预算与全局预算共享。
- 业务逻辑：中文 bigram、英文术语、数字和单位混合索引；保留表头/图题/方法章节上下文；RRF 融合、可选预算内 Qwen 重排；索引只读 source_extraction，不以 AI 摘要作一级依据。
- 输入输出：原文块/媒体 → IndexResult；query + scope → 有 block/anchor/media 的 RetrievalResult；服务失效输出 lexical_only/warnings。
- 单元测试：中文无空格、连字符技术词、公式/表格问句、空结果、重复 chunk 去重、不同论文相同语句、向量维度变化、嵌入超时；验证融合排序与参数版本。
- 集成验证：SQLite 仅词法可答；Postgres pgvector 启用/关闭结果均合法；新空间未完成不污染旧索引；记录 recall@k、耗时和重排增益，不能只测“有结果”。
- 交付限制：不引入本地 embedding 大模型/Elasticsearch，不将向量相似度当支持关系置信度。

### 6.10 M08：有据研究图谱

**任务委托：生成可审计的研究关系图，所有支持边和证据节点都能返回真实来源。**

- 模块职责：`modules/graph/*`；节点/边持久化及旧 GraphOut 投影所需数据，不执行 GET 时重建。
- 遵守契约：5.5 GraphArtifact/Node/Edge、5.4 Binding/ArtifactText、5.10 M08 函数；节点 ID 稳定、边端点同图同 scope。
- 业务逻辑：以已验证 claims/evidence/bindings 建图；supports/contradicts 与验证状态一致；不能对 UNSUPPORTED 统一连支持边；孤立/候选/争议节点保留明确状态。
- 输入输出：Scope + ClaimRecord[] → GraphArtifact；GET 返回持久化快照；节点 anchor/evidence ID 供统一导航。
- 单元测试：缺端点、跨 scope 边、重复 ID、无证据断言、矛盾证据、同 label 不同节点；所有实质标签必须 ArtifactText 有句级来源。
- 集成验证：GraphOut 旧 nodes/edges 字段可用；点击 evidence node 到正确原件区域；图布局计算留前端，GET 无 LLM/额外写操作。
- 交付限制：不把图谱本身称为论文原图，不新增跨论文知识库作为本次前提。

### 6.11 M09：讲解与场景媒体关联

**任务委托：从已验证陈述生成可同步原件的讲解场景，替换 GET 时正则猜测链接。**

- 模块职责：`modules/scene/*`；Scene/Narration/Subtitle 及媒体关系，不拥有原图字节。
- 遵守契约：5.5 SceneRecord/Narration/PresentationArtifact，5.4 ArtifactText/Binding，5.10 M09 函数和 5.11 SceneOut 兼容字段。
- 业务逻辑：只从验证过的 statements/claims 生成场景；scene→evidence→verified binding→media；讲解新增事实必须再次 gate；原始页码字符串只能候选，不作为 linked source_text。
- 输入输出：StructureArtifact + ClaimRecord[] → PresentationArtifact；旧输出 figure_refs/table_refs 为持久化兼容整数，canonical 以 media_id 驱动。
- 单元测试：仅 `p.1587`、中英图号、子图、表 S1、多图同页、无关联；同 caption 不同图；字幕/script 中遗漏来源；无音频时 audio_url/timecode 合法为空。
- 集成验证：涉及内容点击真实图表，讲解句点击原文；GET 查询批量化、不每 scene 开 Session；LLM 失败以原文引用或空态降级，不造新结论。
- 交付限制：不得生成假音频地址/时间轴，不从任意英文关键词挑同页不相干证据填 UI。

### 6.12 M10：检索问答与受控流式输出

**任务委托：用原文检索和句级验证替换现有先答后配引文 QA，提供兼容非流式和新增流式接口。**

- 模块职责：`modules/qa/*`；AnswerRecord、缓存、预置 QA 与事件序列；不依赖“全文摘要”推断 grounded。
- 遵守契约：5.7 QARequest/AnswerRecord/QAStreamEvent 的精确事件顺序与终态，5.10 M10 函数；旧 AskResponse 字段保持。
- 业务逻辑：retrieve→可选 rerank→draft→逐句 gate；先 citation 后 verified sentence，最后唯一 final/error；所有生成事实注册 claim_id，answer_only 不污染展项；不要把裸 token 作为已验证事实流出。
- 输入输出：Scope + question/top_k → AnswerRecord 或 async events；旧接口投影 final；缓存 key 含 source/revision/model/prompt/gate 版本，断线不假装可续传。
- 单元测试：不可回答题、只部分支持、诱导过度外推、矛盾、中文表格问答；题库无证据时 grounded=false；拒答和空答案不能 grounded=true；流 UTF-8 拆包、重复终态和断线取消。
- 集成验证：M05/M07 全失败仍可引用式降级或拒答；证据与输出句逐个对应；首进度/首验证句/总耗时分别测；同输入流式 final 与非流式语义和结构一致。
- 交付限制：不按“未出现拒答词”判 grounded；不得从 Section.summary 补造 source_text/confidence。

### 6.13 M11：持久管线、工作进程与有界 Agent

**任务委托：将上传、URL、真实 seed 收敛到同一个可恢复数据库任务状态机，并实现受控 Agent 工具循环。**

- 模块职责：`modules/pipeline/*`、`app/worker.py`；Job/Stage/Event、租约、预算、幂等、取消/重试和发布协调；保留旧 ingest/run_pipeline 签名适配。
- 遵守契约：5.8 JobSpec/Record/Lease/StageResult/JobEvent/ToolCall/Decision，5.10 M11 函数；任务 at-least-once、fence 提交、stage 幂等、公开状态兼容映射。
- 业务逻辑：一个 paper_id 贯穿全程；云 I/O 不占长事务；领取→心跳→阶段产物→短事务；source/readable/partial/published 分开；Supervisor 仅 accept/retrieve_more/repair/abstain，最多两轮，工具白名单强制 scope。
- 输入输出：JobSpec → JobRecord；worker → JobLease/StageResult；订阅 → 可重放 JobEvent；验证完整产物 → M01 发布。旧进程内 BackgroundTasks 只能唤醒 worker，不作为唯一执行保障。
- 单元测试：重复 enqueue/process、超时 lease、stale fence、worker 停止、模型快照不漂移、预算耗尽、工具越权、repair 超限、非 retryable 错误；取消后不能发布。
- 集成验证：SQLite 单 worker 和 Postgres 双 worker；任意阶段 kill/restart 不重复发布；旧版保持可读；Job SSE reconnect/游标过期/终态；调用数量和阶段 digest 可审计。
- 交付限制：不新增 Redis/Celery，不声称 exactly-once 云调用；worker 掉线不得永久 running，不靠重新删除论文恢复。

### 6.14 M12：真实评测与可审计指标

**任务委托：修复现有 benchmark 错误，建立代理统计与人工真值分离的质量/性能评测。**

- 模块职责：`modules/evaluation/*`、`backend/evals/benchmark.py`；GoldenSet、EvaluationReport 与缓存读取，不负责生成业务内容。
- 遵守契约：5.9 MetricValue/GoldenSet/EvaluationInput/Report、5.10 M12 函数；value=null 的未评估不可冒充 0/100；整体分数公式固定。
- 业务逻辑：修复重复乘百分比、None 运算、一对多匹配虚高、中文 token 与大小写混用；计算证据/定位/拒答/耗时指标时保留分子分母及版本，人工支持关系不能由 confidence 字段替代。
- 输入输出：版本化产物与 golden → EvaluationReport；GET 只返回已有报告/明确未评估；输出 baseline、改版、去掉检索/去掉 gate 的消融报告。
- 单元测试：空样本、无分母、全部拒答、全错/全对、一份预测匹配多个 gold、中文术语、混合量纲；citation_accuracy 最大 100 且只缩放一次。
- 集成验证：至少三篇真实中文论文及独立构造边界 PDF；每个标注可回到原文；训练/调参样本与最终评测样本区分；置信评分与人工支持 precision 分开展示。
- 交付限制：未经测量不得报告“提升 X%”；synthetic 不混入真实论文保真/引用准确率统计。

### 6.15 M13：REST 兼容与资源/事件接口

**任务委托：保留现有 17 个 API 的 URL 和旧响应类型，增加第五章定义的原件、定位、版本和流接口。**

- 模块职责：`api/*`、`schemas/adapters.py`；HTTP 参数验证、认证、错误、兼容投影和轻量聚合；不把业务规则复制进 routes。
- 遵守契约：5.10 M13 精确适配签名，5.11 全部旧路由/DTO，5.12 全部新增资源，5.1 错误及 5.7/5.8 两种 SSE。
- 业务逻辑：旧成功默认 200；from-url 快速入队、upload 流式限额、process 幂等；所有 GET 只读；新 manifest 不含全文/base64；单请求固定 revision；未知 paper 统一 404。
- 输入输出：旧 JSON/multipart → 原返回结构；canonical JSON → 严格 DTO；PDF/资产 → 正确 MIME/Range/ETag；stream → 规范 SSE。原文 HTML/SVG 不当主动页面发送。
- 单元测试：旧 17 路由逐项契约快照、默认字段/空数组/错误；optional 新字段不破坏 lib/api；不同 revision、非法 ID、Range/416、SSE cursor；管理 token 不泄漏。
- 集成验证：真实新导入保持同 ID；旧 demo/真实记录可读取；manifest 体积预算；GET 无 seed/LLM/commit；旧 base64 默认仍可用而新 UI 无需下载它。
- 交付限制：不改成全部 `/api/v2`，不把 200 全改 202，不用 Any 绕过新契约验证。

### 6.16 M14：八视图、原件阅读器与证据交互

**任务委托：保留 Next.js 工作台八视图，以统一来源组件、实际 PDF 阅读器和同版本导航修复展示与交互。**

- 模块职责：`components/source/reader/evidence/jobs`、现有 views、hooks、lib/api/types/contracts；旧 FigureImage/TableRender/MediaModal 调用同一 sourcePolicy。
- 遵守契约：3.4 视图政策，5.12 HTTP，5.13 Props/Hooks/状态机；NavigationTarget=scope+anchor_id+segment_index，只有实际绘制后才能报告 region_highlighted。
- 业务逻辑：react-pdf 动态加载、本地匹配 worker、邻页虚拟渲染；PDF 失败用页面图片；原件/提取/示意来源标记；DOMPurify 白名单；KaTeX 为提取解释模式，原编号不猜。桌面/移动都可查证。
- 输入输出：manifest→固定 revision 并行加载 exhibits；Media→统一原件弹层；Evidence→阅读器定位；Job/QA events→状态时间线和逐句引用；导出通过 evidence-export。
- 单元/E2E 测试：八视图真实/模拟/缺资产/错误 MIME；表头合并/公式编号；中文长文、移动抽屉、键盘与触屏；加载图片失败不循环；HTML 注入样例、SVG 主动内容拒绝。
- 浏览器验收：桌面与移动截图、旋转/CropBox/缩放的高亮位置；点击 fig_1 不打开 fig_10；页级无框不说已高亮；纯 PDF 页面非空；断线/取消/切论文 stale callback 不改当前屏。
- 性能验收：manifest 后首屏可操作，空 claims 不等待 100 秒；任务完成全部展项刷新到同 revision；不在首页加载 PDF.js/全量 base64；记录网络瀑布与 p95。
- 交付限制：不重做无关营销首页，不让动画/重绘替代原论文媒体；不在客户端生成可信页码/grounded 状态。

### 6.17 M15：演示数据、部署与验收交付

**任务委托：统一真实/模拟 seed、完成 SQLite/Compose 双环境部署，并建立可量化竞赛演示证据。**

- 模块职责：seed 入口、Compose/环境示例/README、后端与前端契约/E2E 总验收、备份恢复报告；不改各模块内部业务策略。
- 遵守契约：2.2 约束、2.3 指标、5.10 SeedReport/ReleaseReport、5.14 安全迁移；模拟 provenance_class=synthetic，真实 source_document 可追溯。
- 业务逻辑：真实三篇论文按源 hash/完整度幂等，不是仅看 slug 存在；失败重试不复用坏事务；MinerU/LLM 缺失仍保留原件读取。移除 GET 隐式 seed 写，改显式初始化任务。
- 输入输出：seed_catalog → PaperId/JobId 与跳过原因；Compose → frontend 3002/backend 8002、pgvector 与 backend-data 持久卷；verify_release → 有测试证据路径的 ReleaseReport。
- 单元测试：重复 seed、已有不完整论文、源 URL 变更、synthetic/real 混排标签；同 hash 不重复创建；模型配置/上传卷重启保留。
- 集成验证：SQLite 全链路、Compose 冷启动/健康检查、worker 重启恢复、数据库/资产卷备份恢复、MinerU/DashScope/embedding 分别断服务、内存/延迟预算。
- 竞赛验收：录制“原表核对→点击一句定位→质疑外推→显示拒答/条件→Agent 修正记录→导出证据清单”闭环；并列展示现版基线与改版测值及样本数，未测项明确未测。
- 交付限制：不新增 GPU/重型服务；不泄露 token；不把示意论文计入真实验证效果，不以截图代替可运行入口。

### 6.18 最终验收与停止条件

按以下顺序验收，不允许只凭“页面能打开”宣告重构完成：

1. **契约**：现有 17 API 回归通过，新 API/DTO/事件 schema 与 TS 一致，所有旧数据可以读取或明确提示待迁移。
2. **P0**：每个原件标签可追溯源 hash；表/公式默认原件；真实缺图不会变示意；注入与加载失败安全降级。
3. **P1**：人工样本验证物理页/区域/图表/引文一致；重复印刷页明确歧义；页级定位没有假的高亮成功提示。
4. **事实闸门**：八视图全部生成事实句有 claim_id 与真实证据；无证据、不支持或矛盾内容不作 verified_fact；不以模型自信代替验证。
5. **工程**：统一管线、稳定 ID、短事务、重启恢复、幂等、取消、版本一致；SQLite 和 Postgres 都完成验证。
6. **P2**：流式 QA 有经验证的逐句引用，Agent 工具/预算/失败可观测，任务不是一次生成后伪造时间线。
7. **价值与性能**：有固定数据集、基线、失败样本、延迟/调用费用记录；竞赛主张与实际测量一一对应。

任何一项未过都保留明确未完成状态。本文交付止于分析和实施规格；未编写业务实现，也未声称上述验收已经通过。
