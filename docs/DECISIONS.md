# DECISIONS.md — ResearchLens 决策记录（ADR）

> 每条：**决策 / 背景 / 取舍 / 结论**。凡是「选什么、为什么选它而不选别的」都落在本文档，供答辩与可追溯。

---

## D-01 项目方向
- **决策**：做「AI 科研视界 ResearchLens」——把论文变成证据驱动的可交互科研展项。
- **背景**：第一届一等奖《灵眸智译》= 硬件+CV+可量化+民生对象+可现场展示；第二届主题三允许平台/程序，鼓励多模态/生成式/智能决策/数字人。不押注「AI 自由造世界」的随机性。
- **取舍**：放弃 AI 世界生成器（单人1个月不可行、易崩）；放弃多 Agent 辩论出长报告（押注在模型随机输出）。选择「真实痛点 + 可验证产出 + 强视觉 + 低现场风险」。
- **结论**：ResearchLens。

## D-02 复用 vs 自研边界
- **决策**：成熟 OSS 能复用不重写；但开源仅作为「架构教材」被抽象吸收，不直接粘贴其代码，并以 OSS_REUSE.md 记录来源/License/commit/复用范围。
- **背景**：庆园杯要求原创、完整知识产权；不能把开源底座当全部成果。Spec §41。
- **结论**：复用框架与理念（Paper2Video 分层 / Dify Provider 抽象 / Preacher 评测维度）；核心中间表示与前端视图全部自研。

## D-03 是否引入多 Agent
- **决策**：不硬堆多 Agent。第一版实现为有状态 Pipeline，内含 Parser / Analyst / Validator / Presenter 四个职责角色。
- **背景**：Spec §5「让评委看到可验证 AI 工程，而不是 Agent 数量」。
- **结论**：Pipeline 风格；后续按需才拆分。

## D-04 前端形态与风格
- **决策**：Next.js 14 App Router + React18 + TS + Tailwind v4 + Framer Motion + @xyflow/react + pdfjs-dist。自定义设计系统，基调「科研杂志 × Apple Keynote × AI Studio」。
- **背景**：Spec §9/§40 前端 Agent 强制规则：先找 OSS UI 再改，禁止「请帮我生成漂亮的 Dashboard」，避免廉价 AI SaaS 风。
- **取舍**：不引入全套 shadcn/ui（文件量大、定制受限），但复用其「Radix + Tailwind 原语分层」理念；用 lucide-react 图标 + Radix 原语保证可访问与交互质感。
- **结论**：自绘 cohesive 设计系统 + 成熟库，单一定调。

## D-05 数据存储
- **决策**：SQLAlchemy 2.x；本地开发 SQLite（零依赖、即开即用），Docker 生产 Postgres + pgvector。RAG（向量检索）仅在 LIVE 模式启用。
- **背景**：Spec §17 要求 PostgreSQL + pgvector / Qdrant；但本地要能立刻跑、Docker 要一键。
- **取舍**：DEMO 模式是核心演示路径（只用 seed 结构化结果），不需要本地数据库工程化就可用；用 DATABASE_URL 切换。
- **结论**：dev=SQLite，prod=Docker Postgres+pgvector。

## D-06 AI 调用与降级
- **决策**：LLM 调用收敛到单个 `AIClient`（OpenAI-compatible base_url/model），支持多供应商候选；失败/无 key → 降级到 cached/demo/mock。
- **背景**：Spec §14.5 Deterministic Demo、§37 API/model/TTS failure 逐级降级。
- **结论**：DEMO_MODE=true 无 key 可完整演示；LIVE_MODE 才调用模型。

## D-07 数字人定位
- **决策**：数字人只是 Presenter，不成为主体；必须支持「字幕 + 音频」降级，Avatar 服务挂掉仍能展示。
- **背景**：Spec §13。不做完整 talking-head 视频链路（需 GPU）。
- **结论**：Presenter 组件 = 字幕 + 预生成音频 + 简易 Avatar 视觉（Three.js/CSS/占位），TTS 走外部 API 且失败降级字幕。

## D-08 Demo 论文来源
- **决策**：3 份 Demo 论文（计算机视觉 / 网络安全 / 教育 AI），内容与全部图/表/SVG 均为**项目自绘原创**，避免版权与原创边界问题。
- **背景**：Spec §2 需要 3 篇授权明确的公开论文用于现场；但直接用真实论文的图像会带来版权/原始性举证问题，且规格强调原创知识产权。
- **结论**：Demo = 自绘原创论文（虚构但自洽、学术可信），Live = 用户上传真实 PDF（真实解析管线）。

## D-09 评估指标口径
- **决策**：ResearchLens Quality Score = Citation Coverage / Claim-Evidence Alignment / Unsupported Claim Rate / Structure Extraction Accuracy / Visual Consistency / Answer Grounding。其中 Unsupported Claim Rate 目标≈0。
- **背景**：Spec §21/§22；借鉴 Gen-Verse/Paper2Video 的评测维度但重写口径，针对「证据驱动」。
- **结论**：/api/evaluation 真算结果（对 demo 用其内部真实断言-证据链接计数），不编造数字；文档标注测算对象口径。

## D-10 仓库形态
- **决策**：/backend + /frontend 两个独立目录（各自独立包管理），不用 monorepo workspace。Docker 各自构建。
- **背景**：降低构建复杂度，避免 pnpm workspace / 版本提升带来的连锁问题；让后端可用 uv、前端可用 npm 独立跑。
- **结论**：目录清晰 + 各自 Dockerfile + root docker-compose.yml 一键编排。

## D-11 前端与后端通信
- **决策**：前端通过 `NEXT_PUBLIC_API_URL`（默认 http://localhost:8000）访问后端 REST；长任务用 SSE（/api/jobs/{id}/stream）。
- **背景**：前端要真实绑定后端 API（用户强调「前端不要漏组件和 api 绑定」）。
- **结论**：所有视图均真实调用后端接口，DEMO 模式由后端提供 seed 数据，前端不做假数据。

## D-12 不引入的依赖
- **决策**：不要求 CUDA / Ollama / 本地模型 / ComfyUI / GPU；不整套嵌入 Dify；不使用需要 GPU 的 talking-head 链路；PyMuPDF(AGPL) 仅作可选依赖。
- **背景**：Spec §16 明确禁止要求 GPU/本地模型；§6.2 明确不采用 A6000 链路；OSS_REUSE §6 逐条记录理由。
- **结论**：主链路零 GPU、零本地模型、零 AGPL 硬依赖。

## D-13 media.legacy_no 唯一约束按 kind
- **决策**：`media` 表的唯一约束从 `(revision_id, legacy_no)` 改为 `(revision_id, kind, legacy_no)`（迁移 `0005`）。
- **背景**：Docker Postgres 实测——`build_media` 的计数器是**按 kind** 递增的（figures→1,2,3…；equations→1,2,3…），但约束是**全 revision 级**。于是同一 revision 只要有 1 张图 + 1 个公式，两者都取 `legacy_no=1`，INSERT 撞 `uq_media_revision_legacy_no`，**整个 media 阶段失败**（3 次重试全 500），连带 claims/verify/exhibits/qa 全部无法执行，前端只剩空数据。
- **取舍**：
  - 改约束（采纳）：与既有契约一致——§5.4 `legacy_no` 是喂给 legacy `figure_refs`/`table_refs` 的兼容编号；`schemas/adapters` 按 kind 分别收集这两个数组；legacy 旧表本就是 `figures.fig_no` 与 `tables.table_no` 两套独立编号；前端 `RichText` 分别用 `fig_no`/`table_no` 查找。**图1 与 表1 必须能共存**。
  - 改成全局单序列（否决）：会让第一篇论文的第一张表显示成「表 2」（若之前已有 1 张图），与 legacy 展示不符。
  - 去掉 DB 唯一约束（否决）：丢失真实不变量，重号无法被拦截。
  - 新约束比旧约束**更宽松**（旧成立 ⇒ 新必成立），现存数据无需回填，迁移可原地完成。
- **结论**：约束含 `kind`；新增迁移 `0005_media_legacy_no_per_kind.py`，ORM 与 `migrations/helpers.py` 同步；回归测试 `test_build_media_numbers_legacy_no_per_kind` 锁定「图1/表1/公式1 同 revision 共存」。
- **同源缺陷（一并记录）**：`visual/repository.next_legacy_no(db, revision_id, kind)` 是**按 kind** 分配编号的既有helper，但**从未被 `build_media` 调用**（`build_media` 自己另写了一套同样的按 kind 计数器）——此前的接线遗漏与语义不一致是本缺陷的直接土壤。

## D-14 讲解归属：确定性标题分节 + 断言不得跨场景复制
- **决策**：section 一律由**原文一级标题确定性分节**产生（带块区间）；讲解的场景归属改为**分区**（每条已验证 claim 至多属一个场景），并保留"无归属线索时并入单个兜底场景"。LLM 结构产物只采纳其 `map`/`method_steps`，**不再采纳其 sections**。
- **背景**：3 篇真实论文实测"讲解乱"——paper 3 的 6 个场景**每个都塞进全部 15 条断言**、summary 也完全相同。根因是三连击：① `_structure_with_llm` 产出的 section 既无 `source_block_ids` 也无 `summary.spans`（qwen-plus 在 strict json_schema 下只填有把握的字段），`has_link_clue=False`；② `_section_kind` 只认英文关键词，"1 引言"/"5 实验与结果分析"等中文标题全被归为默认 `intro`；③ `_scene_from_section` 的兜底分支 `picked = all claim_rows` 把全部断言灌进**每一个** section。
- **另发现（同源）**：`claims/repository.get_block_rows` 用 `order_by(page_id)` 排序，而 `page_id` 是 UUID 字符串——这是**随机顺序**而非文档顺序，任何依赖块顺序的分节都不可靠。已改为 join `pages` 按 `pdf_page_index, ordinal` 排序。
- **取舍**：
  - 保留 LLM 的 section（否决）：模型给的 block_id/claim_ids 实测对不上，section 丢失块级归属，正是缺陷来源；真实论文的一级标题本就比模型改写更权威。
  - 让无归属的断言"就留在空场景"（部分采纳）：空场景保留（契约允许且测试依赖），但**绝不复制**到多个场景。
  - 兜底把剩余断言复制到每个场景（否决）：这就是"乱"本身。
  - 兜底新建"未归属"场景（否决）：会让场景标题脱离原文结构；改为并入**最后一个有内容的场景**并记 `unassigned_claims_fallback` 警告。
- **结论**：`scene/service.py` 的场景归属硬不变式为"**一条断言最多出现在一个场景**"；`claims/service.py` 新增 `heading_body()`/`infer_section_kind()`/`_sections_from_headings()`/`_summary_for_blocks()`。回归测试 `test_scene_attribution.py`（4 条）与 `test_structure_sections.py`（4 条）锁定不变式。注：`scene/service._section_kind` 与 `claims/service._SECTION_KIND_TOKENS` 各存一份等价关键词表（避免 M09 反向依赖 M06 内部实现），改动需同步。

## D-15 讲解持久化：不双写 legacy `scenes`/`narrations` 表
- **决策**：讲解只持久化在 canonical `artifact_blobs(kind='presentation')`；**不**回写 legacy `scenes`/`narrations` 表。
- **背景**：任务清单把"`narrations` 表 = 0"当作"讲解从没生成"。查证后发现前提不成立：`narrations` 是迁移 `0001_legacy_baseline` 的 legacy 表，全仓库**只有** `app/seed/demo_papers.py` 写 `scenes`（paper 4/5/6 的 18 行演示数据）且**从不写 `narrations`**，也没有任何代码读它；`scenes=18 但 narrations=0` 是拿 demo 表与另一个 legacy 表比较。3 篇真实论文的讲解**已经生成并落库**（`scene.build → put_presentation_blob`），`/api/papers/{id}/presentation` 与前端 `PresenterView` 均从该路径正常取到 script/subtitle/cues。
- **取舍**：
  - 双写 legacy 表（否决）：破坏 canonical 单一事实源，与 REFACTOR_SPEC §5.5「narration 是 `SceneRecord` 的字段」相悖，且引入双写不一致风险。
  - 修 `narrations` 表的写入（否决）：它没有消费者，属于给死表续命。
  - 只修真实存在的"讲解内容错乱"（采纳）：见 D-14。
- **结论**：legacy `scenes`/`narrations`/`claims`/`evidences`/`graph_nodes`/`graph_edges` 均为 0001 基线表，仅承载 demo 数据与兼容投影，**不作为真实论文的事实来源**。已在本文档记录以免后续再次误判。

## D-16 LLM 超时必须按请求下发（client 缓存不得吞掉超时）
- **决策**：`chat_once`/`embeddings_once` 把各自的超时**按请求**传给 `client.post(timeout=...)`；`get_client` 的 `timeout` 参数只决定新建 client 的默认值，命中缓存时不生效（并在 docstring 中写明）。
- **背景**：paper 1（Haar 隐写）claims 抽取连续 3 次 ReadTimeout，而 paper 2/3 正文更长却成功。表面上 `chat_once` 已声明 300s，实际**从未生效**：`get_client` 只用 `base_url` 做缓存 key，命中缓存时整个 client 构造（含 `timeout`）被跳过。`index` 阶段（embeddings，60s）永远紧挨在 `claims` 阶段（chat，300s）之前，且是该进程内对 dashscope 的**第一次**调用 → 60s client 被永久缓存。决定性证据：job 1/4/5 的 claims 阶段耗时 360.95/360.82/360.82s，精确等于 `MAX_ATTEMPTS(3) × json_schema + 3 × json_object = 6 × 60s`（抖动 ±0.13s）；若 300s 生效则不可能恰好 360.8s。paper 1 文本经全量扫描**无任何病理**（控制字符/U+FFFD/零宽/base64/最长数字串 8 位/最长块 1086 字符，均为三篇中最小最干净），且三篇进入 corpus 的字符数基本一致（15.2K/14.3K/15.0K）。
- **取舍**：
  - 只把 300s 调更大（否决）：缓存 bug 未修时**完全无效**。
  - 缓存 key 改为 `(base_url, timeout)`（否决）：可行但会按超时值分裂连接池；按请求下发更直接且保留连接复用。
  - 流式（stream=True）（暂缓）：最稳但改造面大，且与 `response_format` 兼容性需实测；本次先修根因。
  - 文本切块更小 / 换模型 / 预清洗（否决）：均未触及根因，且扫描已排除文本问题。
- **结论**：新增 `_request_timeout()` 助手；回归测试 `test_ai_transport.py`（4 条）锁死"按请求传超时"与"缓存 client 不得覆盖"。**同源缺陷（一并记录）**：`claims/service._call_extraction` 丢弃了 `CompletionResult` 的 `mode`/`attempts`/warnings，且云调用失败被 `except Exception` 吞成 warning → stage 只报 `partial`、`jobs.error` 恒为 NULL，硬失败在 job 级别静默（paper 1 就是这样"悄悄"失败 3 次的）。该可观测性缺陷**尚未修复**，见"待办"。

## D-17 媒体绑定：只承认可复核的两类关联
- **决策**：新增 `evidence.bind_media_for_statements()` 并在 `stage_exhibits` 中于 `scene.build` **之前**调用；只生成两类 `relation=illustrates, state=verified` 的绑定：`explicit_block_ref`（陈述显式写出 图/表/式 编号且**整号 + 同 kind** 命中）与 `caption_ref`（陈述与 caption 共享 ≥2 个 token 且其中至少一个为**区分性** token——含数字/连字符或全大写缩写，如 `F1-score`/`MAE`/`FPA`）。单条陈述最多绑定 `CAPTION_REF_MAX_PER_STATEMENT=2` 个媒体。
- **背景**：`bindings` 表恒为 0 行——`evidence.bind()` 本身完整可用（含 verified 的关系约束校验），但 **pipeline 从不调用它**。于是 `scene → verified statement → Claim/Evidence → verified Binding → Media` 这条 REFACTOR_SPEC §5.5/§523 规定的**唯一合法**媒体通道永远走不通，讲解挂不上任何图表。3 篇真实论文中只有 1 条陈述显式写出图表编号（"Table 10 reports both PDM…"），所以纯显式匹配过于稀疏，需要 caption 通道补充。
- **取舍**：
  - 只用显式编号引用（部分采纳）：精度最高但几乎无产出（全库 1 条），达不到"图表关联可展示"。
  - 同页图表全部绑定（否决）：规格明令"不用同页全部图表填满"。
  - caption 重叠阈值放宽到 1 个 token（否决）：会把泛化词（image/comparison/result）算成证据，直接制造"乱"。故要求 ≥2 token 且至少一个是区分性 token。
  - `caption_ref` 标 `candidate`（否决）：scene 的受控通道只接受 `state=verified`，标 candidate 等于白做；且 `caption_ref` 本就是契约 `Binding.method` 的合法取值，非"legacy 候选"。
  - 用 `original_label` 做匹配键（否决）：实测存在重复值且无唯一约束；改用 `normalize_media_label()`（同时登记原始编号与 legacy_no 派生别名）。
- **结论**：绑定 id 由 `(revision, statement, media)` 派生（≤36 字符）→ 幂等，重复运行只更新不新增。回归测试 `test_media_binding.py`（10 条）覆盖两类通道、kind 不匹配不绑、单 token 不绑、未验证不绑、幂等、上限、以及"绑定后场景才挂得上媒体"的端到端不变式。

## D-18 媒体候选质量：caption 归属切分 + 装饰性空图过滤（P0 子集）
- **决策**：在 `normalize.build_media_candidates`（落库前的候选列表变换）做两件事：① 把粘连的 caption 按"**不同 (kind, 编号)** 标记"切分，只保留属于本对象的那一段；② 对 `kind=figure` 且 **caption 为空 且 归一化面积 < 2%** 的候选置 `excluded=True` + `exclusion_reason`。同时修正 MinerU 的 `bbox_units` 声明为 `normalized`。
- **背景**：3 篇真实论文实测——① MinerU 的 `image_caption`/`table_caption` 是**数组**，`mineru_adapter._as_text()` 用 `" ".join` 整串拼接，于是相邻对象的 caption 粘成一条（实测 2 行：`图 9…图 10…`、`Table 2…Table 1…表 1…`）；② 16 行 caption 为空，其中 15 行渲染确认是二维码/作者证件照，面积仅占页面 0.60%–0.68%；③ 823 个块声明 `bbox_units="pixel"`，但实测 x1/y1 最大 991/998、最小 122，与 MinerU 官方"0–1000 归一化网格"一致，且 MinerU 成功路径从不填 `pages.width_pt`（恒为 1.0），故任何"像素 ÷ 页面尺寸"的裁剪计算都是错的。
- **取舍**：
  - 切分规则用"编号不同才切"（采纳）：同编号的中英双语（`Fig.1 … 图 1 …`，实测 10 行）与子图/父图（`图 8(a)` 与 `图 8`）必须保留；用"见到标记就切"会把双语 caption 砍掉一半。子图后缀归一到父编号后再比较。
  - 装饰图判据取 **caption 为空 ∧ 面积 < 2%** 的**交集**（采纳）：只用"caption 为空"会误删 paper 3 里丢了 caption 的**真图**（`677e3596…`，面积 4.8%）；只用"面积小"会误删 paper 1 图 1 的 **6 个并排面板**（0.82%–0.85%，都带 caption）。2% 落在实测的 0.68%（装饰）与 4.8%（真图）之间。
  - 表格不参与该过滤（采纳）：表格缺 caption 是另一种情况，不应按图片装饰性处理。
  - 无 bbox 不删（采纳）：判不了面积就不动手，宁可保留也不凭猜删。
  - **按 bbox 几何重关联 caption↔body（暂缓，未实现）**：数据上可行（bbox 完整留在 `blocks.raw_ref` 与 `parser_raw` asset，且 `blocks↔media` 已验证可按 `(kind, page, ordinal)` 1:1 对齐全部 55 条 figure/table），但风险中等——paper 3 第 14 页的图 6/图 7、第 17 页的图 10/图 11 是**两个不同图在同一 y 并排**，纯几何会把它们并成一张；必须先切分拼接串再用"caption 自带的新图号"判定归属。
  - **子图聚类合并（否决）**：`REFACTOR_SPEC.md:480` 明确"子图可以共享父图资产但有不同 Media/Anchor"，且 schema 无 `parent_media_id`；强行合并会丢面板身份，且 `legacy_no` 是下游匹配别名（`legacy_resolver` 把 `图{legacy_no}`/`fig_{legacy_no}` 全登记为别名），合并会让被并掉的编号从 `figure_refs` 消失、已有引用降级为 unresolved——按规格属"改变已发布事实"。
  - **双语去重（已实现，见 D-21）**：原计划需契约+迁移才无损，本轮已补 `media.caption_alt`（迁移 0006）实现无损拆分。
  - **子图聚类（已实现父图编号补全，见 D-21）**：不合并行（REFACTOR_SPEC §480 要求子图保持独立 Media），改为给缺号的面板补上父图编号。
- **结论**：两处改动都在**落库前**做"列表→列表"变换，`legacy_no` 仍由 `visual.build_media` 的按 kind 计数器重新稠密分配 → 与 `uq_media_revision_kind_legacy_no` 不冲突；**绝不**用落库后的 UPDATE/DELETE 重编号补丁（那正是迁移 0005 注释记录的"3 次重试全 500"那类失败）。回归测试 `test_normalize_media_quality.py`（10 条）。
- **同源缺陷（一并记录，未修复）**：
  - **图片字节从未落盘**：74 条 media 的 `original_asset_ids` 去重后只指向 3 个 asset，全是 `parser_raw`（`mime=application/json`）——`normalize.py` 的 `embedded_asset_id=raw_asset_id` 让 `visual/service.py` 把 JSON 当"MinerU 提取图"，而 ZIP 里的 `images/` 与 `image_blocks[].img_path` 全项目**零读取**。前端因此拿到的是 JSON 而不是图片。这是 D 项最严重的遗留问题。
  - `visual/service.py:_extracted_for` 在缺 `extracted` 时用 `table_html=candidate.caption` 造"提取表格"（把 caption 当 HTML 用）。
  - `normalize._refine_kind` 把"以 图/表 开头的正文段落"标成 `kind='caption'`（paper 3 实测 8 条），任何"用 `blocks.kind='caption'` 做关联"的设计都会被误导。
  - `_EQUATION_LABEL_RE` 要求以 `(N)` 结尾，而 MinerU 给 `\tag{N}` → 22 条 equation 的 `original_label` 全为 NULL。

## D-19 空场景过滤 + 遗留缺口登记（图谱边 / method_steps / 图字节）
- **决策（空场景过滤）**：`_plan_scenes` 丢弃**没有任何已验证陈述**的场景；若全部为空则保留第一个，保证 `PresentationArtifact.scenes` 不为空列表、前端有可渲染项。保留后 `order` 重新连续编号。
- **背景**：真实数据里断言多来自摘要/结果章，方法/背景章常常无断言。修复归属后实测：paper 1 有 7 个章节但只有 2 个有断言（4+1 条），paper 3 有 9 个章节只有 2 个有断言（7+6 条）。若不过滤，讲解器会出现 5–7 个空场景，观众侧等同"打不开/空白"。
- **取舍**：保留空场景（否决）——虽然"如实呈现章节结构"，但对展项是纯噪音，且 `scene_without_verified_statement` 警告在每个空场景重复；全部为空时返回空列表（否决）——会让前端没有任何可渲染项。
- **结论**：新增回归测试 `TestEmptySceneFiltering`（2 条）；实测三篇论文的讲解均为 2 个有内容的场景，断言零重复。

### 遗留缺口（本轮**未**修复，供后续版本登账）
| 缺口 | 证据 | 影响 | 建议 |
|---|---|---|---|
| **图谱只有节点、没有边**（`graph_edges=0`） | `graph/service._build_edges` 只消费 `from_kind="claim"` 的绑定；而 `_target_node_id` 对 `to_kind="media"` 会返回 `n:media:*`，但 `build()` **从不把 media 节点加进 `node_ids`** → 即使有绑定也会以 `edge_endpoint_missing` 被丢弃。且 `NodeKind` 字面量**不含 `media`**（`contracts/graph.py:11`），前端 `GraphView.tsx` 的 `KIND_X`/`NODE_KIND_LABEL` 也没有 `media` 键。 | 三篇论文图谱均为 `nodes=9/14/15, edges=0`，图看着是散点而非"图谱" | ✅ **已在 D-20 修复**：statement 级绑定经 `statement→claim` 归约成边，media 节点入图，`NodeKind` 与前端三处补齐。实测 paper 3 得 `edges=2`（claim→表10/表11，均 verified）。 |
| **paper 3 `method_steps=0`** | 其 15 条 claim 的 `type` **全部是 `RESULT`**（paper 1/2 有 METHOD 类型故有 4 条） | `/api/papers/3` 的 `method_steps` 为空数组 | 属数据真实情况（模型没抽到 METHOD 类断言），非代码缺陷；若要补，应在 claims prompt 层强化 METHOD 召回，而不是在结构层编造步骤。 |
| **图片字节从未落盘**（D-18 已记录） | 74 条 media 只引用 3 个 `parser_raw` JSON asset | 前端拿到的"图"是 JSON 而非图片；论文无 OCR/期刊图，无法绕过 | 需在 MinerU 适配层读取 ZIP `images/` 或 `img_path` 并落为 image asset，属独立较大改动。 |
| **C 项因果仍需谨慎表述** | 传输层缓存 bug 已由直接实验证明（请求 300s 拿回 60s）且 3 次失败恰为 6×60s；但修复后 paper 1 抽取**成功且耗时 52s（<旧 60s 上限）** | 无法断言原 3 次失败**仅仅**由 60s 上限导致——当时 dashscope 侧同时段"请求挂起"也能产生同样的 6×60s 形状 | 结论**保守表述**：60s 上限是**已证实的真实缺陷**且已被修掉；paper 1 现在稳定产出 9 条 claim。若要彻底归因，需在受控条件下复现旧代码。 |

## D-20 图谱连通：statement 级绑定归约 + media 节点入图
- **决策**：`graph.build()` 同时消费 `from_kind="claim"` 与 `from_kind="statement"` 两类绑定；statement 级绑定经 `statement_to_claim` 归约到所属 claim 节点；为绑定目标补 **media 节点**（在 `_build_edges` 之前入 `node_ids`）；`NodeKind` 增加 `media`、`GraphNodeRecord` 增加 `media_id`；前端 `GraphView` 的 `KIND_X`/`KIND_COLOR`/`NODE_KIND_LABEL`/图例/图标补齐 `media`。`ALGORITHM_VERSION` 升到 `rl.graph/3`。
- **背景**：3 篇真实论文图谱均为 `nodes>0 / edges=0`——图是散点不是图谱。两层根因：① M04 的媒体绑定挂 `statement` 而 `_build_edges` 只认 `claim`，绑定根本没被图看见；② 即便看见，`build()` 从不把 media 节点加入 `node_ids`，`_target_node_id` 返回的 `n:media:*` 必然落入 `edge_endpoint_missing`。
- **取舍**：
  - 把 M04 绑定改成 `from_kind="claim"`（否决）：会丢掉"绑定挂在具体陈述"这一更精确的出处；改为在图侧归约，M04 语义不动。
  - 改从 claim→evidence 的 `supports` 边取内容（暂缓）：`bind()` 要求 verified supports 必须带 `validation_id` 且报告 `semantic_status` 为 supports，需把 M04 的 validation 接到绑定阶段——是独立的一块工作，且当前 evidence 绑定尚未生成。
  - 合并或丢弃无绑定的孤立节点（否决）：规格要求孤立/候选/争议节点保留明确状态。**无绑定即无边**这一硬约束不变。
- **结论**：实测 paper 3 得 `nodes=17`（15 claim + 2 media）、`edges=2`，两条边均为 `illustrates/verified` 且语义正确（`RFR_best_overall_regression_mode → 表 11 MAE/FPA`、`defect_type_F1_correlates_with_P → 表 10 PDM/F1-score`）；paper 1/2 因无绑定仍为 `edges=0`（如实，非缺陷）。回归测试 `test_graph_binding_edges.py`（5 条）锁定：statement/claim 两级绑定都成边、candidate 不升级、无绑定无边、所有边端点必在图中（悬空目标被丢弃）。

## D-21 媒体后处理：双语无损拆分 + 子图父编号补全
- **决策**：① 新增 `media.caption_alt`（迁移 `0006`，纯新增可空列 + `server_default=''`，expand 阶段、无需回填）与契约字段 `Media.caption_alt` / `ParsedMediaCandidate.caption_alt`；`normalize.split_bilingual_caption()` 把"同一对象的中英双语 caption"按语言拆成 `caption`（文档主导语言）与 `caption_alt`（另一语言，**无损保留**）。② `normalize._assign_subfigure_parents()` 给"只有面板标记 `(a)`、自身无 `图 N`"的候选补上父图编号（**只改 `original_label`，不合并行**）。
- **背景**：实测 10 行是**行内拼接**的中英双语 caption（不是两条独立行）；子图面板中只有最后一块带父图号，其余 `original_label=NULL`，在讲解/图谱里是无主孤儿。
- **取舍**：
  - 直接丢掉另一语言（否决）：丢信息，且违反 spec"不丢原始信息"。
  - 双语都留在 `caption`（否决）：就是"同表双语重复"这个症状本身。
  - **主语言判据用首页而非全文**（采纳）：全文统计会误判——真实中文论文的参考文献与公式让拉丁字母数反超汉字（实测 paper 3：CJK 17714 vs Latin 19491），据此会把中文论文判成英文；只看首页（题名/摘要）则稳定为中文。
  - 子图**合并成一行**（否决）：REFACTOR_SPEC §480 明确"子图可以共享父图资产但有不同 Media/Anchor"，且 schema 无 `parent_media_id`；合并还会让被并掉的 `legacy_no` 从 `figure_refs` 消失（属"改变已发布事实"）。
  - 子图按"同页同 y"几何聚类（否决）：paper 3 第 14 页的图 6/图 7、第 17 页的图 10/图 11 是**两个不同图并排**，纯几何会误并；改为**文本优先**——只有 caption 以 `(a)` 这类面板标记开头、且自身无编号的候选才去认亲，父图必须是自带完整编号的兄弟（几何仅用于"同一行"判定）。
- **结论**：迁移 0006 已在 Docker 实测应用成功（`alembic_version=0006`，`media.caption_alt` 存在，后端健康）。回归测试 `test_normalize_media_quality.py` 扩到 18 条，覆盖：中文论文取中文为主语言且英文进 `caption_alt`、单语言不误切、短拉丁串（`Fig.1`）不触发拆分、面板继承父编号、**两个不同图并排不互相认亲**、找不到父图不凭空编号。

## D-22 断言抽取语料：按章节公平分配（**不**靠加大预算）
- **决策**：`_build_corpus` 改为**按原文一级标题分章节、公平分配预算**：每节份额 = `min(PER_SECTION_CHAR_BUDGET, 剩余预算 / 剩余节数)`；节内超份额时**均匀取样**（标题块优先保留、正文首末块必取）；被截断的章节**逐一点名**（`section_truncated`）。参考文献/致谢章节**不参与分配**。`TOTAL_CHAR_BUDGET` **保持 16000**（作为**单次调用**预算）。另新增**重抽取路径** `claims.reextract()` + `repository.delete_claim_artifacts()`。
- **背景**：fresh seed 后实测——`_build_corpus` 按文档顺序累加到 16000 字符就 `break`，等于**只读头部**：paper 1/2/3 分别只有 66%/43%/29% 正文进入模型，**paper 3 只覆盖第 0..6 页（共 25 页），方法章与实验章完全缺席**，直接导致 `method_steps=0`、只有 1 个场景。而代码自己的意图是「预算内的原文块读取（按章节分配，不只读头尾）」（`claims/repository.py` 模块注释），`PER_SECTION_CHAR_BUDGET=6000` 也早已定义却**从未被使用**，且 6 节 × 6000 = 36000 与 `TOTAL_CHAR_BUDGET=16000` 自相矛盾——实现漏了文档里的意图。
- **取舍（含一次被实测推翻的推荐）**：
  - **把总预算提到 48000（先推荐、后被否决）**：我看到"每节 6000 与总量 16000 矛盾"就推荐 48000，**但没先读那个常量的理由**。`prompts.py` 原注释写着"实测 48000 时 quotes 被省略"。我做 A/B 对照实验（同一 revision、同一提示词，只改预算）：

    | 总预算 | 语料字符 | 产出 claim | 带 quote | **quote 真正匹配原文** | 耗时 |
    |---|---|---|---|---|---|
    | 16000 | 16070 | 7 | 7 | **7（100%）** | 31.7s |
    | 48000 | 48243 | 5 | 5 | **1（20%）** | 112.5s |

    原注释的**机制**猜错了（`min_length=1` 已修掉"省略字段"），但**结论正确**——48000 下模型仍给 quote，只是绝大多数是改写/幻觉，逐字命中率从 100% 掉到 20%，被 `quote_not_in_block` 丢弃后 citations 空、gate 全拒；且慢 3.5 倍。**故 48000 被否决：预算维持 16000，改为把这 16000 按章节重分配**。
  - 分块多次调用（**暂缓**）：每次调用 ≤16000（已验证可靠）按章节分块调用后合并去重，可做到"每节完整"而非"每节取样"；代价约 4 次调用/篇、~120s，且需额外写合并/去重/调用预算逻辑。留作后续。
  - 参考文献占用预算（否决）：实测 paper 1/2/3 的 `References:` 各被分走 12/16/9 块（约 10% 预算），产生不了断言还会诱发模型引用文献。
  - 靠幂等 upsert 重跑（否决）：`upsert_claim` 键为 `(revision_id, claim_id)`、claim_id 由**模型输出**决定 → 换语料必然产生新 id，旧行**残留成孤儿**。故必须显式清理，且清理范围精确到断言派生表，不碰 pages/blocks/media。
- **结论**：实测重抽取三篇（`reextract` → `stage_verify` → `stage_exhibits`）：
  - **paper 3 断言引用从第 0–2 页扩到第 0/2/9/13/16/17/18 页**（共 25 页），**场景 1 → 4 个**（引言 5 条 / 方法 1 条 / 实验设计与结果分析 4 条含 1 张表 / 有效性分析 1 条），**方法章首次出现**；claims 7 → 12，已验证陈述 7 → 11。
  - paper 2 claims 10 → 14、已验证 5 → 11、`method_steps` 1 → 3，引用页 2–12。
  - paper 1 引用页扩到 0–8，但 claims 10 → 6、已验证 5 → 2（**单次 LLM 调用方差大**：本轮会话 paper 1 先后跑出 9 / 10 / 6 条；覆盖变宽是真实的，条数波动不是分配器造成的）。
  - 合计：已验证陈述 17 → 24，场景 1/3/1 → 2/3/4。
  - 新警告 `section_truncated` / `reextract_reset` 让"哪节被截""清了什么"可见——这次缺陷不可见正是因为缺这个信号。
  - 回归测试 `test_corpus_allocation.py`（12 条）+ `test_reextract.py`（5 条）；全量 **314 passed**。
- **同源缺口（一并记录，未修）**：`_draft_batch_from_raw` 对**空 quote** 是 `continue` 静默丢弃（无警告），所以"模型没给引用"这类失败在 warning 里看不到——这正是原作者只能靠手工发现 48000 问题的原因。建议补 `quote_missing` 警告计数。**（已修，见 D-26）**

## D-23 artifact_blobs.kind 加宽到 128：修 `/pages/{n}/preview` 全 500
- **决策**：`artifact_blobs.kind` 由 `varchar(32)` 加宽到 `varchar(128)`（迁移 `0007`），并补一条**长度契约回归测试**。
- **背景**：`/api/papers/{id}/pages/{n}/preview` **全部 500**。根因：`visual.ensure_page_preview` 用 `f"page_preview:{cache_key}"` 当 `kind`，而 `cache_key` 是 `preview_cache_key()` 的 **64 位 sha256 hex** → `13+1+64=78 > 32`，Postgres 报 `StringDataRightTruncation`：渲染成功但缓存写入失败、异常逃逸成 500。阅读器的页面图因此完全不可用（实测 51 页全废）。
- **取舍**：
  - 缩短缓存键（如取 hash 前 24 位）（否决）：要截断内容哈希，且 `kind` 仍被当成"判别符 + 缓存键"混用。
  - 把缓存键挪到 `payload`、`kind` 只用 `'page_preview'`（否决）：`uq_artifact_revision_kind` 唯一约束按 `(revision_id, kind)`，同 revision 多页会互撞——现有设计正是靠把缓存键编进 `kind` 才让每页独立。
  - **加宽列**（采纳）：纯 expand，旧值必然合法、无需回填，Postgres 下不重写表。
- **结论**：迁移 0007 实测应用（`alembic_version=0007`、`kind`=128），预览由 **500 → 200 `image/png`**（278–398KB/页）。回归测试 `test_page_preview_cache.py` 用"组合出的 kind 长度 ≤ 列声明长度"断言，**把这一类"列太窄 + 只有 Postgres 报错"的缺陷变成 SQLite 也能拦住的测试**（SQLite 不校验 VARCHAR 长度，所以此前单测永远发现不了）。

## D-24 图表字节：MinerU 提取图落成 asset，media 不再指向 parser_raw JSON
- **决策**：`RawBlock` 增加 `img_path` / `image_asset_id`，`RawDocument` 增加 `images`（ZIP 解包出的图片字节）；新增 `parse.service._persist_media_images()` 把图字节落成 `AssetKind="crop"` 的 asset 并回填 asset id；`normalize.build_media_candidates` 的 `embedded_asset_id` **只取真实图资产，绝不回退成 `raw_asset_id`**；`_persist_raw_asset`/`_raw_document_from_payload` 增加这两个字段以保持**重放一致**。
- **背景**：前端拿到的"图"其实是 **JSON**。`GET /api/papers/3/media/{figure}` → `GET /api/assets/{id}` 返回 `application/json` 161KB。成因链：ZIP 里的 `images/` 被 `safe_extract` 收进 `archive.images` 后**无人读取**；`img_path` 只进 `RawPage.image_blocks` 这个旁路字典，而 `build_media_candidates` 读的是 `RawBlock`，两边对不上；于是用 `raw_asset_id`（parser_raw）顶替"MinerU 提取图"。实测 `assets` 表图/裁剪类资产 **0 条**。
- **取舍**：
  - 适配器直接落库（否决）：适配器无 `scope`、不应碰 DB；改为适配器只传纯数据（`img_path` + `images`），落库放 `parse()`（有 scope、能调 papers）。
  - 新增 `AssetKind="image"`（否决）：契约 `AssetKind` 已有 `crop`（与 PyMuPDF 渲染的 `pdf_crop` 同一类），复用现成字面量比扩契约更小改动。
  - 让表格继续挂 `parser_raw` JSON（否决）：那是把 JSON 当图渲染；表格本就走 `extracted.table_html`（实测 `extracted_html=True`）。
  - `sniff_mime` 只认 PDF（顺手补）：加 PNG/JPEG/GIF/WebP 魔数识别，否则资产 MIME 只能是 `application/octet-stream`。
- **结论**：fresh seed 后 `assets` 出现 **39 个 `crop` 资产（786KB）**；实测 media 的图资产返回 **`image/jpeg`**（paper 1 9 张 / paper 2 3 张 / paper 3 12 张）。回归测试 `test_media_image_assets.py`（8 条）锁死：适配器必须交出 `img_path` 与 `images`、落库幂等、缺字节不崩、**没有真图时 `embedded_asset_id` 必须为 None（不得拿 JSON 冒充图）**、重放保持 `image_asset_id`。

## D-25 语料排除页码/页眉/页脚（并修好 paper 1 讲解为空）
- **决策**：`claims.service._nonblank` 过滤 `_NON_EVIDENCE_KINDS = {header, footer, page_number, page_footnote}`，这些块不进入抽取语料；**标题块保留**（提供章节上下文）。
- **背景**：实测它们占掉 paper 1/2/3 语料的 **22%(17/77)/24%/21%** 预算，而且**永远不可能成为断言的一级依据**。更糟的是模型会**引用页码或论文标题当证据**——fresh seed 实测 paper 1 的 6 条 claim 全部被 gate 以 `semantic_status=insufficient` 拒掉、讲解为空；抽查引用可见其中一条引用的竟是**论文标题块**。
- **取舍**：连标题一起去掉（否决）——标题给模型章节上下文；放宽 gate 让标题引用通过（否决）——违背"宁缺勿造"，标题不能支撑事实断言。
- **结论**：过滤后 paper 1 的 `quote_not_in_block` 警告消失、**5/5 claim 通过验证**；讲解从「1 个空场景」变为「2 个场景（问题 2 条 + 实验 3 条，脚本 297+442 字）、4 条图边、挂 3 张图」，`method_steps` 由 0 变 1。回归测试 `test_corpus_allocation.py::TestNonEvidenceFurniture`（3 条）。

## D-26 引用定位复用 M04 locator（+ 补"空白无关"一档与 `quote_missing`）
- **决策**：`locator.match_quote` 抽出文本版 `match_quote_text(block_id, text, proposed_quote)`；M06 的 `_draft_batch_from_raw` 改用它（不再自己做 `quote not in text`）。新增 "2b) 空白无关"匹配档：规范化后去掉**所有**空白再找，命中后经紧凑索引 + offset map **回填原文真实切片**。空引用改为显式 `quote_missing` 警告。
- **背景**：实测 paper 2 一轮抽出 12 条 claim，其中 **8 条**的 validation 是 `unsupported_entailment / 证据原文为空` —— 引用在抽取阶段就被丢光。根因是 M06 用了**精确子串**判断，而 MinerU 排版会在符号间插空格（`f _ {W B} = \frac {1}{3}`）、混用全角、拆开连字，模型复述几乎不可能逐字复现。**M04 的 locator 早就有 精确→规范化→模糊 三级匹配，M06 没有复用**。
- **取舍**：放宽到"模糊相似即接受"（否决）——`match_quote` 的 fuzzy 档**只产生候选、绝不伪造精确 quote**，这条纪律必须守住，否则为了通过率把错误证据放进正文正是"乱"的来源；只做规范化（部分采纳为 2a）——救得了全角/连字/大小写，救不了符号间空格，故补 2b。
- **结论**：回归测试 `test_quote_matching.py`（9 条）覆盖：精确命中回填原文切片、**空白变体必须命中且回填原文切片**、全角/连字命中、完全无关必须判缺失（不得放宽成"像就行"）、空引用报 `quote_missing`、未知块报 `unknown_block`。**注意**：paper 2 仍有 8 条 `quote_not_in_block` —— 那是模型**引错块/改写原文**，不是匹配过严；要改善需走"分块多次调用"（D-22 已登记）。

### D-26 附：`new_ctx()` 默认 120s deadline 的陷阱（已加显式告警）
排查中我一度把 paper 2「已验证陈述从 11 掉到 1」归因为**抽取质量方差**，实际是**deadline 陷阱**：`reextract` 要跑「一次抽取（~50–90s）+ 每条陈述一次语义判定」，而我用的是 `new_ctx()`（默认 **120s**）；真实作业由 `pipeline.service` 按 `budget.max_wall_ms`（默认 **600s**）设置 deadline。120s 中途过期 → `evidence.semantic` 的模型判定全部降级为"未判定" → **所有 claim 变 unverified**。日志里是成片的 `semantic judge 调用失败，降级为未判定：请求已超过全局 deadline`，但结果看起来就像"这篇论文没有可验证断言"。
- **已做**：`reextract` 在 deadline 过期时显式追加 `reextract_deadline_exceeded` 警告（回归测试 2 条），避免再次被误读为内容质量问题；并用作业级 deadline（900s）重测，paper 3 提到 15 条 claim / 9 条已验证 / 6 个场景。
- **未做（建议）**：`verify_and_store` 也应聚合报告"语义判定不可用"的条数；否则该陷阱在任何调用路径上都会伪装成"内容质量差"。

## D-27 路线 A：把 canonical 产物补进旧 DTO（图 / 论文地图 / 摘要）
- **决策**：走**路线 A**（先补旧投影 + 前端最小适配），暂不把前端改成读 canonical（路线 B 后续再做）。本轮落地三件：① `FigureOut` 新增 `image_url`，由 `papers.legacy.figure_image_url()` 从 `media.original_asset_ids[0]` 解析；② `map_summary` 由 canonical `structure.map.items` + 章节兜底投影（`map_summary_from_structure()`）；③ `abstract` 由首页正文按中英标记切出（`abstract_from_page_text()`）。前端新增 `lib/api.absoluteApiUrl()`，`FigureImage`/`SourceMedia` 渲染前把**相对**资源路径补成绝对 URL。
- **背景（实测 `/api/papers/1`）**：`map_summary = {}`、`abstract` 长度 0、`authors`/`tags` 为空、`figures[0] = {glyph_svg:"", image_b64:"", media_id:"5fd8…"}`。根因是这些字段取自 **legacy `papers` 表列**（真实论文全空），而 canonical 侧的结构/首页正文/图资产**没有被投影**。前端 `FigureImage` 只认内联 `image_b64`/`glyph_svg` → 真实论文"有摘要没图"；`MapView` 六个六维卡片读 `map_summary[key]` → 全渲染成 "—"。
- **取舍**：
  - 让后端直接返回**绝对** URL（否决）：`asset_url()` 刻意只给受控相对路径（不暴露磁盘、不绑定部署域名），公开域名属于前端配置。
  - 靠 Next.js rewrite 代理 `/api`（否决）：`next.config.mjs` 无 rewrite，加它会改变部署拓扑；前端集中拼一次更小。
  - `dataset`/`experiment` 两键 canonical map 里没有（canonical 只有 problem/method/result/limitation）→ 用**章节 kind/标题**兜底；仍无来源就**不给键**（前端显示 "—"），不编造。
  - 摘要标记**必须带冒号**：初版用 `摘\s*要`（无冒号）把正文普通词"没有**摘要**标记"误判成摘要头，单测抓到后已修。
- **结论**：实测 `/api/papers/1`：**9/9 图有 `image_url`**，绝对地址取图 **200 `image/jpeg` 4975B**；`map_summary` 得到 method/result/limitation/experiment 四键真实内容；`abstract` 329 字、正确切在"关键词"前。前端重建通过，`/`、`/paper/1`、`/paper/3` 均 200，bundle 已含新逻辑。回归测试 `test_legacy_detail_projection.py`（8 条）；全量 **346 passed**。
- **路线 A 剩余（未做）**：`method_steps[].detail` 为空、`figure_ref` 为 null（源头在 structure builder 未填 detail）；`authors`/`tags`/`year`/`domain` 未从首页派生；图谱 evidence 边（claim→evidence `supports` 绑定）未生成；**章节"跳到对应正文页"仍需给 PaperView 加页码定位**（现有导航是锚点制 `NavigationTarget = scope + anchor_id`，而真实论文的 `section_records.anchor_ids` 实测为空，所以只能走页码）。

## D-28 路线 A 第二批：章节真实正文 + 页范围 + 解析器转义清理
- **决策**：① `sections[]` 的 `body` 改为该节 `source_block_ids` 覆盖的**原文块文本**，`page` 改为真实起始页并新增 `page_start`/`page_end`；② 新增 `papers.legacy.clean_text_markup()` 清解析器留下的 markdown 转义与 NBSP，用于 `pages[].text`、章节 `body`/`summary`、图/表 caption；③ 前端 `MapView` 的章节正文改用 `MathText`（KaTeX）渲染，页码 badge 显示页范围。
- **背景**：实测 `sections[0].body === summary`（都是断言拼接）、7 个章节 `page` **全部是 1** → 前端"阅读该章节正文"永远跳到第 1 页；`pages[0].text` 里是 `…的 JPEG 隐写\*`、`黄牛 $^{1}$` 这类**未解转义**的原文，而 `MathText` 只处理 `$...$`，`\*` 会原样显示成"一堆没转义的字符"。另有 `page.tsx:388` 的 `onOpenSection={() => changeView('paper')}` **丢掉了 section 参数**，只切视图不跳页。
- **取舍**：
  - **不动 `$...$`**（关键）：前端 `MathText` 用 KaTeX 渲染行内/块级公式，若顺手把 `$` 清掉会**丢公式**；只解 markdown 转义。
  - `\*` **整段去掉**、其余转义**解转义**（`\_`→`_`）：星号在这些中文期刊里是标题/术语的强调或脚注标记，留成 `*` 反而像乱码；下划线在 `W_{u,v}` 这类标识里有义。首版把两者一律解转义，被单测断言抓出不一致后改成上述策略。
  - 章节无块可取时 `body` 退回 `summary`（否决"空正文"）：summary 是**已验证断言拼接**不是编造，而空正文会让章节看起来是坏的。
- **结论**：实测 `/api/papers/1`：7 个章节页范围分别为 `[1-3] [3-3] [3-5] [5-6] [6-9] [9-9] [9-10]`（此前恒为 1），`body` 与 `summary` **全部不同**（最长 6647 字真实正文）；`pages[0].text` 不再含 `\*`/NBSP 且 `$^{1}$` 保留。前端重建通过、`/`、`/paper/1` 均 200。回归测试 `test_legacy_detail_projection.py` 增至 **17 条**；全量 **355 passed**。







## D-29 章节 → 正文页定位：块级锚点回填 + 章节锚点派生 + 读路径自愈

- **决策**：① 解析期为每个块回填 `Block.anchor_id`（指向其所在页的页锚点）；② 分节期由本节块的锚点**派生** `SectionRecord.anchor_ids`；③ `claims/repository.get_structure` 对 `anchor_ids` 为空的历史数据**只读现算补齐**；④ 前端把 `onOpenSection` 真正接到锚点导航。
- **背景（Postgres 实测，这是"点了章节没跳到正文页"的根因）**：`blocks.anchor_id` **823/823 全为 NULL**；`section_records.anchor_ids` **21/21 全为 `[]`** → `manifest.section_index[].anchor_ids` 与 `exhibits.structure.sections[].anchor_ids` 都是空的。而 `jumpToPaper()` 依赖 `api.getAnchor(paper_id, anchor_id, revision_id)`，没有锚点就只能退化成"打开论文视图"，`page.tsx` 更是把 section 参数整个丢掉（`() => changeView('paper')`）。链路断点其实在最上游：`parse/service.py` 为每页构造了页锚点（`segments[0].block_ids` 列出该页全部块），却**从不回填反向指针**。
- **取舍**：
  - 用"页锚点"而不是"新建章节锚点"：`anchors` 里已有每页一个覆盖全区块的页锚点（实测 paper 1 第 0 页：1 个 23 块的页锚点 + 4 个单块 `anc-*` 证据锚点），语义正好是"整页"，复用它无需新增数据模型。
  - 同页多锚点时**取 `block_ids` 最多者**：单块证据锚点物理页相同，但页锚点更稳定、语义更准。
  - 读路径**只读补齐、绝不写库**：为了让显示层不必重跑昂贵的 LLM 抽取（3 篇论文的完整抽取是分钟级），补齐发生在投影阶段；显式写入的 `anchor_ids` 一律保留。
  - 块没有锚点时**留空、不伪造**（单测锁定）：宁可前端诚实报"无法定位"，也不给假锚点。
- **结论**：实测 3 篇论文 `manifest.section_index` 与 `exhibits.structure.sections` 的锚点覆盖 **7/7、5/5、9/9**，且每个锚点都能 `GET /anchors/{id}` 解析出 `pdf_page_index`。回归测试 `test_section_anchor_navigation.py`（8 条）。

## D-30 首页元信息派生：authors / tags / year / domain

- **决策**：新增 `papers.legacy` 的 `authors_from_page_text()` / `keywords_from_page_text()` / `year_from_page_text()` / `domain_from_page_text()`，由首页正文保守派生；覆盖策略抽成纯函数 `merge_front_matter()`：`authors`/`tags` **仅在 legacy 为空时**补，`year`/`domain` 派生到就覆盖。
- **背景（实测）**：3 篇真实论文 `authors=[]`、`tags=[]`、`year=2026`（**入库年份**，不是发表年）、`domain='general'`（等于没判）。这些信息首页正文里本来就有：中文期刊首页第 2 行是作者行（`黄炜 $^{1}$ ，赵险峰 $^{2}$`），摘要下方是"关键词"行，页脚是卷期年份。前端"论文地图"的署名行、标签行、领域行因此长期是空的或恒显示 "general"。
- **取舍**：
  - 作者行判定用**全行否决**：按 `,，、;` 切分后必须**每个**片段都像姓名（≤24 字符、只含汉字/字母/连字符、不含数字与括号），任何一段像单位/页眉就否决整行。**宁可返回空，也不要把"厦门大学"当作者**——错误元信息比缺失元信息更糟（单测含 4 条否定用例）。
  - 年份取首页**出现次数最多**的年份（页脚/版权重复出现），次数相同取更晚者；不取全篇 max（会把引用年份当发表年）。
  - 领域用关键词表，且**具体领域排在笼统领域之前**：Solidity 那篇摘要里有"智能合约**安全**问题"，若 `security` 在前就会把区块链论文判成安全论文（首版实测被单测抓出）。同理不收录裸"安全"。
  - 派生不到的键**不出现**，由调用方保留原值。
- **结论**：实测 paper 1 = `['黄炜','赵险峰'] / ['隐写','载体选择','Haar 小波','范数'] / 2018 / security`，paper 2 = 4 作者 / 5 标签 / 2020 / software-engineering，paper 3 = 6 作者 / 4 标签 / 2022 / blockchain。回归测试 `test_front_matter_derivation.py`（17 条）。

## D-31 旧 HTTP 端点的 canonical 桥接必须成对补齐（claims 详情）

- **决策**：`claims/legacy.py` 新增 `get_claim(db, paper_id, claim_id)`，并把 `modules/claims/__init__.py` 的旧 HTTP 分派指向它（此前直接转发只查旧 `claims` 表的实现）。
- **背景**：`GET /papers/1/claims` 能列出 5 条 canonical 断言，`GET /papers/1/claims/{claim_id}` 对**同一批 id 全部 404**——列表走了 canonical 桥接、详情没有。`schemas/adapters.to_legacy_claim()` 其实早就写好了，只是没人调用。用户可见后果：研究图谱"点击断言节点 → 该断言的证据"永远空白。
- **取舍**：详情**必须带出 evidence 记录**（不是只回 statement），否则图谱详情面板依旧是空的；证据取不到时**降级为空列表而不是 500**（兼容层不得把异常泄漏成 500，与 §5.11 一致）。
- **结论**：回归测试 `test_claim_detail_bridge.py`（3 条）覆盖"详情可取到""带出 2 条证据正文""未知 id 返回 None 而非抛错"。

## D-32 QA 必须注入 revision 固定的模型快照

- **决策**：新增 `papers.snapshot_for_revision(scope)`（revision pin 的快照优先，缺失回退运行时快照），`/papers/{id}/qa/stream` 改为 `new_ctx(scope, snapshot=...)`。
- **背景（SSE 实测，这是"证据问答不能聊天"的唯一后端主因）**：`new_ctx()` 的 `snapshot` 默认 `None`，而 revision 明明 pin 了 `model_snapshot_id`。于是 `retrieval/vector.py` 报 `embedding_unavailable`、`qa/service.py` 因 `not snapshot_id` 直接判 `llm_unavailable` → `mode=abstained`，SSE 只发 `meta/status/status/final`（**没有 citation/sentence**）、`answer.text.text=""`，前端落到"既无 sentences 又无 text"分支 → 空气泡 + "无证据支持"。
- **取舍（踩坑，已用单测锁定）**：返回值必须是 **`ModelSnapshotLike`**（或 dict），**不能是 `contracts.ai.ModelSnapshot` 实例**——`CallContext.model_snapshot` 声明的就是 Like 类型，传完整 `ModelSnapshot` 会被 pydantic 以 `model_type` 拒绝、端点直接 500。pipeline 之所以没踩到，是因为它走 `ctx.model_copy(update=...)`，而 `model_copy` **不做校验**。
- **结论**：端到端契约测试断言 `qa/service._snapshot_id(ctx)` 等于 revision pin 的 id；回归测试 `test_qa_model_snapshot.py`（4 条）。

## D-33 前端字段错位批修：把"看起来坏了"逐条落到契约

一次只读审计（两个子代理并行）逐字段比对"前端读取 vs API 实际"，发现多数视图的"没有内容/内容乱"是**字段名或语义错位**，而不是数据缺失。本轮按收益修：

| 视图 | 缺陷 | 修法 |
| --- | --- | --- |
| MapView | 表格内联渲染 `t.content[0]`，而 **16/16 张表 `content=[]`**（内容在 `table_html`）→ 表格只剩标题与空框 | 改用 `TableRender`（优先 `table_html`，自带消毒） |
| MapView | `map_summary` 缺键时六张卡片全渲染成 "—"（paper 2 缺 5/6） | 只渲染**后端真的产出**的卡片；全空给显式文案 |
| MapView | `kind` 直接当标签，实际 kind 含 `problem/body/limitation` 未覆盖 → 界面出现英文 kind | 补 `KIND_LABEL`/`TONE` 映射 |
| MapView/PaperView | `map_summary`/`summary`/`abstract` 未过 KaTeX，`$8\times8$` 原样显示 | 统一走 `MathText` |
| PaperView | canonical 分支把 `body` 写死 `''`、`page` 写死 `0` → **实测 6353/4022/6647 字的真实正文与页码徽标被整块丢弃** | 按 `heading` 与旧 `detail.sections` 合并补回 `body`/页码/要点 |
| PaperView | `hasCanonicalMedia` 时**不渲染** figures/tables → 真图真表被 40 条 `equation` 媒体顶掉 | 取消互斥：真图表常驻，canonical 媒体另设独立区块 |
| MethodView | `importance === 'high'` 而实测 **24/24 图全是 `'medium'`** → "论文原图"永不显示 | 优先 `high`，否则取首图 |
| MethodView | 0 步论文整页近乎空白；`phase=null` 渲染空 Badge；`label` 是 164 字整句 | 加零步空态文案；`phase` 有值才渲染；列表/状态行截断 |
| GraphView | 只认 6 类 kind，实际含 `limitation/method` → 全部落第 1 列且共用灰色（"节点不全、连线不齐"） | 按图中**真实出现的 kind 动态**生成列位/配色/中文名，任何新 kind 都有位有色 |
| GraphView | 详情面板读 `props.text`（后端从不产出该键）→ 恒显示 "—" | 断言节点展示陈述正文，其余展示可用属性事实 |
| EvalView | 整体读**已废弃的 legacy 指标名** → 全部 undefined 显示 0.0% | 改读 canonical 指标（优先 `/exhibits` 的持久化 report） |
| EvalView | `Number(undefined ?? 0) === 0` 让 `unsupported === 0` 为真 → **把"没有数据"渲染成"已通过 Evidence Gate，所有断言均有证据"**（纯属虚构的绿色通过） | 只有真的算出 0 才说通过；null 一律标注"未评测"，并列出 `not_evaluated` |
| PresenterView | `steps` 是后端内部 ID `s:<rev>:0:5510:step:0`，被当标签直接渲染 | 解析为 `method_steps` 的标签；解析不出来就**丢弃**，绝不渲染裸 ID |
| PresenterView | `evidence_refs`（实为 `stmt-*` 断言 id）被当"原文定位"渲染成 `论文原文定位：stmt-01f2…` | 用 `statements` 的 `id → text` 回填陈述正文 |
| ClaimView | 只按固定 `TYPE_ORDER` 分组，**不在表里的断言类型被静默丢弃** | 已知类型排前，其余类型一律补在后面 |
| ClaimView | 断言正文裸渲染 LaTeX | 走 `MathText`；正文为空给显式占位 |

- **结论**：前端 `tsc --noEmit` 零错误；后端全量 **392 passed**。

## D-34 事故记录：后端端口/CORS 与容器落后于工作区

- **事故 1（我造成，已修）**：运行中的 `researchlens-backend-1` 映射到 **8001** 且 `CORS_ORIGINS` 只有 `http://localhost:3001`，而前端 bundle 里烘焙的是 `http://localhost:8002`、`.env` 也写 8002/4002。**前后端不同源 + CORS 不放行 → 前端所有 API 请求全部失败**（"页面什么都没有"的最大单因）。`docker-compose config` 解析正确，说明容器是拿旧环境创建的陈旧实例；`docker-compose up -d --force-recreate backend worker` 后恢复 `8002->8000` + `CORS=http://localhost:4002`。
  - **教训**：改 `.env` 端口后必须 `force-recreate`（仅 `restart` 不会重读环境）；排查"前端全空"的第一步应是**核对运行态端口与 CORS**，而不是先读业务代码。
- **事故 2**：审计时代码已改但镜像未重建（frontend 镜像 13:20 构建，`PaperView.tsx` 13:36 才改）→ 审计到的"运行态"落后于工作区。**教训**：任何"运行态结论"都必须先确认镜像构建时间晚于最后一次源码修改。
- **事故 3（误判，需记住）**：PowerShell 5.1 的 `Get-Content` 默认按 **ANSI(GBK)** 解码，读 UTF-8 中文会显示成 `鍩轰簬` 这类"乱码"。我一度据此判断"库里的正文是乱码"，用 Python 逐字段核对后 `MOJIBAKE_RE` 命中数 **0**，实际数据是干净的。**教训**：判断编码问题必须用 Python 或 `-Encoding utf8`，控制台输出不能作为证据。

## D-35 证据问答全链路：快照类型 + 引文恢复 + gate 落库 + 检索索引

`/papers/{id}/qa/stream` 此前**恒返回空气泡**（SSE 只有 `meta/status/status/final`，`answer=""`、`mode=abstained`）。逐层剥开一共**四个**独立缺陷，全部修完才通。按发现顺序记录，因为它们互为掩盖：

1. **`CallContext.model_snapshot` 被声明为 `ModelSnapshotLike`**
   → pydantic 把完整快照**降级**成 Like 视图，而下游 `CompletionRequest.model_snapshot` / 重排请求声明的是完整 `ModelSnapshot` → `ValidationError` → `qa/service._llm_draft` 抛异常 → 降级"抽取式"。
   **修**：字段类型改为 `Optional[Any]`，`new_ctx` 新增 `_normalize_snapshot()` 把 dict/Like/完整快照统一成 `ModelSnapshot`。
   **为什么一直没暴露**：pipeline 走 `ctx.model_copy(update=...)`，而 `model_copy` **不做校验**；只有 `new_ctx` 这条路会踩到。

2. **`chunks` / `chunk_vectors` 全库 0 行**（papers 1–3 经 seed/reextract 路径入库，跳过了 pipeline 的 `stage_index`）→ 检索 0 命中。
   **修**：对 3 篇论文跑 `retrieval.index()`（幂等）：chunks/vectors = 66 / 111 / 159。

3. **模型给了答案但不给引用**：提示里片段以 `[chunk_id] 正文` 展示，而输出 schema 字段叫 `block_ids`，模型因此返回 `block_ids=[]`/`quote=""` → gate 判 `claim_without_citation` → `sentences=0` → 拒答。
   **修（两处）**：① 提示明确"`block_ids` 原样复制方括号里的标识、`quote` 照抄原文连续片段"；② 新增**确定性引文恢复** `_recover_citation()`——拿引文（或整句）到命中块的**真实原文**里做空白无关匹配，命中才恢复 `(block_id, 原文切片)`。**恢复不等于放宽 gate**：改写过的句子找不到原文就照旧拒绝（单测含 2 条否定用例）。恢复的引文必须是原文切片，否则 gate 会判 `quote_not_in_block`。

4. **`register_statement` 只注册身份、不产生证据**，而 QA 拿完就去看 `display_class` → 每句都停在 `unverified` → 句子全丢。
   同时 `qa/service._register_statement` 把 `ctx` 传成 `None`，而 `claims.register_statement` 要写 `ctx.request_id` → `AttributeError` 被兜底吞成 `gate_unavailable`（同一个可见症状）。
   **修**：新增公共入口 `claims.verify_registered_statement(draft, report, visibility, ctx)`——把 `verify_and_store` 内部那套"保存证据 + `display_class_for` + upsert claim"抽出来，供"先注册后校验"的调用方复用；QA 改为 **validate → register → verify** 三步，并把 `ctx` 透传下去；审计 actor 用 `getattr(ctx, "request_id", "") or "system"` 兜底。

- **修复后实测**：`POST /papers/1/qa/stream` 事件流 = `meta, status, status, citation×3, sentence×3, final`，`final.answer.text.text` = 「这篇论文提出的方法是基于 Haar 小波域指标自适应选择载体的 JPEG 隐写方法，通过计算图像在 Haar 小波域高频成分分解图像的高阶范数，优选难以被检测的…」。
- **回归测试**：`test_qa_model_snapshot.py`（5 条，含"ctx 里必须是完整 ModelSnapshot 且能直接喂给 CompletionRequest"）、`test_qa_citation_recovery.py`（7 条，含"改写句不得被恢复成引用""命中之外的块不得成为引用来源"）。
- **仍存的相关缺口（未做）**：`POST /papers/{id}/index` 这类"重建检索索引"的公开入口尚缺，目前只能跑脚本；补齐后 re-index 才能由 API/作业触发，而不是运维手动介入。

## D-36 事故补记：`to_legacy_evidence` 读错字段（详情端点 500）

- **现象**：修好 `claims` 详情桥接后 `GET /papers/1/claims/{id}` 由 404 变成 **500**。
- **根因**：`schemas/adapters.to_legacy_evidence` 读 `record.source_region[0].block_id`，而 `AnchorSegment` 的字段是 **`block_ids`（列表）**：
  `AttributeError: 'AnchorSegment' object has no attribute 'block_id'`。该路径此前因"详情恒 404"从未被执行，所以长期潜伏——**修好一个 bug 才会暴露下一个**。
- **修**：抽出 `_legacy_region_label(segment)`，对 `block_id` / `block_ids[0]` / `page_label` 三种历史形态都容忍，取不到返回空串。单测加了"证据带真实 `source_region`（`block_ids` 是列表）时详情不得 500"。
- **教训**：桥接/投影层的代码如果长期不可达，就等于没有测试覆盖；恢复可达性后必须立刻补真实形状的用例。

## D-37 研究图谱的 claim → evidence 边：由已判定证据行投影

- **决策**：新增 `_derived_evidence_bindings()`——把**已判定**的 `evidence_records` 投影成等价的 `claim → evidence` 绑定输入，**只补图谱边、不写库**；同时给 `GraphArtifact` 补上 `warnings` 字段（此前 `build()` 收集的告警**无处可放**，"为什么这张图没有边"在 API 里完全不可见）。
- **背景（Postgres 实测）**：`bindings` 全库只有 **6 行**，且**全部**是 `statement → media / illustrates`；`claim → evidence` **一条都没有**。于是图谱只有 `illustrates` 边：paper 1 = 8 节点 / 4 边、paper 3 = 15 节点 / 2 边、**paper 2 = 12 节点 / 0 边（整张散点图）**。这正是用户说的"节点不全且连线不齐"。
  而 gate 早已把判定写进 `evidence_records.support_status`，`claim_records.evidence_ids` 也指向它——那是**已验证的证据**，不是编造。
- **取舍**：
  - 为什么不在 gate 里补写 binding（否决）：那要动写路径 + 回填全部历史数据；而投影层现算**立即可用**且不动数据。真正该记的缺口是"bindings 表没有被 gate 填充"，已由 `evidence_bindings_derived` 告警显式暴露。
  - 只认 `supports` / `contradicts`：`insufficient` / `unreviewed` 一律不进图——**投影不等于放宽判定**（单测含否定用例）。
  - 已有显式绑定的 `(claim, evidence)` 不重复补，避免重复边。
  - 一次读全 revision 的证据行（实测 10–30 行），而不是"先按绑定查、再补查"。
- **结论**：重建快照后实测——**paper 1：8 节点/4 边 → 26 节点/17 边**（13 supports + 4 illustrates + 13 evidence 节点）；**paper 3：15/2 → 29/14**（12 supports）；paper 2：12/0 → 13/1。所有边两端都在节点集内（0 条悬空）。`exhibits.graph.warnings` 可见 `evidence_bindings_derived` 与 `isolated_claim`。
  paper 2 仍只有 1 条证据边，是因为该篇的证据本身只有 1 行（8/12 条引文 `quote_not_in_block` 被判不通过）——那是**抽取质量**问题，不是图谱问题。
- **回归测试**：`test_graph_evidence_edges.py`（5 条：无绑定时必须成边 / `insufficient` 不成边 / `contradicts` 连 `contradicts` / 显式绑定不重复 / 推导必须留告警）。
- **仍存缺口（未做，两处同源）**：`retrieval.index` 与 `graph.build` 这类**派生产物重建**没有公开入口，存量论文只能跑脚本补（本次分别跑了 `retrieval.index` 与 `graph.build`）。建议后续加 `POST /papers/{id}/rebuild-derived`（admin）把 re-index 与 rebuild-graph 变成可触发、可观测的作业，而不是运维手动介入。

## D-38 QA 兜底：模型草稿全被 gate 拒时降级为"检索原文抽取"

- **决策**：`_draft` 在"模型给了草稿但**没有一句**通过 gate"且存在检索命中时，改走 `_extractive_draft` 用**检索命中的原文**作答，并留 `extractive_fallback` 告警；同时修好 `_extractive_draft` 自身的一处缺陷。
- **背景（实测，同一问题连续两次结果不同）**：第一次 `grounded=true / confidence=High` + 3 条带页码证据、答案 105 字；紧接着第二次 `mode=abstained`、`statements=0`、`text=""`。根因是**模型每次改写引文的程度不同**，而 gate 逐句严格校验，抽到 0 句就直接拒答——用户看到的就是"证据问答时好时坏、多数时候不能用"。
- **顺带修掉的缺陷**：`_extractive_draft` 此前直接把命中文本整句当引文，而命中文本是 `chunking.block_context_line()` 产出的 `【章节：6 总结】` + **多块拼接**；该结构说明只存在于检索文本、原文块里没有，于是 gate 判 `quote_not_in_block`，**连兜底答案也被丢光**。现在先 `_chunk_body()` 剥掉结构说明前缀，再用 `_recover_citation` 收敛成某一块的原文切片，定位不到就跳过该命中（不伪造引用）。
- **取舍**：
  - 会不会把"不可答问题"也答了？兜底答案**只引用检索命中的原文**且逐句过 gate，`note` 会标注为抽取式作答；相比"永远拒答"，这是设计里既有的降级路径（`llm_failed` 分支早就这么做），只是漏了"0 句通过"这个入口。`unanswerable_refusal_rate` 指标可能因此下降，属于已知取舍。
  - 不改成"模型改写也放过"：那才是真正的放宽 gate，会引入幻觉；宁可降级为原文引用。
- **回归测试**：`test_qa_citation_recovery.py` 增至 9 条（新增"兜底必须剥掉章节前缀并把引用落在真实块上""草稿全被拒时必须走兜底并留告警"）。
