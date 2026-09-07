# TASKS.md — ResearchLens 任务分解（Epic 清单与进度）

> 进度状态：`[ ]` 待办 / `[x]` 完成 / `[~]` 进行中。所有 Epic 目标以「能跑起来、能演示、可验证」为准。

## EPIC 0 — OSS Recon（Spec §26）[x]
- [x] 评估 showlab/Paper2Video、Gen-Verse/Paper2Video、langgenius/dify
- [x] 记录 License / 复用范围 / 不可复用部分 → `OSS_REUSE.md`
- [x] 产出 `ARCHITECTURE.md` / `DECISIONS.md` / `TASKS.md` / `ASSET_LICENSES.md`

## EPIC 1 — 运行参考链（Spec §27）[~]
- [~] 理解 `Paper → Slides → Narration` 分层（思想已抽象进 ARCHITECTURE 的 pipeline）
- [x] 明确不复制其 GPU/talking-head 链路

## EPIC 2 — Paper Parser（Spec §28）[ ]
- [ ] PDF → pages → sections → figures → tables（pypdf 文本 + 区域定位）
- [ ] Live 模式：结构抽取（Vision/LLM 结构化输出）；Demo 模式：读 seed

## EPIC 3 — Claim / Evidence（Spec §29）[ ]
- [ ] Claim 提取（statement / type / confidence）
- [ ] Evidence 关联（page / region / text / quote）与 Evidence Gate（无证据 → unsupported）

## EPIC 4 — Research Graph（Spec §30，React Flow）[ ]
- [ ] 后端 `/api/papers/{id}/graph` 输出 nodes + edges
- [ ] 前端 React Flow 渲染 Problem→Method→Experiment→Claim→Evidence

## EPIC 5 — Presentation Engine（Spec §31）[ ]
- [ ] Scene 生成（Intro/Method/Experiment/Result/Limitation + 证据绑定）
- [ ] Scene 动画步骤 + Narration（script / tts / subtitle）

## EPIC 6 — Interactive Viewer（Spec §32）[ ]
- [ ] Paper Map 视图
- [ ] Method 动画视图
- [ ] Claim→Evidence→Page 视图（含原图引用）
- [ ] 布局：PAPER / VISUAL STAGE / EVIDENCE 三区 + Timeline

## EPIC 7 — Presenter（Spec §33）[ ]
- [ ] 字幕 + 预生成音频 + 简易 Avatar；TTS 外部 API 可选；失败降级字幕

## EPIC 8 — Grounded Q&A（Spec §34）[ ]
- [ ] Question → Retrieval → Evidence → Answer（含 Confidence）
- [ ] 无证据 → "模型未在论文中找到直接依据"（禁止编造）

## EPIC 9 — Evaluation（Spec §35）[ ]
- [ ] `/api/evaluation` 真算指标（Citation Coverage / Alignment / Unsupported Rate = ~0 等）
- [ ] 前端 Evaluation 仪表盘

## EPIC 10 — Demo Worlds（Spec §36）[ ]
- [ ] 3 份演示论文：Cybersecurity / Computer Vision / Education AI（自绘原创，含 SVG 图/表）
- [ ] seed JSON + loader + `/api/demo/{slug}`

## EPIC 11 — Docker / Fallback（Spec §37）[ ]
- [ ] docker-compose.yml：backend + frontend + postgres(pgvector)
- [ ] API/model/TTS 逐级降级（cached/mock/subtitle）
- [ ] `.env.example`；`cp .env.example .env && docker compose up --build`

## EPIC 12 — Final Integration（Spec §38）[ ]
- [ ] 端到端：Docker → Paper → Map → Method → Evidence → Presenter → Q&A → Evaluation
- [ ] 稳定性验证 + README

---

## 横切
- [x] Evidence-first 数据模型（Claim/Evidence/Citation）
- [ ] 前端全部视图与后端 API 真实绑定（无假数据）
- [ ] 自动质量评分进入答辩演示
