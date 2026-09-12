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

## D-39 模型对照实测：`qwen3.6-plus` 可用但**抽取路径不可换**；另发现 schema 能力未被复用

**动机**：用户反馈"qwen3.6-plus 调用成功了"，而我上一轮的记录是"qwen3.6-plus 316s 失败"。实测后确认**用户是对的**：那次"失败"是**600s 作业墙钟预算把它掐断**，不是模型本身不可用。以下是可复现的对照数据。

### 实测（容器内，项目自己的 `ai.complete()` 路径 + 真实提示词/schema）

**① 语义判定路径**（`evidence.semantic.judge`，真实 `SEMANTIC_JUDGE_PROMPT` + 真实 `_Verdict`）

| 输入 | qwen-plus | qwen3.6-plus |
|---|---|---|
| 应判 supports | `supports` conf=1.0，**2.5s** | `supports` conf=1.0，**20.7s** |
| 应判 contradicts | **`insufficient` conf=0.3（判错方向）** | `contradicts` conf=0.95，**27.1s** |
| 应判 insufficient | `insufficient` conf=0.2，1.9s | `insufficient` conf=1.0，**28.1s** |

→ 判定路径上 **qwen3.6-plus 判别力更好**（3/3 正确、置信度分离度高），qwen-plus 把 contradicts 判成 insufficient 且三类置信度都低（1.0/0.3/0.2）。**这反证了我上一轮"维持 qwen-plus"的结论——那次只测了引文可定位率与时延，没测判别力。** 样本仅 3 例，不足以定论，但方向明确。

**② 抽取路径**（真实 `CLAIM_EXTRACTION_PROMPT` + `_ClaimExtraction` + 真实 6175 字符/33 块语料）

| 指标 | qwen-plus | qwen3.6-plus |
|---|---|---|
| 时延 | **22.4s** | **494.0s（8 分 14 秒，22×）** |
| 输出模式 | `json_schema`，**1 次尝试** | `json_object`，**4 次尝试** |
| claim / quote 数 | 6 / 10 | 7 / 12 |
| quote **逐字命中原文** | **80%（8/10）** | 75%（9/12） |
| 输出 tokens | 988 | **6218**（远超 `max_output_tokens=4096`） |

→ 抽取路径上 qwen3.6-plus **不可用**：单次 494s 就吃掉 `INGEST_BUDGET_WALL_MS=600000` 的 **82%**，后面还有 N 次逐句判定，必然爆 deadline——这正是"316s 失败"的真身。且质量**没有提升**（命中率反而略低），输出 token 还多 6 倍。
→ **结论：不能整体切换。** 若要利用它的判别力，只能**分模型分工**（抽取/结构留 qwen-plus，判定换 qwen3.6-plus），代价是每篇论文的判定环节从秒级变成 20–28s×陈述数，且必须先调大作业墙钟预算。

### 顺带发现（真缺陷）：观测到的 schema 能力**从未被复用**

`ai/service.py:125` 只判断 `if binding.json_schema is not None:`，**从不读 `caps.capabilities_for(model).json_schema`**。于是 `caps.observe(model, json_schema=False)`（:145）记下的"这家供应商不接受 json_schema"**永远是死数据**：

- 每次结构化调用都要**重新撞一遍** json_schema（最多 `MAX_ATTEMPTS=3` 次），再回退 json_object；
- qwen3.6-plus 实测 `attempts=4`，且第二次调用**没有变快**（19.7/28.5/17.4s，与第一次同量级）——直接证明能力未被复用；
- `caps._OBSERVED` 只在进程内存里，重启即失，也**未持久化**。

修掉它（命中 `json_schema=False` 就直接走 json_object）可省下每次结构化调用约 3 次无效尝试：按实测比例，qwen3.6-plus 抽取可从 494s 降到约 125s，判定从 28s 降到约 7s。**对 qwen-plus 无影响**（它一次就接受 schema）。

### 运维事实（重要，容易踩）

1. **切换入口**：`POST /api/models {"model": "…"}` → 写 `data/runtime.json`（`runtime.get_active_model()` **优先于** `.env` 的 `LLM_MODEL`），对**新**入库作业生效；`.env` 只是兜底默认值。
2. **存量论文的问答不会跟着变**：`/qa/stream` 用 `papers_mod.snapshot_for_revision(scope)`，即 **revision pin 的 `model_snapshot_id`**（实测 paper 1 pin 的是 `fd4c8b11…` = qwen-plus）。换了运行时模型后，老论文仍然用旧模型回答；要变必须重 pin（新 revision 或显式改 `revision.model_snapshot_id`）。
3. 切换会产生新的 snapshot id → QA 缓存键变化 → 旧答案自动失效（这是好事，不会拿旧模型的答案冒充新模型）。
4. `VISION_MODEL=qwen-vl-max` **全项目零调用**（`services/ai.py: vision()` 无调用者），图表信息完全来自 MinerU，没有视觉模型补强。

## D-40 跨块引文纠错：模型标错块号时救回**逐字存在**的引文

- **决策**：新增 `locator.match_quote_across_blocks()`；`claims.service._draft_batch_from_raw` 在主匹配失败后，在**本次语料覆盖的所有块**里再找一次，命中则挂到正确的块并留 `quote_block_corrected` 告警。
- **背景（Postgres 实测 paper 2）**：一轮 12 条断言里 **8 条**报 `quote_not_in_block`。此前的实现**只在模型自报的那个块里**找引文；而 MinerU 会把一段话拆进相邻块（跨页、表题与表体相邻），模型复述时块号极易错位，于是**逐字正确的引文**被当成"不在原文中"丢弃 → citations 空 → gate 全拒。用户看到的就是"证据链少证据、图谱少连线"。
- **取舍**：
  - **只认能产生 `QuoteSpan` 的档位**（`exact` / `normalized`，含空白无关匹配），**绝不接受 `fuzzy`**：纠错的前提是"这段引文确实逐字存在于某块原文"，否则就是给引文随便找个落点（等于伪造引用）。单测含两条否定用例。
  - 纠错后回填的引文是**原文真实切片**，不是模型给的那串字（否则 gate 仍会判 `quote_not_in_block`）。
  - 只搜**本次语料覆盖的块**（模型实际看过的那批），不扩大到全篇——避免把引用挂到模型没见过的上下文上。
  - 廉价预筛（规范化+去空白后是否为子串）避免对每个块跑 difflib。
- **结论**：回归测试 `test_quote_cross_block_recovery.py`（9 条）。

## D-41 可见性隔离：`answer_only` 断言**不得**进入论文产物

- **决策**：`claims.get_verified_statements`、`claims.build_structure`、`graph/repository.list_claims`、`scene/repository.list_claims` 一律只读 `visibility='exhibit'` 的断言；`get_verified_statements` 只排除**明确标记为 `answer_only`** 的陈述（没有 claim 行的历史陈述不误伤）。
- **背景（Postgres 实测 paper 1）**：`claim_records` 里 `answer_only` **15 条** vs `exhibit` **5 条**。问答每次回答都会用 `register_statement` 落库一批 `answer_only` 断言，它们同样是 `verified_fact`；而上述四个读取点**都没有按 visibility 过滤**，于是问答答案被编进论文地图 / 方法步骤 / 讲解分镜 / 研究图谱 / 展项包 / 评测指标。实测：我跑过几轮问答之后，paper 1 的 `method_steps` 从 **1 条涨到 12 条**，内容全部来自 `answer_only`。用户可见后果就是"论文地图/方法动画里混进针对某次提问临时生成的句子"。
- **取舍**：排除"已知是问答派生"的即可，不去猜来源不明的行——`test_statement_without_claim_is_kept` 锁住"不误伤"。
- **结论**：回归测试 `test_visibility_isolation.py`（6 条）。
- **顺带发现（未做）**：应给 `answer_only` 增加**保留期或清理策略**——它们目前永久留在库里并参与评测指标的分母候选，长期会让 `support_precision` 之类的口径漂移。

## D-42 方法步骤：按**方法/实验章归属**取，且顺序必须确定

- **决策**：新增 `_steps_from_sections()`——方法/实验章内按**引用块的文档位置**排序的已验证陈述即步骤，`phase` 用章节标题；归属为空时退回旧的"METHOD 类型断言"路径（`_steps_from_method_claims`）。同时给"模型给了步骤/地图但 claim_ids 全不命中"补上 `method_steps_dropped` / `map_items_dropped` 告警。
- **背景（paper 1 实测）**：`method_steps` 只有 1 步。根因有二：① 确定性路径只把 `type == "METHOD"` 的断言当步骤，而 `_claim_type_for` 是关键词启发式（文本含"方法/算法/流程/训练"才算 METHOD）——paper 1 有 **2 个 method 章 + 1 个 experiment 章**，但 5 条展项断言里只有 1 条被判成 METHOD；② LLM 结构路径对这篇实测返回 `method_steps=0`，没有任何补充。此外丢弃步骤时**完全没有告警**，"为什么只有 1 步"在 API 里不可见。
- **顺带修掉一个真缺陷（顺序不确定）**：`repo.list_claim_rows` 按 `ClaimRecordORM.id`（**随机 UUID**）排序，所以任何"按 claim 顺序生成序列"的地方都是**非确定**的——新写的步骤排序单测因此在全量跑时随机失败，暴露出步骤顺序每次构建都不同。现改为按引用块的文档位置排序（`doc_pos`），连跑 3 次稳定通过。
- **取舍**：`detail` 仍留空——`ArtifactText.spans` 是 **statement 级且必须完整覆盖文本**，模型给的自由散文无法落 span（"禁止无引用副文案"的纪律）；前端读 `label` 文本渲染，不需要重复一份。这解释了 `_MethodStepDraft.detail` 被"丢弃"并非疏忽，而是契约约束；真正缺的是**可观测性**（已补告警）。
- **结论**：回归测试 `test_method_steps_source.py`（5 条）。

## D-43 `POST /papers/{id}/rebuild-derived`：让派生产物可被 API 重建

- **决策**：新增 admin 端点，默认重建 `index` + `graph` + `scene`（均不需要 LLM），`structure` 为**显式 opt-in**（会调 LLM）；返回每项的计数与告警，便于核对。走既有 `require_admin(X-Admin-Token)` 模式。
- **背景（ADR-0037 记的缺口）**：`retrieval.index` 与 `graph.build` 此前**只有脚本能调**。实测 papers 1–3 的 `chunks` / `chunk_vectors` 全为 0（经 seed 路径入库、跳过了 pipeline 的 index 阶段），"证据问答"整块不可用；图谱快照也停留在旧算法上。没有任何 API 能补——只能进容器跑脚本，这不是可运维的形态。
- **取舍**：`structure` 默认关闭，因为它是唯一会花钱的一项；"重建"不该悄悄产生 LLM 费用。`scene` 默认开启（确定性），但**基于当前结构**——改过结构要先 `structure=true`。
- **结论**：回归测试 `test_rebuild_derived_api.py`（5 条：错误凭据 403 / index+graph 重建并返回计数 / structure 必须显式开启 / scene 默认重建 / 重复调用幂等）。全量 pytest **433 passed**。

## D-44 重抽取必须**重建** media 绑定（它自己删掉的）

- **决策**：`claims.reextract` 在重抽取完成后调用 `evidence.bind_media_for_statements(scope, built.statements, ctx)`，并留 `media_bindings_rebuilt` 告警；绑定失败只记 `media_bindings_rebuild_failed`，不让重抽取整体失败。
- **背景（paper 1 实测）**：`delete_claim_artifacts` 会删除 `bindings`（它被归类为"断言派生物"），而重抽取**从不重建它**。后果：statement→media 的 `illustrates` 边消失，图谱只剩 `supports`、讲解与"关键图表"的关联整块断掉——实测 bindings 由 **6 条变 0 条**，图谱 `illustrates` 边归零。
- **取舍**：绑定是**派生增强**（不是断言正确性的前提），因此失败降级为告警而非异常——否则一个媒体的 caption 匹配问题会让整个重抽取白跑。
- **结论**：修复后重抽取 paper 1：`media_bindings_rebuilt` 出现，图谱恢复 **4 条 illustrates + 8 条 supports**。回归测试 `test_reextract.py` 增至 9 条。

## D-45 引文"最长逐字子串"恢复 + paper 2 失配的实测归因

- **决策**：新增 `locator.match_quote_trimmed()`，作为抽取路径的**最后一道**恢复：当整串引文匹配失败时，取模型引文与原文块的**最长逐字子串**，要求 `≥20 字` 且 `≥ 引文长度 × 50%`；命中则回填**原文切片**并留 `quote_trimmed` 告警。契约上 span 标 `normalized`（不是 `exact`），因此**不计入 `quote_exact_rate`**，避免精确率虚高。

### paper 2 失配的实测归因（一次抽取 15 条断言，失配 4 条）

| # | 模型报的引文 | 原文块 | 归因 | 处置 |
|---|---|---|---|---|
| 1 | `Download Percentile (i) = \frac {n - r a n k _ {i}}{n}.` | 块里只有后半段公式 | 引文**逐字存在**，被套了非原文前缀 | ✅ 新增 trimmed 恢复救回 |
| 2 | `use of卸载率(U-I ratio)这一相对指标…` | `使用卸载率(U-I ratio)这一相对指标…` | 模型改写（漏字/并句） | ❌ 正确拒绝 |
| 3 | `can use users' update ratio to represent…` | 中文原句 | **模型翻译**成英文 | ❌ 正确拒绝 |
| 4 | MSE / Kendall τ 的指标句 | 该块讲的是 Lasso/岭回归/随机森林 | 句子来自**语料外**的块（每节预算截断） | ❌ 正确拒绝 |

- **结论（回答"paper 2 图谱为什么只有 1 条证据边"）**：该篇的低验证率**主要不是定位器失准，而是模型改写/翻译引文**——4 条失配里只有 1 条属于"逐字存在但被套前缀"。继续"放宽匹配"会把译文和改写作当成引用，**那才是真正的伪造**。要提升 paper 2 只能改**抽取提示词/模型**，不能松 gate。
- **顺带观测（重要）**：同一篇论文两次抽取的失配数差异很大（10/11 vs 4/15），说明该环节**方差高**；`support_recall` 这类指标若只跑一次，噪声会盖过信号。
- 回归测试 `test_quote_cross_block_recovery.py` 增至 14 条；全量 pytest **441 passed**。

## D-46 Golden Set：真值必须来自**原文**，不能由模型自证

- **决策**：新增 `evaluation/golden_builder.py`（确定性、不调 LLM）+ 两个 admin 端点
  `POST /papers/{id}/golden-set`（构造并保存）与既有的 `rebuild-derived`；同时给
  `evaluation/legacy._input_for()` 补上 `golden` 与 `navigation_checks` 的装配。
- **背景**：`golden_sets` 0 行 → `overall_score` 公式（§5.9）的 4 个核心指标里
  `support_precision`(0.4) 与 `unanswerable_refusal_rate`(0.2) **永远没有分母** →
  `overall_score_available=false`，前端只能显示"未评测"。
  但**"补一批 golden 数据"不能靠模型生成**——那等于让模型给自己出卷子，指标变成自我确认。
- **三条纪律（都有单测锁定）**：
  1. `GoldenClaim.text` 必须**逐字出现在**它声明的块里（真值来自 parser 产出）；
  2. `GoldenAnchor.expected_page_index` 必须等于该块所在**物理页**；块没有矩形就不给
     `expected_rect`（宁缺勿造，避免 `anchor_region_hit_rate` 变假）；
  3. 不可答题所用术语必须**经程序检查确认全文不出现**（"不可答"要被验证，不能猜）。
- **`anchor_page_accuracy` 的真值独立于被判对象**：期望页取自**引用块所在页**（parser 事实），
  实际页取自**证据记录的锚点**（导航会打开的那页），两者来自不同表 → 是真实交叉校验。
- **踩坑与修正（两次）**：
  - 首版 golden claim 取"前 12 个内容块的首句"，**全落在题名/作者/单位/邮箱/摘要**上，
    与真实断言最高相似度仅 **0.13** → `support_precision` 被算成 0。
    **那是构造器取句取错了，不是指标不行**。修法：排除首页杂项（邮箱/上标/单位/引用格式/
    参考文献），并在全文 4 个位置桶间**轮转取样**，优先取带数字/结论动词的句子。
  - 可答题先用满 `question_limit` → 章节多的论文（paper 3 有 9 章）构造出 **0 条不可答题**，
    拒答率又没分母。修法：可答题配额压到 `question_limit // 2`，其余留给不可答题。
- **实测（3 篇真实论文，各 12 golden claims / 4 可答 / 4 不可答 / 12 anchors）**：
  `anchor_page_accuracy = 1.0`、`quote_exact_rate = 1.0`、paper 3 的
  `support_precision = 0.375 / support_recall = 0.25`；paper 1/2 仍为 0（见下）。
- **仍未出综合评分，如实说明原因**：`overall_score` 要求 **4 个核心指标全部 measured**。
  现在 `unanswerable_refusal_rate` 需要把 golden 问题**真问一遍**（`qa.build_bank`），
  已提供脚本；而 `support_precision` 在 paper 1/2 上为 0 是**口径问题**：
  `metrics.similarity` 是"单字 Jaccard + 数字集合 Jaccard（数字权重 0.4）"，
  而产品产出的是**改写句**（含大量数字），与原文句的字面重合度天然低于 `SIM_THRESHOLD=0.42`。
  要让它有意义，必须**产品侧决策**：要么 golden claim 用"事实"而非"原句"（需要人工标注），
  要么承认该指标衡量的是字面重合、把阈值/口径写进规格。**我不擅自调阈值**。
- **顺带：新增的评测第一次量化了我自己在 D-38 引入的回归**——
  `_draft` 的"抽取兜底"此前**无条件**触发，导致模型明确回答"资料不足"（`claims=[]`）时
  也照样从检索原文拼一个答案 → 不可答问题不再被拒答（拒答率会归零）。
  已修正为：**只有模型给出了 claims 但全被 gate 拒时**才兜底；`claims` 为空则尊重拒答。

## D-47 事故根因（D-34 未查清的那一条）：`backend/.env` 影子配置

- **现象（复现两次）**：`docker-compose up -d --build backend worker` 之后，后端落到
  **8001**、`CORS_ORIGINS` 变成 `http://localhost:3001,...` —— 而根 `.env` 与前端烘焙的都是
  **8002/4002**，于是前端所有请求失败（"页面什么都没有"）。D-34 当时只记了"容器是陈旧实例"，
  没找到来源。
- **根因**：仓库里存在一份 **`backend/.env`**（被 `.gitignore` 忽略的本地残留），内容是
  一份**旧端口方案**：`BACKEND_PORT=8001`、`FRONTEND_PORT=3001`、
  `NEXT_PUBLIC_API_URL=http://localhost:8001`。
  **Compose 的 `.env` 是按"当前工作目录"查找的**，所以只要以 `backend/` 为 CWD 运行 compose，
  它读的就是这一份 → 宿主端口 8001；而 `docker-compose.yml:11` 的
  `CORS_ORIGINS: http://localhost:${FRONTEND_PORT:-4002},...` 也随 FRONTEND_PORT=3001 变成 3001。
  **同一个仓库、同一条命令，只因为工作目录不同就切换到另一套端口**，而且没有任何提示。
- **证据**：`docker-compose config`（根目录运行）解析 `published: "8002"`、`CORS=4002`；
  而容器 env 实测 `CORS_ORIGINS=http://localhost:3001,...`、宿主端口 8001。
  容器 labels 显示 project/config 都是根目录那份 → 差异只能来自 `.env` 的加载目录。
- **处置**：把 `backend/.env` 重命名为 `backend/.env.bak-unused-by-compose-20260912`
  （**内容保留、可随时恢复**），然后从根目录 `--force-recreate` → 后端回到 8002、CORS 4002。
- **纪律**：**任何 docker-compose 命令都必须在仓库根目录执行**；排查"前端全空"时，
  第一步永远是核对 `docker ps` 的端口映射与 `docker inspect` 的 `CORS_ORIGINS`。

## D-48 方法步骤的图表引用：按**该步骤自己的**证据取；DTO 固定字段表的静默丢弃

- **决策**：`method_step_extras` 改为输出 ``figure_refs`` / ``table_refs``（可多个），来源优先级：① 该步骤断言的 ``statement→media`` 绑定；② 步骤自带 ``media_ids``；**③ 绝不回退到"全篇第一张图"**。同时给 `LegacyMethodStepOut` 补上这两个字段并透传。
- **背景（用户实测）**：paper 1 的 5 个步骤点开后**都引用同一张图**，且那张图是 ``(a) 原图`` 这种无意义子图面板。根因链：
  1. 确定性步骤（`_steps_from_sections`）构造 `MethodStepRecord` 时**没有 media_ids**；
  2. 于是 `figure_ref` 解析不出来；
  3. 前端 `MethodView` 落回"方法原图"兜底 —— 兜底取 `detail.figures[0]`，**对所有步骤都是同一张**。
- **第二个隐蔽缺陷**：`schemas/adapters._legacy_step` 用**固定字段表**构造 `LegacyMethodStepOut`，所以我新加的 `figure_refs` 在投影层被**静默丢弃**（实测恒为 `null`）。这类"投影层白名单漏字段"很难从 API 表面看出来，必须端到端核对。
- **顺带更正 UI 文案**：MethodView 顶部写死"点击任意步骤可探索其作用 → 输入 → 骨干 → 模块 → 预测"，与实现完全不符（会误导用户以为步骤是模型按那个流程生成的）。实际是"**方法/实验章里按原文顺序排列的已验证断言，每条一步**"，已按事实改写。同理，``phase`` 是章节标题，同章步骤必然相同 → 前端改为**只在阶段变化处标注**，不再每张卡片重复同一个标签。
- **结论（paper 1 实测）**：步骤 1 = 图 9 + 表 2；步骤 3 = 表 [2,1]；其余 3 步**确实没有绑定**（`bind_media_for_statements` 只在 caption 与陈述词面重合 ≥2 个 token 时才绑）→ 前端如实显示"该步骤的断言尚未绑定图表"，而不是硬塞一张无关的图。
- 回归测试 `test_method_step_media_refs.py`（5 条）。

## D-49 长文排版统一组件 `LongText` + `\$` 转义

- **决策**：新增 `frontend/components/LongText.tsx`——按换行切段、逐段过 `MathText`、可选折叠（高度阈值或行数截断）+ "展开全文（N 字）"开关；在 MapView（地图卡片/章节正文）、PaperView（结构化导读/全文原文）、PresenterView（讲解词）统一使用。
- **背景（用户反馈"内容非常多且挤在一起很乱"）**：`sections[].body` 是**该节原文全文**（实测最长 **6647 字**，D-28 的设计：结构化导读要能看到原文），`pages[].text` 是整页原文，而此前都整段塞进一个 `<p>`：没有段落间距、没有折叠，首屏就被一大坨文字塞满，无法定位。
- **转义问题的实测结论（重要，避免误判）**：
  - 用**前端同款 KaTeX** 对 3 篇论文的 180/156/224 个公式逐个渲染：**失败 0 个**。所以"看起来没转义"**不是**公式渲染失败。
  - 逐字段扫描 `$` / 公式外反斜杠：`body/pages/abstract/caption/key_points/method_steps/map_summary/scenes` 等**全部干净**，只发现**1 处**真实问题：paper 2 的 `rf\$importance` —— `clean_text_markup` 的转义字符类里**没有 `$`**（怕解转义后与公式定界符配错）。
  - 修法：不在后端解 `\$`（会产生不成对的 `$`），而在 `MathText` 里**先保护再切分**：把 `\$` 替换成占位符、切完公式再还原为字面 `$`。否则那个 `$` 会和后面任意一个 `$` 配成一对，把中间大段正文吞进"公式"里——那才真的看起来像乱码。

## D-50 金标集来源纪律：机器构造的集合**不得当人工真值**（自我纠正）

- **我上一轮的错误**：新增自动构造的 Golden Set 后，`support_precision` 被算成 measured、`overall_score` 出了 **60/55/75**。但 `docs/REFACTOR_SPEC.md:613` 明确写着：
  > 自动流水线只可报告可直接测量项或 proxy；**support precision/recall 等必须有标注集才叫 measured**。……只在**包含人工真值的核心指标均可测**时计算 overall_score；否则 canonical null。
  把机器从原文自动构造的集合当成真值，等于**让机器给自己出卷子**——既违反规格，也违背"不以假数字冒充"的产品纪律。已修正。
- **修正内容**：
  1. `build_and_save(scope, annotated=False)`：默认产出的是**调参集**（`GoldenSetORM.is_tuning=True`，`golden.py` 既有约定"调参集不用于对外报告"）；
  2. `EvaluationInput.golden_is_tuning`：评测层据此把 `support_precision/recall` 降级为 `not_evaluated`，并追加 `golden_not_annotated` 告警（**proxy 数值写进告警便于排查，但不当真值**）；
  3. 综合评分因此恢复为 **null**（`overall_score_available=false`），符合规格；
  4. 新增「机器提议 → 人工确认」链路：`GET /papers/{id}/golden-set` 列出草案逐条内容（让确认是**看过之后的确认**）、`POST /papers/{id}/golden-set/confirm` 标记人工已确认（此后 precision/recall 才 measured、才出分）；
  5. 前端 EvalView 区分三态：**缺少 Golden Set** / **金标集待人工确认** / **Golden Set 已确认**，并说明"不以 0 分冒充"。
- **一个需要保留的例外（说明清楚）**：`unanswerable_refusal_rate` 在草案状态下仍算 **measured**——因为"不可答"不是模型判断，而是**经程序在全文检索确认该术语不出现**的客观属性，且问题确实被问过（`qa.build_bank`）。它不依赖人工真值。
- **仍未人工确认**：三篇的金标集都是草案。要出综合评分需要**你**（人或受委托者）看过 `GET /golden-set` 的内容后调用 `confirm`。我没有替你盖这个章。
- 回归测试 `test_golden_provenance.py`（5 条：默认是调参集 / 确认清除标记 / 无集合时确认返回 None / 调参集不得出分且告警 / 确认后不再报未确认）。

## D-51 抽取提示词强化：直击 paper 2 的"翻译/改写"失败模式

- **决策**：`CLAIM_EXTRACTION_PROMPT` 增加一节显式规则——**quote 必须原样复制该块文字**：① 保持原文语言（中文块严禁译成英文、英文块不译中文）；② 标点/数字/单位/公式照抄，不增删字词、不合并句子；③ 一个 quote 只能来自一个 block；④ 不加任何前后缀说明（如"原文为："）。
- **背景（D-45 的实测归因）**：paper 2 一轮 12 条断言里最多 **10 条** `quote_not_in_block`，逐条诊断显示失败模式是**把中文原文翻译成英文**、漏字并句、以及引用语料外的句子。原先的提示词只写了"必须是原文中真实存在的片段，不得改写"，但对"翻译"这种"看起来忠实、实则不是原文"的行为约束不够。
- **实测效果（paper 2，同一语料同一模型）**：

  | 指标 | 强化前 | 强化后 |
  |---|---|---|
  | claims | 10 | 12 |
  | **已验证** | **1** | **11** |
  | **quote_not_in_block** | **10** | **0** |
  | method_steps | 0 | 1 |
  | 分镜 | 1 | 3 |
  | 图谱节点/边 | 11 / 1 | **25 / 13** |

  这是本轮最大的一处数据改善：paper 2 从"整篇几乎不可用"变成"与另两篇同一水平"。
- **纪律**：这属于**收紧产出质量**（要求逐字引用），不是放宽 gate；跨块纠错（D-40）与最长逐字子串恢复（D-45）仍然只认"逐字存在"，两条安全网不变。

## D-52 评测口径三处修正 + "事实级匹配"经测量**否决**

- **背景**：用户看到"自动评测一堆指标无数值"，问是不是没做完。逐项查证后确认**不是没做完，是三类真实缺陷**：有的值算出来了却被丢掉、有的口径根本不对、有一个我本来准备放宽的判据被实测证明无益。
- **修正 1：proxy 指标被投影层吞掉**。规格（REFACTOR_SPEC L613）允许报告 proxy，只要求**标明**。但 `to_legacy_evaluation` 把"非 measured"一律写成 `null` 并登记进 `not_evaluated` → 前端显示"未评测"，而 `unsupported_fact_escape_rate` 等其实**有值**。现改为：`measured`/`proxy` 都写值，另出 `metrics["proxy"]` 名单；前端 EvalView 对名单内的项标注"proxy：间接口径（规格允许报告但必须标明），非人工真值"，**不再混进"未评测"**。
- **修正 2：`recovery_success_rate` 永远是 `not_evaluated`**。旧实现 ① 只吃 warnings、② 只认 `*_failed` / `*_unavailable` 两类码。而我们**实际最常发生的降级**是 `citation_recovered`（引用恢复）、`extractive_fallback`（草稿全被 gate 拒后降级抽取）、`quote_trimmed`、`quote_block_corrected`、`claim_without_citation`、`rerank_failed`——一个都不被认。于是这个"恢复能力"指标形同虚设。
  - 现改为**按答案粒度**：`recovery_success_rate(answers)`，显式列出 `_DEGRADATION_CODES`；该次回答出现过降级且**最终仍有答案句或 grounded** 才算恢复成功（分母 = 发生过降级的回答数，**不是告警条数**——否则一次回答报 5 条告警就把分母灌成 5）。
- **修正 3：`qa_first_verified_ms` 拿"页面跳转时延"冒充"首个经验证答案句耗时"**。旧实现用 `navigation_checks[].latency_ms` 的均值，口径完全不对（那是锚点导航）。答案句在 `answer()` 返回时就已生成落库，故改用**产出过句子的那批答案**的 `usage.elapsed_ms` 均值，`method` 写明口径；拒答样本不计入（那衡量的是"拒答有多快"）——**全部拒答时该指标是 `not_evaluated`，不写 0**。`navigation_checks` 参数随之从 `timing_metrics` 移除（它仍服务于 `anchor_page_accuracy`）。
- **被否决的方案（"事实级匹配"）**：`support_precision` 实测为 `null`（金标集是草案，见 D-50）。我曾怀疑是"模型改写句 vs 原文句措辞不同"导致相似度上不去，遂实现 `fact_match_score`（同数字 + 术语重合的额外通道）并测量：
  - 手工构造的**同事实改写句**相似度本就 0.58–0.64（`similarity` 里数字权重已把它拉过 `SIM_THRESHOLD=0.42`）——即"改写"根本不是失败原因；
  - live 数据上 3 篇论文的过阈值预测数：**`similarity` 字面 3 条 / 事实级 3 条，完全一样**。
  - 结论：预测与 golden 是**内容不同**，不是同一事实换措辞。放宽判据只会削弱匹配语义，**已回退**（删除 `fact_match_score`、`scorer` 与 `test_fact_match.py`），并在 `one_to_one_match` 的 docstring 里留下这段实测结论，防止后人再走一遍。
- **遗留（明确不假装完成）**：`anchor_region_hit_rate` 仍无矩形可判（不编 IoU）；`support_precision/recall` 要等金标集**人工确认**才 measured；`overall_score` 因此保持 null。
- **修正 4：把"未完全核验通过"当成了"拒答"**。`refusal_metrics` 用
  `refused = (answer.grounded is False)` 判拒答——但 `grounded=False` 只表示"未完全核验通过"
  （有句子但含未验证推断、或引用恢复过），**不等于拒答**；`qa/service.py` 自己的定义是
  "无句子才算拒答"（`if not decision.grounded and not sentences:`）。
  - 实测后果（live 3 篇）：paper 1 里一条 `mode=generated`、**交付了 3 条答案句**（`ms=18201`）的
    回答被算成"可回答却被误拒"，`answerable_false_refusal_rate` 从真实的 **0** 虚报成 **0.5**；
    paper 3 从 **0.5** 虚报成 **0.75**。
  - 改为按 `mode == "abstained"` 判（无 `mode` 的旧记录退化为"无句子且无文本"），
    实测变为 **0.0 / 0.25 / 0.5**。
  - **必须说明方向**：这一改使数字**变好**，所以我格外查了原始证据——逐条打印了
    `mode / grounded / statements / elapsed_ms`（见下），确认那些被记为"误拒"的回答确实交付了内容。
    这不是放宽阈值，是把判据从不成立的 `grounded` 换成语义正确的 `mode`。修正后 paper 3 仍有
    **0.5 的真实误拒率**（4 道可答章节题里有 2 道被拒答），这个"难看但真实"的数字被保留下来。
- **修正 4 顺带发现的**：那 2 道被拒答的题（paper 3 的「2 相关背景」「3 Solidity…设计」）**不是**
  检索坏了——插桩显示 `_retrieve` 有 5 命中、无告警，但 hybrid 的向量通道把**别的章节**排到了前面，
  章节标题块没进 top-5，模型遂判"证据不足"并返回空 claims（按设计尊重拒答）。
  **验证实验**：只把该章节自己的 2 个块喂给 `_draft`，两道题都产出了**带证据的验证句**
  → 根因是"问句点名了章节，检索却不保证召回该章节"。修法（章节通道）记在 D-54。
- 回归测试 `test_eval_metric_reporting.py`（15 条：拒答判据 5 / proxy 三项 / recovery 四项 / 时延三项）。

## D-53 已观测到的模型能力必须复用（否则每次结构化调用都白撞 schema）

- **缺陷**：`ai/service.py` 的 `caps.observe(...)` 一直在**记录**"该模型不接受 json_schema"，但 `complete()` 决策时**不读**——每次结构化调用仍先撞 `json_schema`，失败后才回退 `json_object`。实测 `qwen3.6-plus` 单次抽取因此有 **3 次白撞**，总耗时从 ~125s 涨到 **494s**（吃掉 `INGEST_BUDGET_WALL_MS=600000` 的 82%）。
- **决策**：进入 `json_schema` 尝试循环前先查 `caps.capabilities_for(model_override or provider.model)`；若 `json_schema is False`，**只跳过这一层循环**，继续走 `json_object` 回退。
- **一个差点犯的错**：第一版把短路条件直接加到外层 `if binding.json_schema is not None and observed.json_schema is not False:` 上——而 `json_object` 回退循环**嵌在同一个 if 里**，于是连回退一起跳过、直接掉进"路径二纯文本"，结构化绑定再也拿不到 JSON。测试立刻抓到（第二次调用 `sent` 为空、`object_tries == 0`）。教训：**短路要贴着它真正想跳过的那一层**，别改外层守卫条件。
- **口径说明**：`observed.json_schema is not False` 而非 `is not None`——`None` 表示"尚未观测"，必须照常尝试（首次仍要试，试过才知道）。
- 回归测试 `test_ai_capability_reuse.py`（2 条：首次仍尝试 schema / 第二次记下 False 后 schema 0 次尝试且仍有 json_object 调用）。

## D-54 章节通道：问句点名了章节，检索就必须召回该章节

- **背景（D-52 修正 4 顺带查出来的真实缺陷）**：评测的题库（`qa.build_bank` / golden builder）用
  **章节标题**造问题——"论文中「2 相关背景」这一部分主要讲了什么？"。这类问题的答案就在该章节里，
  但实测 paper 3 的 **4 道可答章节题被拒答 2 道**（`answerable_false_refusal_rate=0.5`）。
- **根因（插桩定位，不是猜）**：`_retrieve` 正常返回 5 条、零告警，但 hybrid 排序把**别的章节**排到了前面。
  逐条打印 RRF 后看到确切机制：
  - 该章节的块在**词法**里其实是第 1（`lex=34.7`），但只有**单通道**贡献 → RRF≈**0.0164**；
  - 向量+词法**双通道**的无关块 RRF≈**0.026–0.030**；
  - 于是目标块排第 **6**，被 `top_k=5` 截掉 → 模型拿到的是别的章节 → 判"证据不足"→ 返回空 claims
    → 按设计（尊重拒答）返回 `abstained`，且 `ms=0` 级别地"什么都没做"。
  - 排除项：**不是**检索坏了（`mode_used=hybrid`、向量分 ~0.55、无告警）、**不是**重排挤掉的
    （`rerank=False/True` 两种跑法 top-5 完全一致）、**不是**模型能力问题。
  - **验证实验先于实现**：只把该章节自己的 2 个块喂给 `_draft`，两道题都产出了**带证据的验证句**。
- **决策**：在 `retrieval.service` 增加**章节通道**——问句里出现索引中存在的章节标题时，把该章节自己的块
  作为一路候选加入 `rrf_fuse`，权重 `SECTION_WEIGHT=2.5`（`2.5/61≈0.041`，足以压过双通道陌生块）。
  - 判据**只有**"问句出现了索引中存在的章节标题"（去掉引号/书名号/空白后比对，标题长度 ≥2 字）；
    命中多个标题取**最具体**（最长）的那个——「方法」不该抢走「方法实现流程」。
  - 章节归属看两处：块的结构化 `section_path`，以及块文本里的 `【章节：X】` 标记
    （分块会跨节合并，合并块靠标记仍能认出来）。最多带进 `SECTION_CHANNEL_LIMIT=8` 块，长章节不挤满候选。
  - 它是**功能不是降级**：不产生任何 warning（不会污染 `recovery_success_rate`）。
  - `ALGORITHM_VERSION` 从 `rl.retrieval/2` **bump 到 `/3`**（规格要求影响检索结果的改动必须进版本）。
- **顺带修掉两个"过期数据掩盖改进"的缺陷**（否则这次修复根本量不出来）：
  1. **评测读最旧的答案**：`list_answers` 是 `order_by(created_at)` **升序**，而 `refusal_metrics`
     用 `seen` 去重、先到先得 → **旧答案赢**；重跑题库后拒答率仍按旧记录算。
     现改为 `metrics.latest_answers()`：同一问题只保留**最新**一条（`refusal_metrics`/`timing_metrics`/
     `token_metrics` 都用它）。注意这不是"只挑好看的"——先答对后拒答会被**如实**记成误拒（有测试）。
  2. **QA 缓存键不含检索版本**：`cache_key` 只有 source/model/prompt/gate，检索变了旧答案照样命中缓存。
     现加 `retrieval_version`（由 `qa.service._retrieval_version()` 传 `retrieval.ALGORITHM_VERSION`）。
     实测中正是它让我第一次"重问"拿回来的还是索引未建好时那条拒答记录。
- **实测效果（重跑三篇题库后，均为 measured）**：

  | 指标 | 修复前 | 修复后 |
  |---|---|---|
  | `answerable_false_refusal_rate`（paper 1/2/3） | 0.5 / 0.25 / 0.75（口径错误时的虚报） | **0.0 / 0.0 / 0.0** |
  | `unanswerable_refusal_rate` | 1.0 / 1.0 / 1.0 | **1.0 / 1.0 / 1.0**（仍全拒答，未因修复而放过不可答题） |
  | `quote_exact_rate` | 1.0 / 0.75 / 1.0 | 0.9375 / 1.0 / 1.0 |
  | 可答章节题实际作答数 | paper 3 为 2/4 | **4/4**（三篇全部 4/4） |
  | `recovery_success_rate` | not_evaluated | 1.0（分母 5 / 4 / 4，真实） |

  注意最后两行是**独立**的：`unanswerable_refusal_rate` 保持 1.0 说明没有"为了少拒答而乱答"，
  不可答的 4 道题仍然全部正确拒答——这两条必须一起看才有意义。
- **仍然 null 的（不假装完成）**：`support_precision/recall`（金标集是机器草案、未人工确认）、
  `anchor_region_hit_rate`（无矩形可判）、`overall_score`（依赖前者）。
- 回归测试 `test_retrieval_section_channel.py`（11 条：章节通道单元 6 / 检索集成 3 / **hybrid 排序复现 2**）
  与 `test_eval_answer_freshness.py`（10 条：最新答案赢 5 / 缓存键 3 / upsert 与键一致性 2）。
  其中 `TestHybridRankingRegression` 用纯融合层**确定性地复现**了 live 的排序失败
  （单通道目标块排第 6 → 注入章节通道后回到 top-5），不依赖 embedding。

## D-55 `overall_score`：未评估时是**真 null**，不是 0.0（列放宽可空 + 迁移 0008）

- **发现的经过**：D-52/D-54 修完后 curl `/api/papers/1/evaluation`，顶层仍是
  `"overall_score": 0.0`，而 `metrics.overall_score_available=false`。
- **根因**：规格要求"核心指标不可测时 `overall_score` 必须是 null，不得用 0 冒充"，
  canonical 报告也确实是 `None`；但 legacy 投影**为了迁就 `evaluations.overall_score`
  的 NOT NULL 列**，在**两处**都把它填成 0.0（`modules/evaluation/legacy.py` 与
  `schemas/adapters.py`），只靠 `available` 标志提示。
- **为什么必须改**：前端恰好有 flag 保护，但**契约本身在教人误读**——任何只读
  `overall_score` 的消费者（包括人肉 curl 验收）都会看到"0 分"。这正是"以假数字冒充"，
  和 D-50 是同一类纪律问题：**不能靠"调用方记得看另一个字段"来保证不误导**。
- **修法**：
  1. 迁移 `0008_evaluation_score_nullable.py`：`evaluations.overall_score` 放宽为可空
     （幂等、纯 expand、不需回填；downgrade 会把 NULL 回填 0.0 并说明**有损**）；
  2. ORM 改 `Mapped[float | None]`；`EvaluationOut.overall_score: Optional[float]`；
     前端 `types.ts` 同步 `number | null`；
  3. 两处投影都返回 `None`，并顺带把 `schemas/adapters.py` 的 **proxy 口径**与
     `modules/evaluation/legacy.py` 对齐（此前 adapters 里 proxy 同样被丢成 null）；
  4. "论文不存在/revision 不可用"的占位行也从 0.0 改成 `None` + `available=False`。
- **实测**：`curl /api/papers/{1,2,3}/evaluation` → `overall_score = None`、
  `available = False`、`canonical = None`；`alembic current` = `0008 (head)`。
- 回归测试：`test_eval_metric_reporting.py` 新增两条（modules 投影 / adapters 投影
  都必须是 None，且 proxy 值不得被丢）。
- **仍然保留的判断**：`overall_score_available` 标志继续存在（旧消费者需要），
  但它现在是**冗余**的安全网，而不是唯一的真相来源。

## D-56 AI 评测：LLM 语义裁判出分（proxy）+ 独立的 `ai_overall_score`

- **谁要求的**：用户明确的指令——"可以直接全部 ai 测评，评分吗 …那还是按我说的直接 ai 评测和评分"。
  此前 `support_precision` 一直是 null（金标集是机器草案，规格要求"必须有标注集才叫 measured"），
  四个核心指标缺一个 → `overall_score` 恒 null，界面永远显示"未评测"。
- **先查清楚"卡点到底在哪"（不是拍脑袋）**：
  - 四个核心指标里，`quote_exact_rate`/`anchor_page_accuracy`/`unanswerable_refusal_rate`
    **本来就是程序可测**（实测 0.94/1.0/1.0 都有值）；唯一缺的是 `support_precision`；
  - 而它缺的**技术原因**是文本相似度：预测断言与参考断言常是"同一事实不同措辞"，
    实测最高相似度 **0.21 < 阈值 0.42**（D-52 已实测"事实级匹配"通道 0 增益，因为它仍在比字面）。
- **决策**：加一个 **LLM 语义裁判**（`evaluation/ai_grader.py`）——只做一件事：
  判断"预测断言 i"与"参考断言 j"是否表达**同一事实**（数值/结论/对象一致；允许改写、中英互译；
  每条预测与每条参考各自最多配一次）。判据不是放宽阈值，而是换成**语义判等**。
- **纪律（绝不破坏既有规范）**：
  1. 裁判产出的 precision/recall 状态是 **`proxy`**，**不是 measured** —— "没有人工标注就不算 measured"不变；
  2. 新增**独立的** `ai_overall_score`（同一 0.4/0.2/0.2/0.2 公式，但允许 `support_precision`
     以 proxy 参与）；canonical `overall_score` **仍然只在四项都 measured 时才有值**，
     所以 D-50 的"机器不得给自己出卷子"没有被破坏（`test_golden_provenance` 仍全绿）；
  3. 四项里**缺任何一项**就不出 AI 分（不用 0 顶替）；
  4. 调用失败/无模型 → `None`（未判定），**绝不返回 0 分**；
  5. 结果按**输入摘要**缓存（`judge_digest`），摘要不匹配必须重判；
  6. 前端明写"AI 口径"，并说明"不是人工真值分"。
- **过程中自己踩的两个坑（都写进测试）**：
  1. **持久化不全 → 缓存把好数据写成 0**：为了省事只存"总数"不存配对，复用时却用 `matches`
     重算真阳性 → 算成 0，于是第二次打开评测页就把 0.5714 覆盖成 0，之后永远 0。
     修法：契约加 `true_positive` 字段，复用路径**直接用它**；补"往返一致"测试。
  2. **裁判改判可能是"分母脏"而不是"裁判不行"**：paper 2 判 0 命中，逐条打印后确认
     12 条参考断言里 **3 条是参考文献条目**（`[12] Lim SL, Bentley PJ, …`）。
     `_FRONT_MATTER_RE` 只在句子文本里找 "References" 字样，而文献条目本身不含这个词 → 全漏过。
     修法：① 按**章节标题**整章排除 references/致谢/附录；② 句子形态兜底（`[12]` + 拉丁作者式）。
     `GOLDEN_VERSION → rl.golden/2`。
  3. **参考集取句取错了内容**：参考集全是"每块首句"（数据集规模、算法对比等铺垫句），
     而抽取产出的是**定义/量化断言**，两批**根本不重合**——模块自己的注释早就写着
     "要瞄准量化结论句"，实现却只拿首句。改成块内取**最像断言的句子**（`_best_sentence`），
     仍**只从原文取句**（真值来源不变）。`GOLDEN_VERSION → rl.golden/3`。
     顺带发现句子切分把**小数点当边界**（`8.5%` 切成 `8.` 与 `5%`），已修
     （`.` 只在后面跟空白/结尾时才算边界）。
- **实测（三篇真实论文，重建 golden 后首次判定）**：

  | 论文 | support_precision | support_recall | ai_overall_score | 人工口径 overall |
  |---|---|---|---|---|
  | paper 1 | **0.857**（修复前 0.571） | 0.5 | **93.03** | null |
  | paper 2 | **0.182**（修复前 **0.0**） | 0.167 | **67.27** | null |
  | paper 3 | 0.625 | 0.417 | **85.0** | null |

  缓存效果：首次 3–4s（真判），二次访问 **0.06–0.07s**（命中缓存且数值不再被写坏）。
- 回归测试 `test_ai_judge_evaluation.py`（17 条：裁判单元 7 / 综合分 4 / 服务接线 6，含**往返一致**）
  与 `test_golden_builder.py` 新增 5 条（文献条目按章节排除/按形态排除、正文结论句不误杀、
  取最优句、单句块不变）。
- **仍未做的（不假装完成）**：`support_precision` 是 **proxy**，所以它参与的评分只能叫 AI 分；
  要拿到"人工真值分"仍需人看过并 `confirm` 金标集。

## D-57 证据问答不受限：与论文无关的问题走**通用回答**，不再"无证据即拒答"

- **谁要求的**：用户原话——"证据问答功能应该不受限制问答，不应该无证据 → 拒绝编造，
  应该只是聊到论文相关的东西才查到该论文相关的东西。"
- **原缺陷**：`_draft` 里 `if not hits: return "", [], Usage(), …` → 任何**检索不到论文内容**
  的问题（闲聊、领域常识、跨论文提问）都被判 `abstained`，界面显示拒答，用户以为"问答坏了"。
- **决策**：在检索之后、生成之前加一次**指向判定** `_is_paper_related(question, hits)`：
  1. 问句出现指向词（论文/本文/这一节/图 3/实验/…，中英都认）→ **论文问题**；
  2. 或检索命中的**语义相似度 ≥ 0.6**（问的正是文中内容，只是没用"论文"二字）→ 论文问题。
  - 判据**故意不含"检索有没有命中"**：问"什么是量子纠缠"时检索也会返回一堆片断，
    但那是无关命中；反过来"这篇论文用了什么数据集"即便索引为空也仍是论文问题。
- **两条路径**：
  - **论文问题** → 走原证据链；**没有证据仍然如实拒答**（"不编造"这条纪律不变）；
  - **非论文问题** → `_general_answer`：通用提示词直答，`mode="general"`、**`grounded=False`**、
    `note` 写明"未使用论文原文证据，不是论文内容"，不产生任何断言与引用；
    **没有可用模型时返回 `None`**，调用方按原拒答路径走（绝不硬编一段文字冒充回答）。
- **连带口径**：评测的拒答率用 `mode == "abstained"` 判（D-52 已改），
  所以 `general` **既不记误拒、也不记"正确拒答"**——有测试锁住；
  SSE 状态文案为"通用回答（未使用论文证据）"；前端用蓝色徽标与"拒答"区分。
- 回归测试 `test_qa_general_mode.py`（8 条：指向判定 4 / 路径 3 / 评测口径 1）。

## D-47 附（措辞修正）

原文写"Compose 的 `.env` 是按当前工作目录查找的"，实测更精确的说法是：**Compose 先看当前工作目录的 `.env`、再看项目目录（compose 文件所在目录）的 `.env`，前者优先**。证据：`backend/.env` 存在时（以 `backend/` 为 CWD）端口/CORS 被它覆盖成 8001/3001；把它改名后，同样的工作目录又能正确读到根 `.env`（8002/4002、`DEMO_MODE=false`）。
