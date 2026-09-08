# ResearchLens · AI 科研视界

> **让一篇论文从「文档」变成「可验证、可演示、可交互的科研成果」**

第二届「庆园杯」人工智能创新应用大赛 · 主题三（开放创新探索）参赛作品。

ResearchLens 把一篇科研论文自动转换成**证据驱动的可交互科研展项**：
论文结构 → 核心方法 → 实验结果 → 证据链 → 动画化讲解 → 可点击研究图谱 → AI 问答。

核心创新是 **Evidence-first**：任何 AI 生成内容都必须绑定 `claim_id / source_page / source_region / source_text / confidence`，
没有证据就不能作为「事实」展示——这正是它区别于普通「论文总结工具 / AI 文案生成器 / AI PPT 生成器」的地方。

---

## ✨ 功能亮点

- **全中文界面**：默认语言为中文（保留关键英文术语作点缀），可直接演示
- **真实公开论文 + URL 放入**：粘贴公开论文网址 → 下载 → **MinerU 高质量文档解析**（reading-order 正文 + 结构化表格 + 真实裁剪图 + OCR/公式）→ 真实大模型完整抽取（结构/断言/证据/场景/问答）；也支持本机 PDF 上传。(配置 `MINERU_TOKEN` 即开启；未配置自动降级 pymupdf。默认自举 3 篇中文 **软件学报** 真实论文：JPEG 隐写载体选择 / 移动应用用户接受度建模 / Solidity 智能合约缺陷预测)
- **DashScope 模型可选**：首页右上角下拉切换 qwen-turbo/plus/max/long/vl 等模型（运行时生效）
- **Paper Map**：一键生成 问题/方法/数据集/实验/结果/局限 总览（含可展开章节树 + 要旨 + 关键图表可点击放大）
- **方法动画**：核心算法流程动画 + 每步可探索（步骤正文富文本，`图/表N` 引用可点击）+ 论文原图
- **Claim → Evidence → Page**：断言分组 + 原文引用高亮 + 跳页定位；图/表可点击放大（含真实论文图）
- **Research Graph**：React Flow 图谱，点击节点直接在**图谱内弹出**该断言的证据，并可跳转到证据链并自动定位高亮该证据
- **讲解（分镜式）**：按 6 个分镜做详细讲解（讲解词+要点），涉及内容（图/表/原文）可点击在右侧查看对应证据；无语音、无播放按钮（仅分镜切换）
- **Grounded Q&A**：接真实模型回答任意问题，带引文 + 置信度；回答富文本排版 + 证据卡片可定位原文；**问答历史跨视图切换保留**
- **论文阅读**：结构化导读（章节+要点+图表）与「全文原文」（按页原文）双模式切换，非仅摘要
- **ResearchLens Evaluation**：观众/作者双维度 + 指标明细 + 逐断言汇总

## 🖼 现场演示（Demo Mode）

`DEMO_MODE=true` 时**无需任何 API Key**即可完整演示：
先拖入/选择一篇 Demo 论文 → 自动生成 Paper Map → 点击 Method 看算法动画 →
点击实验结果看 Claim→Evidence→Page → 打开 Research Graph 图谱 → AI Presenter 讲解 →
提问「这篇论文哪里最值得质疑？」系统基于 Discussion 证据作答。

3 份 Demo 论文为项目**自绘原创**：计算机视觉 / 网络空间安全 / 教育 AI。

## 🔬 Live 模式（接入真实 LLM · 已接 DashScope）

> 演示无 key 也能跑（DEMO_MODE=true 读内置 seed）；若要「真实抽取链路」，切到 Live。

```bash
# .env 中：
DEMO_MODE=false
LLM_API_KEY=<你的 DashScope/百炼 API-KEY>
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
VISION_MODEL=qwen-vl-max
```

Live 模式下走真实链路：上传 PDF → 结构化抽取 → **LLM 生成 Claim** → Evidence 链接 → 图谱/讲解/问答/评测。
`AIClient` 对 OpenAI 兼容 gateway 做了 `json_schema` → `json_object` 结构化输出降级，多供应商候选失败自动切换。

## 🧪 Benchmark / 自动评测（Spec §21/§22）

```bash
cd backend && python -m evals.run_benchmark --live
```

对数据集逐篇做真实 LLM 抽取并算指标：Claim Extraction Recall/Precision/F1、Evidence Coverage、
Unsupported Claim Rate、Citation Accuracy。详见 `backend/evals/README.md`。
当前实测：**evidence_coverage 100%、unsupported_claim_rate 0%**（所有抽取断言均绑定证据，Evidence-first 达标）。

## 🧱 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Next.js 14 (App Router) · React 18 · TypeScript · Tailwind v4 · Framer Motion · @xyflow/react (React Flow) · pdfjs-dist |
| 后端 | FastAPI · Pydantic v2 · SQLAlchemy 2.x |
| AI | OpenAI-compatible API · Vision · Structured Output · RAG（多供应商候选 + 降级） |
| 数据 | PostgreSQL + pgvector（生产）/ SQLite（本地开发） |
| 运行时 | Docker Compose · SSE |

**约束**：不要求 CUDA / Ollama / 本地模型 / GPU；现场演示可离线（Demo Mode）。

## 🚀 一键部署

```bash
cp .env.example .env
# 如需 Live 模式，填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
docker compose up --build
```

打开 `http://localhost:3000`。

> 默认 `DEMO_MODE=true`，无需 API Key 即可完整体验。

## 🧩 本地开发

**后端**
```bash
cd backend
uv sync            # 或 pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**前端**
```bash
cd frontend
npm install
# 若本机 8000 被占用，可先把后端跑在 8001：
#   set NEXT_PUBLIC_API_URL=http://localhost:8001
#   (并在后端 .env 的 CORS_ORIGINS 中加入 http://localhost:3000/3001)
npm run dev        # 打开 http://localhost:3000（端口被占会自动换 3001）
```

> 说明：本机 8000/3000 若已被其他服务占用，本地开发可用上述备用端口；生产一键部署一律用 Docker Compose（见下）。

## 📄 文档

- `docs/OSS_REUSE.md` — 开源复用清单（来源 / License / 复用范围）
- `docs/ARCHITECTURE.md` — 系统架构
- `docs/DECISIONS.md` — 关键决策记录（ADR）
- `docs/TASKS.md` — 任务分解
- `docs/ASSET_LICENSES.md` — 素材版权记录

## 🏆 比赛定位

> **ResearchLens——面向科研成果的多模态证据理解、交互式演绎与智能讲解平台。**

技术亮点：多模态论文理解 · Claim-Evidence Graph · 证据约束生成 · 交互式科研可视化 · Grounded Q&A · 自动质量评测。
