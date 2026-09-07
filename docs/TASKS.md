# TASKS.md — ResearchLens 任务分解（Epic 清单与进度）

> 进度状态：`[ ]` 待办 / `[x]` 完成 / `[~]` 进行中。
> 说明：核心可运行版本已完成并验证（后端 API 全链路 + 前端 8 视图真实渲染 + Docker 镜像构建成功）。

## EPIC 0 — OSS Recon（Spec §26）[x]
- [x] 评估 showlab/Paper2Video、Gen-Verse/Paper2Video、langgenius/dify
- [x] 记录 License / 复用范围 / 不可复用部分 → `OSS_REUSE.md`
- [x] 产出 `ARCHITECTURE.md` / `DECISIONS.md` / `TASKS.md` / `ASSET_LICENSES.md`

## EPIC 1 — 运行参考链（Spec §27）[x]
- [x] 理解 `Paper → Slides → Narration` 分层（已抽象进 ARCHITECTURE 的 pipeline）
- [x] 明确不复制其 GPU/talking-head 链路

## EPIC 2 — Paper Parser（Spec §28）[x]
- [x] PDF → pages / sections / figures / tables（pypdf 文本 + 区域定位）
- [x] Live 模式：结构抽取；Demo 模式：读 seed

## EPIC 3 — Claim / Evidence（Spec §29）[x]
- [x] Claim 提取（statement / type / confidence）
- [x] Evidence 关联（page / region / text / quote）与 Evidence Gate（无证据 → unsupported）

## EPIC 4 — Research Graph（Spec §30，React Flow）[x]
- [x] 后端 `/api/papers/{id}/graph` 输出 nodes + edges
- [x] 前端 React Flow 渲染 Problem→Method→Experiment→Claim→Evidence

## EPIC 5 — Presentation Engine（Spec §31）[x]
- [x] Scene 生成（Intro/Method/Experiment/Result/Limitation + 证据绑定）
- [x] Scene 动画步骤 + Narration（script / tts_text / subtitle）

## EPIC 6 — Interactive Viewer（Spec §32）[x]
- [x] Paper Map 视图
- [x] Method 动画视图
- [x] Claim→Evidence→Page 视图（含原图引用）
- [x] 布局：PAPER / VISUAL STAGE / EVIDENCE 三区 + Timeline

## EPIC 7 — Presenter（Spec §33）[x]
- [x] 字幕 + 预生成音频 + 简易 Avatar；TTS 外部 API 可选；失败降级字幕

## EPIC 8 — Grounded Q&A（Spec §34）[x]
- [x] Question → Retrieval → Evidence → Answer（含 Confidence）
- [x] 无证据 → "模型未在论文中找到直接依据"（禁止编造）

## EPIC 9 — Evaluation（Spec §35）[x]
- [x] `/api/evaluation` 真算指标（Citation Coverage / Alignment / Unsupported Rate ≈ 0 等）
- [x] 前端 Evaluation 仪表盘

## EPIC 10 — Demo Worlds（Spec §36）[x]
- [x] 3 份演示论文：Cybersecurity / Computer Vision / Education AI（自绘原创，含 SVG 图/表）
- [x] seed JSON + loader + `/api/demo/{slug}`

## EPIC 11 — Docker / Fallback（Spec §37）[x]
- [x] docker-compose.yml：backend + frontend + postgres(pgvector)
- [x] API/model/TTS 逐级降级（cached/mock/subtitle）
- [x] `.env.example`；`cp .env.example .env && docker compose up --build`
- [x] 镜像构建已验证（researchlens-backend / researchlens-frontend Built）

## EPIC 12 — Final Integration（Spec §38）[x]
- [x] 端到端：Paper → Map → Method → Evidence → Presenter → Q&A → Evaluation
- [x] 稳定性验证（headless Chromium 验证全部 8 视图真实渲染 + API 绑定）
- [x] README / 一键部署说明

---

## 横切
- [x] Evidence-first 数据模型（Claim/Evidence/Citation）
- [x] 前端全部视图与后端 API 真实绑定（无假数据）
- [x] 自动质量评分进入答辩演示

## 后续可选（非阻塞）
- [ ] Live 模式接真实 OpenAI 兼容 API（DEMO_MODE=false）做结构抽取/视觉理解/RAG 的真实链路验证
- [ ] 现场 10 papers / 100 claims 固定 Benchmark 的评测脚本
- [ ] TTS 接真实外部语音（失败已自动降级字幕）
