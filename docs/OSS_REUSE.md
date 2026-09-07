# OSS_REUSE.md — ResearchLens 开源复用清单

> 本文档记录本项目复用/参考的开源项目的**确凿来源、License、commit、复用范围与修改范围**。
> 原则（详见 DECISIONS.md）：**OSS 能复用不重写；已有成熟前端不重新设计；没有必要的复杂依赖不引入；不部署本地大模型；不要求 GPU；不从零实现论文解析全部基础能力。**
> 本项目的主体创新（Evidence-first 中间表示 + 交互式科研可视化 + 自动质量评测）是原创的，开源项目仅作为「架构教材」被抽象吸收，而非「克隆改名」。庆园杯要求参赛作品原创、拥有完整合法知识产权，因此**不以任何开源底座作为自己的全部成果**，且所有 Demo 论文、图表、SVG 均为本项目自绘原创。

---

## 1. 主参考：showlab/Paper2Video — 新加坡国立大学 Show Lab

| 项目 | 说明 |
| --- | --- |
| 仓库 | https://github.com/showlab/Paper2Video |
| License | MIT（其上 PaperTalker / Presentation 模块均 MIT） |
| 定位 | 从科研论文自动生成演讲视频；输入论文/图像/音频，输出幻灯片+字幕+光标+语音+视频 |
| 我们的核心借鉴 | `Paper → Slides → Narration` 的分层管线思想；幻灯片/讲解/Narration 的架构抽象；对项目做评测的思路 |

### 复用方式：作为「架构教材」，抽象成我们的业务系统
- **借鉴**：`Paper → Presentation → Narration` 的生成分层；把「讲解」与「视觉呈现」解耦——讲解内容由 LLM 生成，视觉输出由程序渲染（HTML/CSS/SVG），避免生成式视频的不稳定性。
- **吸收为自研**：PaperTalker 的视频/talking-head 链路（依赖 NVIDIA A6000 48GB GPU 与 GPU 推理）**明确不采用**（Spec §6.1/§6.2）。我们只抽取思想，自行实现「多模态解析 → 结构化 → 证据约束 → 浏览器交互式渲染」。

### 修改/裁剪范围
- 不粘贴其代码；仅作为设计参照。本项目所有代码均为自研实现。

---

## 2. 第二参考：Gen-Verse/Paper2Video — Preacher

| 项目 | 说明 |
| --- | --- |
| 仓库 | https://github.com/Gen-Verse/Paper2Video |
| License | 需以仓库为准（使用时按仓库 LICENSE 记录） |
| 定位 | 把科学论文转换为视频摘要，采用层级规划，支持多维度自动评价 |
| 我们的核心借鉴 | 评价维度：`accuracy / professionalism / aesthetic quality / alignment / CLIP / Aesthetic Score` |

### 复用方式：借鉴「自动评测」维度，建立自研评分
- 将它对外宣称的评测维度映射到本项目自研的 **ResearchLens Quality Score**（Spec §21）：
  - Citation Coverage（引用/证据覆盖率）
  - Claim–Evidence Alignment（断言-证据对齐度）
  - Unsupported Claim Rate（无证据断言率，**目标≈0**）
  - Structure Extraction Accuracy（结构抽取准确率）
  - Visual Consistency（视觉一致性）
  - Answer Grounding（答案 grounded 程度）
- 我们**不沿用其具体指标实现**（其指标针对视频生成），而是针对「证据驱动」这一核心创新重写指标口径，并在 /api/evaluation 中真算结果，而非编造数字。

---

## 3. 第三参考：langgenius/dify

| 项目 | 说明 |
| --- | --- |
| 仓库 | https://github.com/langgenius/dify |
| License | 以仓库 LICENSE 为准（商用需看清条款；本项目仅作 UX/抽象参考） |
| 定位 | LLM 应用开发平台：Workflow、RAG、Agent、模型管理、可观测、Docker Compose 部署、OpenAI-compatible 模型 |
| 我们的核心借鉴 | Workflow UX、Provider 抽象、模型配置理念（多供应商/候选路由/降级） |

### 复用方式：只吸收「理念」，不嵌入 Dify 本身
- 参考其 **模型 Provider 抽象**：本项目把 LLM 调用收敛进单个 `AIClient`，支持 OpenAI-compatible base_url/model，并做「多供应商候选 + 失败降级（demo cache → mock）」的治理（Spec §14.5/§37）。
- 参考其 **Docker Compose 一键部署** 与 **模型配置外置（`.env`）** 理念。
- **不引入** Dify 依赖、其数据库 schema、其前端，避免「套壳平台」。本项目只有 4 个轻量角色（Parser / Analyst / Validator / Presenter）并实现为有状态 Pipeline（Spec §5）。

---

## 4. 前端复用：直接借成熟创作型 UI 生态（不自己造轮子）

依据 Spec §9/§40「前端 Agent 强制规则：先寻找 OSS UI 再改，禁止『请帮我生成一个漂亮的 Dashboard』」，我们基于以下**成熟、稳定、可控**的开源前端生态来构建（每项均为主流维护、大量生产使用）：

| 库 | License | 用途 | 复用范围 |
| --- | --- | --- | --- |
| Next.js 14 (App Router) | MIT | 前端框架、SSR/路由/API 路由 | 框架 |
| React 18 + TypeScript | MIT | UI 组件 | 框架 |
| Tailwind CSS v4 | MIT | 原子化样式/设计系统 | 样式 |
| Framer Motion | MIT | 过渡/关键帧/手势动画 | Method 动画、场景转场 |
| @xyflow/react (React Flow) | MIT | 节点/边编辑器——用于 Research Graph | 图视图核心 |
| pdfjs-dist / react-pdf | Apache-2.0 | 真实 PDF 渲染（Live 上传路线） | PDF 查看器 |
| lucide-react | ISC | 图标体系 | 图标 |
| Radix UI primitives | MIT | 无样式可访问原语（Tabs/Tooltip/Dialog） | 可访问交互原语 |
| zod | MIT | 前端/后端共享的类型+运行时校验 | 数据模型 |

> 说明：不引入全套 shadcn/ui（文件量与定制自由度权衡），但复用其「基于 Radix+Tailwind 的原语分层」理念；组件以自绘 cohesive 设计系统实现，保证「科研杂志 × Apple Keynote × AI Studio」单一定调，不做廉价 SaaS 后台风。

---

## 5. 数据/解析复用

| 库 | License | 用途 |
| --- | --- | --- |
| pypdf | BSD-3 | PDF 文本抽取（Live 模式） |
| PyMuPDF (fitz) | AGPL-3.0 | 页面渲染、图表/图片区域定位（Live 模式；**注意 AGPL 传染性，仅作为可选依赖，主链路不依赖**） |
| SQLAlchemy 2.x | MIT | ORM |
| FastAPI / Pydantic / Uvicorn | MIT | API 框架 |
| psycopg / pgvector | MIT / PostgreSQL | Postgres 向量检索（仅 LIVE 模式） |

> PyMuPDF 的 AGPL 传染性：本项目主链路（DEMO 模式）**不依赖** PyMuPDF；Live 模式它作为可选依赖存在，部署与学术用途请遵守其 License 条款；若不希望 AGPL，可仅保留 pypdf + 自研图表定位。

---

## 6. 明确不采用的 OSS（理由）

| 项目 | 不采用原因 |
| --- | --- |
| showlab/Paper2Video 的完整 talking-head/数字人视频链路 | 依赖 NVIDIA A6000 48GB GPU、GPU 推理，不符合「不要求 GPU」约束（Spec §6.2）。我们只保留 Presenter 的「字幕+音频」降级路径。 |
| 整套 Dify 应用平台 | 过度依赖，违背「不是 Agent 数量/平台套壳」原则（Spec §5） |
| 本地大模型 / Ollama / ComfyUI | 违背 Spec §16「不允许要求 CUDA/Ollama/本地模型/GPU」 |
| 任何「clone 改名加 RAG」的伪原创 | 违背庆园杯原创/知识产权要求 |

---

## 7. 复用边界总结

- **我们写出并拥有知识的**：Evidence-first 中间表示、Research Graph 逻辑、Presentation Spec / Scene 模板化渲染、Grounded Q&A、ResearchLens Evaluation、全部 Demo 论文与 SVG 图/表、设计系统、前端各视图。
- **我们借势的**：成熟框架（Next/Tailwind/Framer/React Flow/pdfjs）、成熟理念（Paper2Video 分层、Dify Provider 抽象、Preacher 评测维度）。
- **我们引用的开源项目的代码本体**：仅在「理解后自行实现」层面借鉴，不直接粘贴其源码文件（避免 License 与原创边界问题）。
