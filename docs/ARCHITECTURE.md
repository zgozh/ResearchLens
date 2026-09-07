# ARCHITECTURE.md — ResearchLens 系统架构

## 1. 目标与核心命题

把一篇科研论文自动转换成「证据驱动的可交互科研展项」：

```
Paper → 结构提取 → Claim 提取 → 证据链接 → Research Graph
     → Presentation Spec → 可视化渲染 → 讲解 / 数字人导览
```

**核心创新 = Evidence-first**：任何 AI 生成内容都必须绑定 `claim_id / source_page / source_region / source_text / confidence`。没有证据 → 不能作为「事实」展示，只能标记为「AI 解释/推断」。这是本项目区别于「论文总结工具」「AI 文案生成器」的关键（Spec §0/§3/§14.3/§21）。

---

## 2. 分层总览

```
┌────────────────────────────────────────────────────────────┐
│  Frontend (Next.js 14, App Router, TS, Tailwind, Framer)   │
│  Landing/Upload · Paper Map · Method · Claim→Evidence      │
│  Research Graph · Timeline/Scene · Presenter · Q&A · Eval  │
└───────────────▲───────────────────────────▲────────────────┘
                │  REST + SSE                │  fetch / sse
┌───────────────┴───────────────────────────┴────────────────┐
│  Backend (FastAPI + Pydantic + SQLAlchemy)                 │
│  ├─ api/     routes: papers, claims, graph, presentation,  │
│  │           qa, evaluation, demo, health, stream          │
│  ├─ services/ parser · claims · evidence( Gate ) · graph   │
│  │           presentation · qa · evaluation · ai · demo    │
│  └─ core/    config(dataclass+dotenv) · db · logging       │
└───────────────▲───────────────────────────▲────────────────┘
                │ ORM / SQLAlchemy           │ RAG (LIVE only)
┌───────────────┴───────────────────────────┴────────────────┐
│  Store:  Postgres + pgvector (prod) / SQLite (local dev)    │
│  AI:     OpenAI-compatible API (LLM + Vision + Structured)  │
│          DEMO_MODE → pre-generated seed (no API key)        │
└────────────────────────────────────────────────────────────┘
```

---

## 3. 处理管线（Pipeline）

按 Spec §5，第一版实现为**有状态 Pipeline**，不硬堆多 Agent。角色职责内聚到不同 service 方法：

| 角色 | 职责 | 映射到 service | 是否必要 |
| --- | --- | --- | --- |
| Parser | PDF → pages / sections / figures / tables | `parser.py` | 必须 |
| Research Analyst | 从结构里提取 Claim + 语义陈述 | `claims.py` | 必须 |
| Evidence Validator | 把 Claim 关联到具体证据；无证据则打「未验证」标记（Evidence Gate） | `evidence.py` | 必须 |
| Presenter | 生成 Scene/Narration（讲解脚本） | `presentation.py` | 必须 |

编排顺序（在 `services/pipeline.py` 中组合为一个可重放、可降级的流程）：

```
parse → structure
  → claim_extract → claims[]
  → evidence_link → claim.evidence[]  (Gate: 无证据→unsupported)
  → build_graph → research_graph
  → present → scenes[] + narration[]
  → evaluate → score (CitationCoverage / Alignment / UnsupportedRate / ...)
```

### 降级策略（Spec §37，主链路永远可用）
```
API failure        → cached result
Model failure      → mock / pre-generated
TTS failure        → subtitle (文字始终可用)
无 API key         → DEMO_MODE → 直接读 seed
```

---

## 4. 数据模型（对应 Spec §18）

```
Paper(id, slug, title, authors, year, domain, abstract, pdf_url, status, source_mode)
PaperPage(id, paper_id, page_no, text, region_map jsonb)
Section(id, paper_id, heading, kind, summary)
Figure(id, paper_id, fig_no, caption, page, image_ref, glyph_svg, importance)
Table(id, paper_id, table_no, caption, page, content_json)
Claim(id, paper_id, claim_id, statement, type, confidence, status[SUPPORTED|UNSUPPORTED])
Evidence(id, claim_id, page, region, region_type, text, quote)
ResearchGraphNode / ResearchGraphEdge   (paper_id, kind, label, props)
Scene(id, paper_id, order, title, kind, summary, evidence_refs)
Narration(id, scene_id, script, tts_text, audio_url, subtitle)
Question / Answer(id, paper_id, q, a, evidence_refs, confidence)
Evaluation(id, paper_id, metrics jsonb, overall_score, computed_at)
GenerationJob(id, paper_id, stage, status, payload, created_at)
```

为降低启动门槛，本地开发用 **SQLite**（零依赖、即开即用），Docker 生产用 **Postgres + pgvector**。通过 `DATABASE_URL` 切换。RAG（pgvector 向量检索）仅在 LIVE 模式启用；DEMO 模式直接用 seed 的结构化结果。

---

## 5. 关键流程（前端视角）

```
Demo 开场：
  /  → DROP A PAPER  (选择 3 个 Demo 论文 之一)
       → GET /api/demo/{slug}  → paper + map
       → 渲染 Paper Map (Problem/Method/Dataset/Experiment/Result/Limitation)

点击 Method：
  → GET /api/papers/{id}/presentation 取得 Method scene 的动画步骤
  → Framer Motion 逐步动画 (Input → Backbone → FE → Module → Prediction)

点击实验结果：
  → GET /api/papers/{id}/claims  → 取 claim
  → GET /api/papers/{id}/claims/{cid} → claim + evidence + 原图引用
  → 右侧 Evidence 面板：Claim / Evidence / Page / original figure

Research Graph：
  → GET /api/papers/{id}/graph → nodes+edges
  → React Flow 渲染 Problem → Method → Experiment → Claim → Evidence

AI Presenter：
  → GET /api/papers/{id}/presentation → scene + narration
  → 字幕 + 预生成音频（fallback 纯字幕）；TTS 外部 API 可选

Grounded Q&A：
  → POST /api/papers/{id}/qa {question}
  → Answer + Evidence(Page/Content) + Confidence
  → 无证据支持 → "模型未在论文中找到直接依据"（禁止编造）

Evaluation：
  → GET /api/papers/{id}/evaluation → real computed metrics
```

---

## 6. 技术栈（对应 Spec §17）

| 层 | 选型 | 说明 |
| --- | --- | --- |
| Frontend | Next.js14 + React18 + TS + Tailwind v4 + Framer Motion + @xyflow/react + pdfjs-dist | App Router；自定义设计系统（非普通 Admin） |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2.x + Uvicorn | REST + SSE |
| AI | OpenAI-compatible API + Vision + Structured Output + RAG | 多供应商候选 + 降级（`AIClient`） |
| Data | PostgreSQL + pgvector（prod）/ SQLite（dev） | RAG 仅 LIVE |
| Runtime | Docker Compose + SSE | 一键 `docker compose up --build` |
| 约束 | 无 CUDA / 无 Ollama / 无本地模型 / 无 GPU | Spec §16 |

---

## 7. 目录结构

```
ResearchLens/
├─ docs/            OSS_REUSE · ARCHITECTURE · DECISIONS · TASKS · ASSET_LICENSES
├─ backend/
│  └─ app/
│     ├─ main.py              FastAPI app 装配
│     ├─ core/                config(dataclass) · db · logging
│     ├─ models/              SQLAlchemy ORM
│     ├─ schemas/             Pydantic v2 模型
│     ├─ services/            parser · claims · evidence · graph · presentation · qa · evaluation · ai · pipeline · demo
│     ├─ seed/                3 份 Demo 论文 seed (JSON + loader)
│     └─ api/                 routes
├─ frontend/           Next.js App（详见 TASKS.md）
└─ docker-compose.yml
```

---

## 8. 安全性 / 一致性 / 去随机化

- **Source Grounding（Spec §14.1）**：LLM 只能访问 Paper Text / Figures / Tables / Claims / Evidence。
- **JSON Schema（Spec §14.2）**：所有中间结果必须 JSON（Pydantic 强约束 + Zod 前端校验）。
- **Evidence Gate（Spec §14.3）**：无 citation 不进事实层。
- **Fixed Templates（Spec §14.4）**：Research Intro / Method / Experiment / Result / Limitation 使用固定模板。
- **Deterministic Demo（Spec §14.5）**：现场演示使用预生成结果；实时生成仅作第二条路线。
