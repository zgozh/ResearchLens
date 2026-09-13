# ResearchLens · AI 科研视界

> **让一篇论文从「文档」变成「可验证、可演示、可交互的科研成果」**

第二届「庆园杯」人工智能创新应用大赛 · 主题三（开放创新探索）参赛作品。

ResearchLens 把一篇科研论文自动转换成**证据驱动的可交互科研展项**：
论文结构 → 核心方法 → 实验结果 → 证据链 → 分镜讲解 → 可点击研究图谱 → 证据问答 → 自动评测。

**核心创新是 Evidence-first（证据优先）**：任何 AI 生成的内容都必须绑定
`claim_id / source_page / source_region / source_text / confidence`；
拿不到证据的内容不许当作「事实」展示，宁可如实标注「本条暂无证据」。
这正是它区别于普通「论文总结工具 / AI 文案生成器」的地方 —— **可核验，而不是看起来像**。

---

## 🚀 30 秒跑起来（Docker，推荐）

```bash
git clone git@github.com:zgozh/ResearchLens.git
cd ResearchLens
cp .env.example .env          # 至少填 LLM_API_KEY；建议再填 MINERU_TOKEN
docker compose up --build     # 等价命令 docker-compose up --build 亦可
```

| 入口 | 地址 |
|---|---|
| 前端界面 | **http://localhost:4002** |
| API 文档（FastAPI Swagger） | **http://localhost:8002/docs** |
| 健康检查 | **http://localhost:8002/api/health** → `{"status":"ok",...}` |

四个容器（端口均可改，见下表「配置项」）：

| 服务 | 宿主端口 | 作用 |
|---|---|---|
| `frontend` | 4002 | Next.js 14 standalone（容器内 3000） |
| `backend` | 8002 | FastAPI（容器内 8000）；**启动时自动跑 Alembic 迁移 + schema 校验**，失败即 readiness 失败，不静默降级 |
| `worker` | 不发布 | 后台执行论文 ingest 流水线（下载 / 解析 / 抽取） |
| `db` | 不发布 | pgvector/pg16，数据落在命名卷 `pgdata` |

> ⚠️ **改端口后必须重建前端**：`NEXT_PUBLIC_API_URL` 是**构建期**注入进浏览器 bundle 的。
> 改了 `.env` 的 `BACKEND_PORT` 之后要 `docker compose build frontend && docker compose up -d`，
> 否则页面仍会去请求旧端口。

---

## 📦 首次启动你会看到什么（干净克隆后的真实行为）

数据库是空的，但**启动时会自动填两部分，你不需要手工做任何事**：

| 来源 | 数量 | 需要 Key 吗 | 说明 |
|---|---|---|---|
| **内置示例论文**（`source_mode=demo`） | 3 篇 | **完全不需要** | 项目**自绘原创**并预置结构化 IR（章节/断言/证据/图谱/分镜/问答题库全部齐备），入库即可点。首次访问 `GET /api/papers` 时幂等写入，8 个视图立刻可演示 |
| **真实中文论文自举**（`source_mode=real`） | 3 篇 | 建议配 | 后端启动时后台线程自动**入队**《软件学报》（开放获取）3 篇；由 `worker` 真实下载 PDF → 解析 → 抽取。**没有 LLM Key 也能入队**，只是内容质量按降级路径产出 |

3 篇内置示例（自绘原创，非真实论文，版权自有）：

| slug | 领域 | 标题 |
|---|---|---|
| `slimseg-net` | 计算机视觉 | SlimSeg-Net: An Efficient Cross-Attention Network for Real-Time Medical Image Segmentation |
| `netguard` | 网络空间安全 | NetGuard: Graph Contrastive Detection of Zero-Day Lateral Movement from Host Telemetry |
| `learnflow` | 教育 AI | LearnFlow: A Knowledge-Graph Tutor that Personalizes Adaptive Practice from Mistake Patterns |

3 篇自举真实论文（《软件学报》正式出版、开放获取）：

| 论文 | 链接 |
|---|---|
| 基于 Haar 小波域指标自适应选择载体的 JPEG 隐写 | <https://www.jos.org.cn/josen/article/pdf/5281> |
| 数据驱动的移动应用用户接受度建模与预测 | <https://www.jos.org.cn/josen/article/pdf/6106> |
| 基于软件度量的 Solidity 智能合约缺陷预测方法 | <https://www.jos.org.cn/josen/article/pdf/6550> |

### 所以：**别的真实论文要你自己导入**

自举的只有上面这 3 篇。除此之外的任何论文（arXiv / 期刊 / 你自己的稿子）都需要你自己导入，
两种方式，都在界面上：

1. **粘贴公开 PDF 网址** → 上传页把上述 3 个《软件学报》链接做成了示例，点一下就能测；
2. **上传本地 PDF**（默认上限 40MB，`MAX_UPLOAD_MB` 可调）。

导入是**真跑完整链路**（不是查缓存）：下载 PDF → MinerU/PDF 解析 → 归一化 → 图表裁剪 →
向量索引 → LLM 抽取断言 → 证据校验 → 问答题库 → 自动评测 → 发布。
实测 **1～4 分钟/篇**（本机实测：未配 MinerU 走 PyMuPDF 约 1 分钟；配 MinerU 后约 3～4 分钟），
期间进度**实时**显示在论文页上，完成后图谱 / 讲解 / 评测 / 图表**自动上屏，无需手动刷新**；
`worker` 是**单进程串行**处理，所以 3 篇自举论文是排队依次跑完的。

**自举论文的产出边界（如实说明）**：这 3 篇真实论文的任务会以 `partial` 收尾 ——
不是失败，而是每一处降级都写进了阶段结果里：章节超出上下文预算会被均匀取样截断
（`section_truncated` / `budget_truncated`，断言覆盖不全）、没有已验证陈述的章节
只呈现空场景而不编内容（`scene_without_verified_statement`）、协议校验发现数值对不上
会走修复（`supervisor_decision: repair`）。另外**真实论文没有预置题库**
（`qa_bank: skipped`，理由是"不生成假问答"），所以证据问答页没有预置问题 —— 自己提问照常可用。

> 这也是为什么项目里**没有「演示模式」开关**：产品只有一条链路。
> 没配 Key 时是**运行期降级**（`has_llm=False` → 抽取式作答），不是另一种模式。

---

## ⚙️ 配置项（`.env`）

| 变量 | 默认 | 作用 |
|---|---|---|
| `LLM_API_KEY` | 空 | **最重要**。阿里云百炼 DashScope 的 API-KEY（[申请入口](https://bailian.console.aliyun.com/)）。留空 = 运行期降级为抽取式，无 LLM 生成 |
| `LLM_BASE_URL` | DashScope 兼容端点 | OpenAI 兼容网关地址 |
| `LLM_MODEL` / `VISION_MODEL` / `EMBEDDING_MODEL` | `qwen-plus` / `qwen-vl-max` / `text-embedding-v3` | 抽取 / 视觉理解 / 向量检索模型；首页右上角可在运行时切换模型 |
| `MINERU_TOKEN` | 空 | [MinerU](https://mineru.net) 解析凭证。**建议配**：高质量 reading-order 正文 + 原始表格 HTML + 真实裁剪图 + 公式/OCR。留空自动降级到内置 PyMuPDF 适配器（能跑，但表格/图表/公式质量明显下降） |
| `LLM_FALLBACKS` | 空 | 多供应商候选路由，格式 `key1@url1\|model1,key2@url2\|model2`，主供应商失败自动切换 |
| `BACKEND_PORT` / `FRONTEND_PORT` | 8002 / 4002 | 宿主端口（容器内固定 8000/3000） |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8002` | 浏览器访问后端的地址，**构建期注入** |
| `POSTGRES_USER/PASSWORD/DB` | `researchlens` | 数据库账号（compose 使用；DB 端口不对宿主发布） |
| `DATABASE_URL` | sqlite | **仅本机直跑后端时生效**；Docker 部署由 compose 强制覆盖为 postgres |
| `MAX_UPLOAD_MB` / `MAX_DOWNLOAD_MB` | 40 / 80 | 上传与网址下载体积上限 |
| `PUBLIC_DEPLOYMENT` + `ADMIN_TOKEN` | false / 空 | 公开部署时置 `true` 并**必须**配 `ADMIN_TOKEN`，配置缺失会在启动期直接报错 |
| `CORS_ORIGINS` | localhost 前端端口 | 允许跨域来源 |

**降级行为一览（如实说明，不假装可用）**

| 缺什么 | 会怎样 |
|---|---|
| 缺 `LLM_API_KEY` | 抽取/问答走抽取式路径；界面**不冒充**有 AI 结论，评测里相关项标 `not_evaluated`（**`not_evaluated` ≠ 0 分**） |
| 缺 `MINERU_TOKEN` | 解析降级 PyMuPDF，仍是真实解析，但版式/表格/图片质量下降 |
| 缺网络 | 只有 3 篇内置示例可完整演示；网址导入会因为下载失败而报错（错误信息会指到具体环节） |

---

## 🧭 八个视图

| 视图 | 做什么 |
|---|---|
| 论文地图 | 问题 / 方法 / 数据集 / 实验 / 结果 / 局限 总览，含可展开章节树与可点击放大的关键图表 |
| 方法动画 | 核心算法流程逐步动画，每步可探索（步骤正文富文本，`图/表N` 引用可点击跳转），并展示论文原图 |
| 证据链 | 断言分组 + 逐字原文引用高亮 + 跳页定位；每条断言给出证据判定与置信度 |
| 研究图谱 | React Flow 交互图谱；点节点在**本页展开**该断言的证据，可跳转到证据链并自动定位高亮 |
| 讲解 | 分镜式讲解（讲解词 + 要点），涉及内容（图/表/原文）可点击在右侧核对证据；无语音、无播放按钮 |
| 证据问答 | SSE 流式接真实模型作答，带引文与置信度；回答富文本排版、证据卡片可定位原文；历史跨视图保留 |
| 自动评测 | **「AI 质量评分（自动）」** + 指标明细 + 逐断言汇总；无样本的指标如实标 `not_evaluated`，不填 0 冒充 |
| 论文阅读 | 结构化导读（章节 + 要点 + 图表）与全文原文（按页）双模式；公式用 KaTeX 渲染；表格优先展示原始 HTML 表 |

**进度语义**：论文页的进度以 `manifest.capabilities` 为唯一真相，
后端 11 阶段流水线为 `acquire → parse → normalize → media → index → claims →
verify → exhibits → qa_bank → evaluate → publish`；
`pdf/text/media/claims` 为阻塞域（未就绪即视为「处理中」），其余为非阻塞域。
完成时只按「就绪跃迁」拉取一次对应数据，失败保留旧数据，不闪、不清空。

---

## 🧱 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 14 (App Router) · React 18 · TypeScript · Tailwind · Framer Motion · `@xyflow/react`（React Flow）· KaTeX · pdfjs-dist |
| 后端 | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic |
| AI | OpenAI 兼容 API（默认 DashScope/百炼）· 结构化输出 · 视觉理解 · 向量检索 · 多供应商候选路由与降级 |
| 解析 | MinerU（可选，高质量）· PyMuPDF（内置降级） |
| 数据 | PostgreSQL 16 + pgvector（Docker）· SQLite（本机直跑） |
| 运行时 | Docker Compose（4 容器）· SSE 流式 |

**约束**：不要求 GPU / CUDA / 本地大模型，全部走云端 API；有 Key 即可跑通全链路。

---

## 📁 目录结构

```
ResearchLens/
├─ backend/
│  ├─ app/
│  │  ├─ api/            # FastAPI 路由（canonical + 历史兼容层）
│  │  ├─ contracts/      # 对外契约：jobs / qa / documents / evidence…
│  │  ├─ core/           # 配置、DB、错误、可观测
│  │  ├─ modules/        # 业务域：papers / parse / pipeline / evidence / qa / evaluation / graph / scene …
│  │  ├─ projection/     # 对外投影层（DTO 的唯一实现处，CONTRACT.md 说明契约）
│  │  ├─ seed/           # 3 篇内置示例论文的 IR
│  │  └─ tests/          # 单元 / 集成测试
│  ├─ migrations/        # Alembic 迁移（启动时自动执行）
│  └─ evals/             # 离线评测（benchmark + README）
├─ frontend/
│  ├─ app/               # Next.js 路由：`/`（论文库）、`/upload`、`/paper/[slug]`
│  ├─ components/        # 视图与组件（8 个视图在 components/views/）
│  ├─ hooks/             # usePaperWorkspace / useJobEvents …
│  ├─ lib/               # 纯函数内核（进度、富文本、图布局、问答状态机…）＋ 同名 *.spec.ts
│  └─ scripts/           # 渲染卫生检查、文本路径检查
├─ scripts/acceptance/   # 端到端验收套件（7 套，独立于实现细节的黑盒检查）
├─ docs/                 # 规格 / 架构 / 决策 / 任务 / 开源复用 / 素材版权
└─ docker-compose.yml
```

---

## 🧩 本地开发（不用 Docker）

**后端**

```bash
cd backend
uv sync                              # 或 pip install -r requirements.txt
cp ../.env.example .env              # 后端读的是 backend/.env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**前端**

```bash
cd frontend
npm install
npm run dev                          # 打开 http://localhost:3000（被占用会自动换端口）
```

> 本机直跑时数据库默认是 SQLite（`backend/data/researchlens.db`），无需额外安装 Postgres；
> 但 Docker 部署一律用 PostgreSQL + pgvector。

---

## ✅ 测试与验收

```bash
# 后端单测 / 集成测试（当前基线 1023 passed）
cd backend && .venv/Scripts/python -m pytest        # Windows
cd backend && .venv/bin/python -m pytest            # macOS / Linux

# 前端纯函数内核测试（当前基线 136 项断言，含类型检查）
cd frontend && npm run test:lib

# 端到端验收：四容器已起时，黑盒核对真实 HTTP 行为（当前 7/7 全绿）
python scripts/acceptance/run_all.py
```

验收套件覆盖：论文 manifest/章节/图表路由、图谱无断裂与证据可达、SSE 事件序列、
评测口径（`not_evaluated` 不冒充 0）、多轮问答稳定性、**问答无拒答**（三问×两篇）、
**导入进度语义**（`capabilities` 为真相、阻塞域不停在 pending）。
详见 [`scripts/acceptance/README.md`](scripts/acceptance/README.md)。

> ⚠️ `docker-compose.yml` **不挂载源码**（代码烘进镜像）。改了后端/前端代码后，
> 必须 `docker compose build backend worker frontend && docker compose up -d`，
> 否则容器里跑的还是旧代码 —— 这一点验收 README 里有专门的踩坑记录。

---

## 📄 文档

| 文档 | 内容 |
|---|---|
| [`docs/SPEC_REVISED.md`](docs/SPEC_REVISED.md) | 需求规格（修订版） |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 系统架构与流水线分层 |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | **决策记录（ADR，共 115 条）**：每条含背景、取舍、后果；含被否决的方案与踩坑 |
| [`docs/TASKS.md`](docs/TASKS.md) | 任务分解与进度 |
| [`docs/OSS_REUSE.md`](docs/OSS_REUSE.md) | 开源复用清单（来源 / License / 复用范围 / 不可复用部分） |
| [`docs/ASSET_LICENSES.md`](docs/ASSET_LICENSES.md) | 素材版权记录 |
| [`backend/app/projection/CONTRACT.md`](backend/app/projection/CONTRACT.md) | 投影层对外契约 |
| [`backend/evals/README.md`](backend/evals/README.md) | 离线评测 benchmark 说明 |
| [`scripts/acceptance/README.md`](scripts/acceptance/README.md) | 验收套件用法与已知偏离 |

---

## 🔒 素材与许可

- 内置 3 篇示例论文为**项目自绘原创**，不使用任何第三方论文素材；
- 自举与示例链接均为**开放获取**的正式出版论文，仅作检索与原文引用，著作权归原作者与期刊；
- 第三方依赖的 License 见 `docs/OSS_REUSE.md` 与 `docs/ASSET_LICENSES.md`。

---

## 🏆 比赛定位

> **ResearchLens —— 面向科研成果的多模态证据理解、交互式演绎与智能讲解平台。**

技术亮点：多模态论文理解 · Claim–Evidence 图谱 · 证据约束生成 · 交互式科研可视化 ·
Grounded Q&A · 自动质量评测（AI 评分如实标注「自动」，无样本指标不填 0）。
