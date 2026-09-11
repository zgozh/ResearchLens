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





