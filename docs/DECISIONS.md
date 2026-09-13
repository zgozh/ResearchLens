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

## D-58 图谱节点必须带够展示事实；**投影层不许静默丢字段**

- **谁反馈的**：用户实测两条 ——"研究图谱里的…证据节点就只有个标签显示'可定位锚点 1 个'是正常的吗"
  与"图表节点没有给出具体的图表"。**都不正常**，而且是两个层面的缺陷。
- **缺陷 1（真 bug，投影层丢字段）**：`graph/legacy.to_legacy_graph` 的 props 是**白名单**：
  `status/claim_id/evidence_id/anchor_ids` —— **没有 `media_id`**。于是前端"图表节点"分支
  （`selected.props?.media_id`）**永远不成立**，图表节点等于空壳。
  这和 D-48（`_legacy_step` 丢掉 `figure_refs`）是**同一类**缺陷：白名单式投影漏一个字段，
  API 表面毫无异常，功能整块失效。**纪律**：投影层必须原样透传契约里已有的字段。
- **缺陷 2（节点没带展示事实）**：节点只有 `label` + 几个 id，前端除了"数锚点个数"无话可说。
- **修法**：
  1. `GraphNodeRecord` 增加 `props: Dict[str, Any]` —— 放**展示用**的补充事实
     （用 dict 而不是继续加语义字段：这些是投影/UI 关心的，不该污染图谱语义）；
  2. 构建时填充：图表节点给 `media_id/media_kind/legacy_no/caption`；
     证据节点给 `support_status/quote/page/anchor_id`
     （`source_page` 是 **1-based 页码**，见 `evidence/gate.build_evidence` 的 `pdf_page_index + 1`）；
  3. 投影层白名单补上 `media_id` 并透传 `props`；
  4. 前端：图表节点按需调 `GET /api/papers/{id}/media/{media_id}` 取 **assets + 视图策略**，
     直接渲染这张图/表（没有图像资产时**如实说明**并只提供定位）；
     证据节点显示 判定徽标 + 原文第 N 页 + 引文；"可定位锚点 N 个"这个**静态标签**换成
     真的能跳页的按钮（接既有的 `onNavigate({anchor_id})`）。
- **注意**：图谱是**持久化快照**，改完必须 `POST /papers/{id}/rebuild-derived` 重建才生效
  （实测：不重建时新 props 全空，`media_id` 有值只是因为它在节点语义字段里）。
- **实测（重建后）**：paper 1/3 的图表节点 `no=2/8 kind=table caption='表 2 …'`，
  经 media 接口拿到 **16/23 个资产**且 `policy=extracted`；证据节点
  `status=supports page=8 anchor=有 quote='r 小波的相关系数…'`。
- 回归测试 `test_graph_node_props.py`（5 条：投影保留 `media_id`、透传节点 props、
  证据带判定与页码、两个 props 构造器）。

## D-59 方法步骤的图表引用：新增**位置兜底**（同页/相邻页），来源一路标到前端

- **谁反馈的**：用户 ——"方法动画里有些步骤显示该步骤的断言尚未绑定图表（证据门只把 caption
  与陈述词面重合的图表绑上；不重合就不绑…）然后导致该步骤没有相关的引用。"
- **背景**：`bind_media_for_statements` 原本只认两类可复核关联：① 陈述显式写"图 N"；
  ② 与 caption 共享**区分性 token**。中文论文上命中率有限，两道关都过不了就一条不绑。
- **决策**：新增第三种、**低置信但诚实**的关联 —— **位置兜底**（`method="page_proximity"`）：
  ① 只在精确方法都没结果时启用；② 页差 ≤ 1（同页优先于相邻页）；③ 分值固定 0.2（显著低于精确匹配）；
  ④ `reason` 写明"位置推断，非题注文字匹配"；⑤ 来源方法一路传到前端并**在 UI 上分开标注**。
  **绝不退回"全篇第一张图"**（D-48 的教训：5 个步骤曾都指向同一张 `(a) 原图`）。
- **查数据时发现的两个"看不见的坑"（都很关键）**：
  1. **媒体根本没有页信息**：papers 1–3 的 `media` **一个 anchor 都没有**，也没有块通过
     `media_id` 反向引用（`带 media_id 的块 = 0`）。`papers.legacy._media_pages` 走的就是锚点，
     所以它对这批数据恒返回 `{}`（前端图表页码因此是 0）。
     修法：用 **caption 文本反查它所在的原文块**，取该块的物理页（实测前 8 个媒体里 **7 个**能匹配上）。
     匹配不上就**不给页**，不猜。
  2. **`Binding.method` 是受控 Literal**：`page_proximity` 不在枚举里，于是兜底绑定
     **全部校验失败**、一条都没落库 —— 而调用方的 `except` 把异常吞了，表面上"什么都没发生"。
     修法：把 `page_proximity` 加进 Literal，并让 rebuilt 接口**回报 by_method 分布**（可见性）。
     这一条正是"先查现状再动手"救回来的：不做 `bindings` 计数就只会看到"兜底没生效"。
- **顺带修了一处投影层缺陷**：`_media_kind_of` 与 `_collect` 只会解包 `(media_id, kind)` 两元组，
  带来源方法的三元组会 `ValueError`；`LegacyMethodStepOut` 也**必须显式加字段**
  `figure_ref_methods`，否则又被固定字段表静默丢弃（**第三次**遇到同一类坑，已写入纪律）。
- **可运维性**：绑定规则升级后必须回填，因此 `POST /papers/{id}/rebuild-derived` 增加
  `bindings`（默认开，确定性、不调 LLM），并回报 `{statements, bindings, by_method}`。
- **实测（回填后）**：

  | 论文 | 绑定（按方法） | 步骤引用情况 |
  |---|---|---|
  | paper 1 | 3（`caption_ref` 2 + `page_proximity` 1） | 6 步中 2 步有引用（图 9 标为位置推断） |
  | paper 2 | 9（`page_proximity` 9） | 1 步 1 引用（图 4，标为位置推断） |
  | paper 3 | 8（`caption_ref` 3 + `page_proximity` 5） | 4 步中 3 步有引用 |

  **仍然为空的**：paper 1 有 3 个步骤的断言所在页附近确实没有图表（页差 > 1）→ 如实不绑，
  UI 文案已改为说明"显式编号、题注匹配、或同页/相邻页三者都不满足才不绑"。
- 回归测试 `test_method_step_proximity_refs.py`（7 条：位置兜底 4 / 来源标注 3）。

## D-60 旧问答入口的三个真缺陷：500、**从不调用模型**、通用回答拿到空正文

- **怎么发现的**：给 D-57 补**线上**验收（此前只跑了单测）时暴露的 —— 问论文问题 **HTTP 500**，
  问与论文无关的问题**仍被拒答**。三条证据都来自容器内 traceback 与线上响应，不是推断。
- **缺陷 1：带证据的回答必然 500**。`qa/legacy.py:63` 读
  ``ev.source_region[0].block_id`` → ``AttributeError: 'AnchorSegment' object has no attribute
  'block_id'``。**这个 bug 早前在 `schemas/adapters.py` 修过**（改叫 `_legacy_region_label`），
  但 `qa/legacy.py` 里是**另一份手写副本**，没同步 → 旧接口只要答出内容就 500。
  **修法**：删掉副本，`qa/legacy.to_legacy_answer` 直接委托 `schemas/adapters.to_legacy_answer`，
  并加测试断言**两处投影逐字段相等** —— 同一份投影写两遍，迟早只修一处（这次就是）。
- **缺陷 2：旧入口 `_legacy_ctx` 直接 `return None`** → `_draft` 看到 `snapshot_id is None`
  就走 `llm_unavailable` **抽取降级**：旧接口**从来不调用生成模型**；同时
  `_general_answer` 要求 `_snapshot_id(ctx)`，于是 D-57 的"通用回答"在旧接口上**永不触发**。
  **修法**：给旧入口建带**论文模型快照**与预算的 `CallContext`（取不到就退化为旧行为，不 500）。
- **缺陷 3：通用回答拿到空正文**。`ai/service.complete` 的"路径二：纯文本"把正文放在
  **`value`** 里（``CompletionResult(value=result.text, mode="text")``），而
  `CompletionResult` **根本没有 `text` 字段**；`_general_answer` 却读 ``result.text``
  → **永远空串** → 永远返回 None → 退回拒答。
  - **我的单测当时也照着这个错假设伪造了 ``text=`` 的对象，所以"单测通过、线上失败"**。
    修法：抽 `_completion_text(result)` 正确读 `value`，并让单测**改用真实契约类型
    `CompletionResult` 构造返回值**（不再手搓 SimpleNamespace），另加一条回归锁。
- **顺带**：模型有时把 `answer` 留空、只给 claims（句子仍能过 gate），界面会同时显示
  "有正文"与 note="答案文本为空"，容易被读成自相矛盾 → note 改为
  "模型未给出整体结论（answer 为空），本回答由**通过证据校验的事实句**组成，因此不整体标为 grounded"。
- **线上实测（修复后，5/5 通过）**：

  | 问题 | mode | grounded | 有正文 |
  |---|---|---|---|
  | 什么是量子纠缠？ | **general** | false | 是 |
  | 推荐几部科幻电影 | **general** | false | 是 |
  | 本文提出的方法是什么？ | generated | true | 是 |
  | 图 3 说明了什么？ | generated | true | 是 |
  | 本文是如何使用 Kubernetes…？ | abstained | false | 否（仍正确拒答） |

- 回归测试 `test_qa_legacy_projection.py`（4 条：带证据不崩、mode 透传、**两处投影一致**、
  旧入口 ctx 带模型快照）与 `test_qa_general_mode.py` 新增 2 条（真实契约类型 + note 解释 + `_completion_text` 回归锁）。

## D-61 遗留登记（**已查证、未修**，等决策）

以下是"顺带复查其他遗留问题"这一项扫出来的东西。**当场查证过，但没有擅自改** ——
它们的共同点是"改了会动到多个端点的既有语义"，需要你拍板。

### 1. 无可读 revision 的论文，状态码语义不对且各端点不一致

- **事实（实测）**：demo 论文 4–6 没有 canonical revision（没有源 PDF，见第 2 条）。
  同一个条件，三个端点三种回应：
  - ``GET /api/papers/4/statements`` → **422** ``{"code":"INVALID_INPUT","message":"scope 非法"}``；
  - ``GET /api/papers/4/graph`` → **200**（空图 0 节点 0 边）；
  - ``GET /api/papers/4/pages`` → **404**。
- **为什么不对**：客户端**分不清**"这篇确实没有结构化产物"和"请求本身写错了"；
  422 的意思是"请求非法"，而这里请求没毛病（paper 存在、参数合法），是**资源状态**问题。
- **建议（未做）**：把"无可读 revision"统一成 **404**（或 409），并在响应体里给出
  ``reason="no_readable_revision"``；改之前要确认前端对 demo 论文的取数路径不依赖
  "200 + 空"（图谱/讲解的 demo 展示目前混用 legacy 表）。
- 取证脚本：`.scratch/smoke_endpoints.py`（全端点冒烟，当前 **0 个 5xx**）。

### 2. demo 论文 4–6 的 canonical 产物是空的（**没有原料**，不是 bug）

- **事实（实测）**：papers 1–3（真实论文）canonical 完整：
  statements 7/11/8、graph 23-28 节点 / 13-19 边、分镜 2/3/4、页 10/16/25；
  papers 4–6（demo）：statements 0、graph 0、分镜 0、**页 0**，只有 legacy 表里的
  claims 10/8/8 与 steps 5/5/5。
- **原因**：它们是 `seed/demo_papers.py` 用**硬编码 IR** 落进 legacy 表的
  （`source_mode="demo"`），`data/sources` **一个源文件都没有**（`ls | wc -l` = 0）
  —— 没有原文块就没有页/锚点，也就抽不出 canonical 断言与图谱。
- **要补的话是另一件事（未做）**：要么提供这 3 篇的源 PDF 走正常 ingest，
  要么写一个 **demo IR → canonical 投影**（把 IR 里的节点/边/文本落成 blocks/pages/
  statements/graph）。后者是"种子数据"，**必须在界面上标明来源是演示脚本而不是抽取结果**，
  否则会与真实证据混在一起——这也是我没有直接动手的原因。

### 3. 仍需**你**决策的两件事

- **金标集是否人工确认**：`support_precision` 现在是 **AI 裁判 proxy**（0.857/0.182/0.625），
  人工真值口径的 `overall_score` 仍为 null。要出人工真值分，需要看过
  ``GET /api/papers/{id}/golden-set`` 后调 ``confirm``；我实测过草案内容与抽取断言
  内容不重合，直接 confirm 会得到一个**误导性的低分**，所以建议"人工编写关键断言"或逐条复核。
- **方法步骤附近确实没有图表的场合**：是否列出"本章节图表"作参考（**明确标注非该断言专属**）？
  我倾向不列 —— D-48 撤掉"全篇第一张图"就是因为会被读成"这就是它的证据"。

## D-62 问答"答不出来/一直在转"的四个真缺陷 + 图谱"断裂图"的真因

### A. 图谱图表节点显示成"断裂图"

- **真因**：我上一版用 ``<img src="/api/assets/{assets[0].id}">``，而实测 ``assets[0]`` 是
  ``kind="source_pdf"``（**源 PDF**）——该媒体的 ``original_asset_ids`` 是空的，
  ``policy.default_mode="extracted"``、``label="提取表示（无可用原件）"``。
  把 PDF 塞进 ``<img>`` 就是浏览器里的"什么都没有的断裂图"。
- **修法**：改用应用里**统一的来源媒体组件** ``SourceMedia``（它按 ``resolveMediaPolicy``
  决定展示层级：有原图给原图 → 表格/公式走提取表示 → 缺原件回退整页预览 → 都没有就明确说明）。
  **纪律**：媒体展示只能走这个组件，不要自己拼 asset URL。
- 实测：图表节点现在渲染出真实的表格/图片（paper 1/3 的 media 各自有 16/23 个资产）。

### B. 用户点名的三个问题全部答不出来（或一直在转）

**实测（修复前 → 修复后）**：

| 问题 | 修复前 | 修复后 |
|---|---|---|
| 这篇论文哪里最值得质疑？ | 1.3s 拒答（模型返回空 claims） | **9.8s**，grounded，654 字，5 条证据 |
| 这篇论文的主要贡献是什么？ | 104s，后来 300s 超时 | **18.7s**，grounded，1509 字，6 条证据 |
| 论文用了什么数据集？ | 1.5s 拒答 | **14.2s**，grounded，引用了 BOSSv0.92/BOSSv1.01 |
| 本文是如何使用 Kubernetes…？ | 拒答 | **仍 1.4s 拒答**（不编造这条没被放宽） |

为此查出并修掉**四个**真缺陷：

1. **模型给的引用被系统性拒收**：提示词要求"原样复制片段方括号里的标识"，上下文是以
   ``[chunk_id] 正文`` 拼的，而 ``_gate_claims`` 只接受 ``allowed_blocks``（**块 id**）
   → 模型给的对引用**必然无效**，只能靠确定性恢复兜底；恢复失败就整句丢弃（实测 4/4 句被丢）。
   修法：新增 ``_claim_block_ids``，chunk_id → 映射成该片段的块，两种都认。
2. **被 token 上限截断后原地重试，白烧 127s**：实测一次草稿发 5 次请求，其中
   ``max_tokens=1200`` 与 ``2048/3686`` 三次都是**用满上限的截断**（每次 26–82s），
   模型自己只用了 10.5s。修法（两层）：
   - ``ai/service``：识别"输出正好等于上限"= 截断，**放大预算再试**（×1.8，封顶 8192），
     而不是拿同样的预算重试；截断不再是"无意义的重复"。
   - ``qa``：**把要的输出压小**（answer ≤200 字、claims ≤4 条、quote ≤80 字），
     预算回到 1600；仍失败则用"更小的要求"重试一次。**治本是压小要求，不是加大预算。**
3. **逐句语义判定没有批量**：一条回答 4–7 句 → 4–7 次 LLM 调用（每次 2–20s）。
   修法：新增 ``semantic.batch_judge``（一次调用判多句），问答在 gate 前先判一轮、
   把结果按句写进 ctx 预置位。**顺带发现一个"死钩子"**：``evidence.validate`` 会读
   ``ctx._semantic_verdict``，但 ``CallContext`` 是 ``extra="forbid"`` 的 pydantic 模型、
   又没声明该属性 → **该钩子永远读到 None、形同虚设**；改为 ``PrivateAttr`` 才真正可用。
   - 另修一处顺序问题：**必须先做引用恢复、再做批量判定**。实测篇幅收紧后模型常常
     **完全不给 quote/block_ids**，先批量就会因"没有证据文本"整批跳过。
     批量判定的证据文本现在按 ``quote → 该片段正文 → 整段检索上下文`` 三级兜底。
4. **短事实问题检索不到关键段落**：问"论文用了什么数据集"，召回里**一句数据集都没提到**
   （答案句在 5.1 实验章），模型只能返回空 claims。修法：``_query_terms`` 抽出内容词
   （中文按**最长优先剔除停用词**，不是滑窗——滑窗会产出"文用了什"这类垃圾查询），
   用它**再检索一次**并与主结果按 chunk 去重合并。

### C. 兜底路径也要批量 + 必须有截止时间

- ``extractive_fallback``（模型草稿全被 gate 拒时的兜底作答）同样逐句判定 → 实测 7 句 7 次调用；
  现在也先批量再注册。
- **截止时间**：SSE 路径此前**完全没有 deadline**（供应商慢就无限挂着 = 用户看到的"一直在转"），
  现在 ``QA_STREAM_DEADLINE_MS=120_000`` 且带预算；旧入口从 300s 收到 **120s**，
  到点由 AI 层抛 ``DEADLINE_EXCEEDED``、问答降级为抽取式作答或明确拒答 —— **必须给出交代**。

回归测试：``test_qa_latency_and_citations.py``（13 条：截断放大/封顶、chunk 引用映射、
两处投影一致、批量预置与回退、内容词抽取与二次检索、截止时间存在且有界）。

## D-63 网址导入必须验明是 PDF；AI 起草参考断言；评测用哪一版参考集必须确定

### A. 网址导入：入库前**验明是 PDF**（否则库里多出一篇永远解析不出来的"论文"）

- **实测**：把 arXiv 的**摘要页**（``/abs/1706.03762``）贴进来会返回 **HTML**（43KB），
  而旧实现**不看内容一律存成 .pdf** 并建论文 → 解析阶段必然失败，用户看到一个永远卡住的条目。
- **修法**：下载后先验明真 PDF（魔数 ``%PDF-`` 优先，content-type 只在字节对不上时兜底判断），
  不是就 **400 并给出能照做的说明**（"请粘贴论文 PDF 直链，如 arXiv 的 /pdf/xxxx"），
  **不建论文、不建 revision、不留垃圾数据**。回归测试 `test_url_ingest_guard.py`（5 条）。
- **示例网址因此只列实测可用的 PDF 直链**（见 D-64）。

### B. AI 起草参考断言（带**逐字引文校验**）

- **背景（用户指示"自动评测按你的建议改动"）**：句子挑选版参考集取的是"每块最像断言的一句"，
  与抽取产出的断言**内容不重合**（paper 2 的 precision 只有 **0.18**），AI 语义裁判再准也没用 ——
  **分母没对准**。
- **做法**：``golden_builder.build_golden_set_ai`` —— 让模型读原文**起草**关键断言
  （方法/指标定义、实验设置、带数字的结果、局限），但每条必须带 ``quote``，且该 quote
  必须**逐字出现在某个原文块**里，校验不过**直接丢弃**。真值来源仍是原文，模型只负责"选点"。
- **纪律**：① 没有模型/调用失败 → 返回**空集合**（不退回句子挑选冒充 AI 起草）；
  ② 题目与锚点仍用**确定性构造**（"不可答"必须由程序验证术语全文不出现，不能交给模型发挥）；
  ③ 集合仍按**调参集**保存（AI 起草 ≠ 人工确认），所以 ``support_precision`` 依旧是 proxy、
  人工真值口径的 ``overall_score`` 依旧 null。
- **实测（同一批答案，只换参考集）**：

  | 论文 | 句子版 precision / recall | **AI 版 precision / recall** | AI 综合分 |
  |---|---|---|---|
  | paper 1 | 0.857 / 0.500 | 0.857 / **0.545** | 93.59 |
  | paper 2 | 0.182 / 0.167 | **0.455 / 0.625** | **67.27 → 78.18** |
  | paper 3 | 0.625 / 0.417 | 0.625 / **0.455** | 85.0 |
  | paper 7（新导入） | 0.000（分母不重合） | **0.667 / 0.545** | **86.67** |

- 接口：``POST /papers/{id}/golden-set?source=ai``（默认仍是 ``builtin``）。
- 回归测试 `test_ai_golden_claims.py`（7 条：引文校验/来源块/无模型空集合/版本区分/题目不丢/优先级）。

### C. "评测用哪一版参考集"必须**确定**

- **真 bug**：同一篇可以同时存在句子版与 AI 版两个 ``(golden_id, version)`` 行，而
  ``find_for_scope_ex`` 只按 ``created_at`` 取最新 —— 于是**重建句子版就会悄悄换回旧版**，
  用户完全看不出来（实测 paper 7 的评测因此用了句子版，precision 停在 0.000）。
- **修法**：显式优先级 —— **人工确认过的（``is_tuning=False``）> AI 起草 > 句子挑选**，
  同级再比 ``created_at``。规则写进 docstring 与测试（`test_ai_set_is_preferred_over_sentence_set`
  与 `test_human_confirmed_wins_over_ai`）。

## D-64 主页示例论文网址（**全部实测可下载且可解析**）

- 位置：`frontend/app/upload/page.tsx` 的"粘贴网址"输入框**下方**，点击只**填入输入框**、
  不自动下载（避免误触发长任务）。
- 列表（容器内实测 HTTP 200 + `%PDF-` 魔数）：arXiv ``/pdf/1706.03762``（Transformer）、
  ``/pdf/1810.04805``（BERT）、``/pdf/1512.03385``（ResNet）、``/pdf/2106.09685``（LoRA）、
  以及 PLOS ONE 的 printable 直链。
- **为什么只列直链**：实测 MDPI 的 ``/pdf`` 返回 **403**、arXiv 的 ``/abs/`` 页返回 **HTML** ——
  这两类贴进来都会被 A 的守卫拒收，所以不列；输入框下方也写清了"要 PDF 直链"。

## D-65 打卡式提示词不足以保证"不答非所问"：加**确定性**的对象缺失判据

- **实测回归（我自己的改动引入的）**：为让"主要贡献/数据集/最值得质疑"能答，我把提示词放宽成
  "片段里有直接相关的句子就要照抄"。结果 paper 7（英文 arXiv 论文）的**四个"不可答"问题全被答了**
  （5–6 句）：问"用了 Kubernetes 吗"，回答给的是"用了 8 块 P100 GPU"——
  **答非所问**，`unanswerable_refusal_rate` 会从 1.0 掉到 0。
  先加了提示词规则（"问题里的对象没出现就必须返回空数组"）——**模型没有照做**（再跑一次仍全答）。
- **修法（确定性判据，不依赖模型听话）**：``_object_absent_from_hits`` ——
  取问题的内容词，只对"像具体对象"的词做检查（拉丁词 ≥3 字符，或 **≥3 字且不含泛化学术词**），
  若这些词**一个都没出现**在检索文本里 → **强制拒答**（跳过模型草稿与抽取兜底），
  并记 ``question_object_absent`` 告警。
  - 泛化学术词表（质疑/局限/贡献/创新/数据集/方法/结论/实验/结果…）专门用来**避免误伤**用户点名要答的三类问题；
    实测"论文用了什么数据集"（泛化词不检查）与"哪里最值得质疑"（"质疑"仅 2 字）都**不会被误拒**。
- **实测（paper 7 题库重跑）**：四个章节题仍全部作答（3–4 句），
  四个不可答问题**全部 abstained**；题库总耗时 77s → **32s**（拒答不再白跑生成）。
- 回归测试：`test_qa_latency_and_citations.py::TestAbsentObjectRefusal`（4 条，
  含"用户三类问题不得被误伤"与"对象缺失时必须拒答且不调用模型"）。

## D-67 导入的 revision 必须登记模型快照（"问了转圈后没反应"的根因）

- **用户实测**："证据问答依旧是问了之后转圈圈转了一会就没反应了"。
- **排查**（先证后端）：SSE 本身正常（8.7s、14 个事件、有 final）；再证判据：聊天类问题
  确实被判成"非论文问题"（`_is_paper_related=False`）；**最后一层才找到**：
  `qa._snapshot_id(ctx)` 恒为 **None**。
- **根因**：`papers.create_revision` **只在 `ctx.model_snapshot` 非空时**才登记
  `model_snapshots` 行并把 `revision.model_snapshot_id` 指向它；而 `pipeline.ingest`
  建 revision 时**没传 ctx**。于是：
  - `snapshot_for_revision` 回退到**运行时快照**（有 chat_model 但 **没有 id**）；
  - `qa.service` 看到 `snapshot_id is None` → 判"无模型" → 草稿走**抽取式**、
    `_general_answer` 直接返回 None（**通用回答永远不可能成功**）。
  - 实测：paper 1–3（早期 seed）snapshot=uuid；paper **7/9/10（网址/上传导入）snapshot=None**。
- **修法**：`pipeline.ingest` 新增 `_ingest_ctx()`（带运行时快照），建 revision 与跑 pipeline
  都用它；`rebuild-derived` 增加 `snapshot` 项作为**老数据回填**入口（已回填 7/9/10）。
- **实测（回填后 paper 7）**：`你好，你能做什么？` → **general，243 字，4.9s**；
  `什么是量子纠缠？` → general 279 字；`这篇论文的主要贡献是什么？` → generated/grounded 5.3s；
  `论文用了什么数据集？` → grounded 473 字 9.6s；`Kubernetes`（不可答）→ 仍 abstained 0.9s。
- 回归测试 `test_ingest_model_snapshot.py`（2 条）。

## D-68 表格/公式里的 LaTeX 要**就地渲染**，孤立 `$` 要清掉

- **用户实测**："表 2 有类似 `$1.0 \cdot 10^{20}$` 这样的未转义字符"、"证据里显示的
  `$P _ { d r o p } = 0 . 1$` 也是没成功转义"、"结构化导读和全文原文像一堆乱码"。
- **查证**（不是猜）：扫描 paper 7 的 9 段章节 + 15 页文本，统计出
  行内 `$...$` **157** 处、块级 `$$...$$` **10** 处（`MathText` 都能渲染），
  但**跨行/落单的 `$` 有 79 处**（MinerU 标记不配对）→ 这些 `$` 会**原样显示**；
  另外表格走的是 `table_html` + `dangerouslySetInnerHTML`（`ExtractedTable` / `TableRender`），
  **完全没过 KaTeX** → 单元格里的 LaTeX 就是源码（表 2 的 `$1.0 \cdot 10^{20}$` 来源）。
- **修法**：
  1. 新增 `lib/mathHtml.ts`：`renderMathInHtml(html)` 在**已消毒的 HTML** 里把
     `$$...$$` / `$...$` 就地替换为 KaTeX 输出（渲染失败原样保留，绝不吞内容）；
     `ExtractedTable` 与 `TableRender` 都改用它。
  2. `MathText.cleanPlain` 增加"清掉**未配对**的 `$`"（MinerU 残留不再是乱码）。
- **说明**：正文里的公式本来就是渲染的（157 处走 KaTeX），之前被当成"全是乱码"的主因是
  表格未渲染 + 落单 `$`；这两处已修。

## D-69 官网链接 / 图谱表公式节点 / 问答界面 / 方法步骤文案

- **"查看论文官网"跳到 localhost 的坏链**（用户实测）：`papers.pdf_url` 存的是**容器内路径**
  （`/app/data/uploads/attention-is-all-you-need.pdf`），前端拼成
  `http://localhost:4002/app/data/...` → 必然 404。修法（ADR-0069）：
  ① 网址导入的论文用**原始来源 URL**（`source_documents.source_url`）；
  ② 上传件指向本服务的文档接口 `/api/papers/{id}/document`（实测 200 application/pdf）；
  ③ 前端对相对路径补 `absoluteApiUrl`，并把文案改成"查看论文原文"。
  **注意**：我在 `routes.py` 里第一版写错了模型类名（`SourceORM`，实际是
  `SourceDocumentORM`），异常被 `except` 吞掉 → 先看返回值才发现没生效；正确的中枢是
  `papers.service._official_url`（canonical 详情走的是那条路）。实测：paper 7 →
  `https://arxiv.org/pdf/1706.03762`；paper 10 → `/api/papers/10/document`。
- **图谱里表/公式节点显示"不可用 + 未找到任何可展示原件资产"**：`resolveMediaPolicy` 在
  "有源但无裁剪、无整页锚点"时**直接判 unavailable**，哪怕媒体有 `extracted.table_html/latex`。
  修法：该分支先看有没有**提取表示**，有就给 `extracted`（标签"再排版 / 提取"），
  于是表格/公式能在节点里显示（且经 D-68 会渲染公式）。
- **问答界面"转圈后没反应"的第二层**（前端）：
  1. 流**结束但没有 final**（超时/中断）时，旧代码什么都不做 → 界面静默。现在会把已收到的
     句子落成一条消息并写明"本次回答被中断，以上是已生成的部分"，不再空白。
  2. SSE 路径构造的 `legacy` 漏了 `mode` 字段 → 通用回答在界面上按"拒答"样式渲染；
     已补 `mode` 透传。
- **方法步骤文案**：用户看到 `**同页/相邻页**` 字面星号（我在 JSX 文本里写了 Markdown）→
  已改为纯文本；并**移除**"查看论文原图（图 N，非本步骤专属）"按钮
  （用户要求：该步骤什么都没引用时就不该给出引用）。
  同时扫掉 EvalView / MethodView / QAView / 上传页里所有**会显示出来**的 `**`（共 9 处）。

## D-70 导入即自动 AI 评测（"自动评测里全是未评测"的根因）

- **用户实测**："自动评测那里的指标都是显示未评测，不是说自动评测吗，应该直接 ai 评测。"
- **根因（两处）**：
  1. `stage_qa_bank` 只认 `spec["bank_questions"]`，而导入流程**从不设置**它 →
     这一步**永远 skipped** → 拒答率/引文精确率/时延**没有分母**；
  2. `stage_evaluate` 只传 `statements + media` —— **不带金标集、不带已作答的题库** →
     几乎所有依赖真值/答案的指标都是 `not_evaluated`。
- **修法**：
  - `qa_bank`：没有显式题库时，**先用金标集的问题**；没有金标集就**先让 AI 起草参考断言**
    （带逐字引文校验），再拿它的问题去问 —— 导入完即有一套可核对的问题与真值；
  - `evaluate`：改用旧入口的 `_input_for(scope)`（收集 statements/answers/golden/media/
    navigation_checks），**口径与 `GET /papers/{id}/evaluation` 完全一致**。
- **实测（paper 10，此前 10 项"未评测"）**：直接跑这两个阶段 → `qa_bank` 成功（自动建
  AI 参考集 + 答 8 题）、`evaluate` 成功 → **未评测降到 5 项**，并出现
  `ai_overall=65.56 / precision=0.1724 / quote=0.9333 / refusal=1.0 / anchor_page=1.0`。
  对照：paper 1 与 paper 7 现在只剩 **1 项**未评测（`anchor_region_hit_rate` —— 原文没有
  坐标矩形，**拒绝编造 IoU**）。
- **代价（如实说明）**：导入时多出"AI 起草参考断言（~30s）+ 题库作答（8 题 × ~15s）"，
  所以一次导入从 ~140s 变成 ~4 分钟；这是"导入即评测"的必要成本。

## D-47 附（措辞修正）

原文写"Compose 的 `.env` 是按当前工作目录查找的"，实测更精确的说法是：**Compose 先看当前工作目录的 `.env`、再看项目目录（compose 文件所在目录）的 `.env`，前者优先**。证据：`backend/.env` 存在时（以 `backend/` 为 CWD）端口/CORS 被它覆盖成 8001/3001；把它改名后，同样的工作目录又能正确读到根 `.env`（8002/4002、`DEMO_MODE=false`）。

---

# 第五批：REFACTOR_PLAN（docs/REFACTOR_PLAN.md）M1–M8 落地

## D-71 富文本渲染统一到**一个内核**（"看论文像看乱码"的根因与修法）

- **用户实测**：结构化导读/全文原文里出现 `Ashish Vaswani<sup>∗</sup> Google Brain
  avaswani@google.com`、`$P _ { d r o p } = 0 . 1$`；"原件媒体"的介绍里出现
  `$$ \operatorname{Attention}(Q,K,V)=…\tag{1} $$`。
- **根因（四处各写各的 + 一个真 bug）**：
  1. 正文走 `LongText → MathText`：`MathText` 自己实现了一套 `$…$` 切分，**且把 `<sup>`
     当普通文本 `escapeHtml`** → 标签变成字面量；
  2. 表格走 `TableRender/ExtractedTable` 的 `dangerouslySetInnerHTML`，另有一套
     `renderMathInHtml`；媒体介绍走 `ExtractedFormula`，把**带 `$$` 定界符与 `\tag`
     的原始串**直接丢给 KaTeX（`throwOnError:false` → 渲染成红色错误串）；
  3. 证据引文走 `RichText`（`**bold**`/`图N` 那套），**完全没有公式渲染**；
  4. **真 bug**：`LongText` 先 `split(/\n/)` 再逐段渲染 → **跨行块级公式
     `$$\n…\tag{1}\n$$` 被拦腰截断**，永远配不成公式 —— 这才是"媒体介绍里那段 LaTeX 原样显示"
     的直接原因（`MathText` 收到的是半截 `$$`）。
- **修法**：新增 `frontend/lib/richtext.ts` 作为**唯一**解析/渲染内核
  （`parseRichText` / `renderRichHtml` / `splitParagraphs` / `compactLatex` /
  `renderMathInHtmlString`），并把 `MathText`、`LongText`、`TableRender`、
  `RichText`（方法步骤/问答正文）、`ExtractedFormula`、`SourceMedia` 的题注
  **全部改为委托它**。内核规则：文本一律 `escapeHtml`；行内标签只放行
  `sup/sub/i/b/em/strong/code/br`；公式压掉 MinerU 的 token 断裂
  （`P _ { d r o p } = 0 . 1` → `P_{drop}=0.1`）；`\tag{N}` 剥离成编号角标；
  未配对 `$` 丢弃并记 `UNPAIRED_DOLLAR`；KaTeX 失败降级为**去定界符**的等宽文本
  （绝不让 `$`/`$$`/`\tag` 出现在 DOM 里）；`splitParagraphs` **数学感知**，不再切碎块级公式。
- **实测（真实数据，不是截图）**：`.scratch/verify_richtext_live.cjs` 把线上 API 返回的
  每一条文本都喂给内核 —— paper 7（Attention）扫描 70 段：剩余 `$` **0**、
  被转义的标签字面量 **0**、残留 `\tag` **0**、渲染出 KaTeX **1302** 个；
  paper 1：60 段 / 1190 个公式，paper 10：106 段 / 1287 个公式，**均为 0 残留**。
- **测试**：`frontend/tests/richtext.spec.ts`（`npm run test:rich`，23 条）覆盖
  `<sup>` 语义化、行内/块级公式、`\tag`、未配对 `$`、`\$` 字面美元、非白名单标签、
  控制符、幂等、`plain`/`rich` 逐字一致、KaTeX 降级、表格 HTML 就地渲染、以及
  `<script>`/`<img onerror>` 不产生可执行节点。
- **踩坑（值得记）**：内核第一版把扫描正则放在模块级并递归调用自己解析 `<sup>` 内容 →
  **`g` 正则的 `lastIndex` 被递归覆盖 → 死循环吃满 4GB 堆**（node OOM）。现在每次调用
  新建正则实例。另有占位符选了 `\u0001`，被控制符清洗规则当脏字符删掉，
  导致 `rf\$importance` 里的 `$` 静默消失 —— 占位符改用私用区 `\uE000/\uE001`。

## D-72 问答「论文相关」判据加宽 + 拒答**必须有话可说**

- **用户实测（2026-09-12，paper 7 逐条探针）**：
  | 问题 | 修前 | 修后 |
  |---|---|---|
  | 这篇论文哪里最值得质疑？ | `abstained`，**answer 空串** | `abstained`，**如实说明 + 最接近的原文片段** |
  | 主要贡献是什么？ | `general`（用通用助手口吻答"我提供的是通用助手…"） | **`generated` + 2 引用 + 真答案** |
  | 论文用了什么数据？ | `abstained`，空串 | `abstained`，**如实说明 + 片段线索** |
  | 你好，介绍一下你自己 | `general`（本来就对） | `general`（不变） |
- **根因一（路由错）**：`_is_paper_related` 只认"论文/本文…"指向词 + `vector_score ≥ 0.6`。
  **实测同一篇论文上所有问题的 `vector_score` 都在 0.41–0.60**（包括明确指向论文的问题），
  0.6 这条线**实际不可达**；而 rerank 分能到 0.55–1.0。→ 加两路判据：
  ① 学术话题词（贡献/数据集/局限/实验/指标/训练…，日常闲聊几乎不出现）；
  ② `rerank_score ≥ 0.6`。闲聊与领域常识仍走 `general`（不受限问答这条不能丢）。
- **根因二（空白拒答）**：`_abstained` 产出 `ArtifactText(text="")`，前端只渲染
  statements/answer 文本 → 用户看到"无证据支持"外加一片空白，读成"根本没调用到模型"。
  → 拒答模板化：问的是**具体对象**（"论文提到 Kubernetes 了吗"）→
  `mode="not_mentioned"` 且点名对象；否则 `mode="abstained"` 解释为什么答不了；
  两者都附一条**逐字来自检索结果**、明确标注"未通过证据校验、仅供参考"的最接近片段
  （不产生 evidence、不影响 grounded）。另加 `_ensure_readable` 兜底不变量：
  **任何**落库答案都必须有正文或句子，空了就补如实说明。
- **改动面**：`contracts/qa.py`（`AnswerMode` 加 `not_mentioned`）、
  `qa/answer_gate.is_abstention`、`evaluation/metrics` 的拒答口径同步认它
  （口径变了两处指标才不会虚高/虚低）。前端 `QAView` 新增"论文未提及 / 通用回答·未用论文证据"
  两种徽标。
- **测试**：`backend/app/tests/unit/test_qa_answer_integrity.py`（16 条，含"真实量级
  vector_score=0.48 仍必须判为论文问题"这条回归锁）。

## D-73 SSE **终结事件保证** + 断流恢复（"本次回答被中断"的服务端根因）

- **用户实测**：证据问答三条默认问题都显示"本次回答被中断或超时，没有生成内容"。
- **根因（服务端侧，两处真缺陷）**：
  1. `stream()` 里**只有 `svc.answer(...)` 那一句在 try/except 内**，后面发
     status/citation/sentence/final 的整段在保护区**之外**：那里一旦抛异常，生成器直接死掉、
     连接关闭，**既没有 final 也没有 error** → 前端只能显示"被中断"；
  2. 更隐蔽：`terminal.claim("final")` 在 `_final_payload(record)` **之前**调用 ——
     投影一旦抛异常，终态位已被占，error 事件**发不出去**（现在先投影、后占位）。
- **顺带修掉一个必然触发的 bug**：等待生成的循环里 `remaining = deadline - now` 得到
  `timedelta`，`min(float, timedelta)` 直接 `TypeError` → **每一次真实 SSE 都会变成
  INTERNAL_ERROR**。由新增的"final 必须存在"测试当场抓住（`total_seconds()` 修复）。
- **修法**：所有事件都进保护区，任何异常收敛成唯一 `error`；等待期间按
  `HEARTBEAT_SECONDS` 发注释帧 `: ping` 保活（一次草稿实测可长达 100s+）；
  按 `ctx.deadline_at` 兜一层**流级**总闸（`ai.complete` 的截止时间只管模型调用那一层）；
  新增 `GET /papers/{id}/qa/answers/{answer_id}`：`meta` 事件先发 `answer_id`，
  前端断流后凭它取回**已落库**的结果，而不是让用户重问、白烧一次调用。
  新增错误码 `STREAM_NO_TERMINAL_EVENT`（服务端自检，理论不可达，出现即报警）。
- **实测**：修后四条问题（两条论文内、一条领域常识、一条闲聊）**全部**以 `final` 结束
  （`meta→status→status→…→final`），无一条"被中断"；恢复端点对已有 answer_id 返回
  `status=completed` + 完整 legacy 投影，对不存在的 id 返回 404。
- **测试**：`backend/app/tests/unit/test_qa_stream_contract.py`（12 条）覆盖成功/生成异常/
  **发事件阶段异常**/final 投影异常/超时取消/DomainError/心跳/空正文兜底/
  终结事件恰一次且此后不再发事件。

## D-74 研究图谱改为**分层布局**（"节点全堆在一起、看不到关系名字"）

- **用户实测**：图谱节点密密麻麻、关系线纠缠、看不到关系名字。
- **根因**：布局是手写的 `x: col*250, y: row*90` —— **行距 90 小于节点实际高度
  （约 104px）**，同列节点直接互相压住；连线与边标签都被节点盖掉。
- **修法**：新增 `frontend/lib/graphLayout.ts`（纯函数、零依赖，不引 ELK/dagre/cytoscape）：
  泳道（按 kind 分列，列宽 = 节点宽 + 间距）→ 拓扑分层（Kahn 最长路径，**有环不死循环**）
  → 层内按原始序 → `y = 行号 × (节点高 + 间距)`，**行距大于节点高，全局无重叠**；
  边标签放中点，与节点包围盒相交时逐级纵向避让，避不开就 `hidden`
  （**宁可不显示，也不让文字压在节点上**）。确定性：同输入同输出。
- **实测**：`npm run test:graph`（9 条，`frontend/tests/graphLayout.spec.ts`）对
  39 节点/33 边、100 节点图断言"任意两节点包围盒不相交"、边标签不压节点、
  同输入两次调用 deep equal、含环图有位置、100 节点布局 < 200ms、bounds 覆盖全部节点。

## D-75 `textnorm` 模块（M1）落地，但**尚未接入流水线**（如实登记）

- **做了什么**：新增 `backend/app/modules/textnorm/`（纯规则、零 LLM、零 DB）与
  `backend/app/contracts/textnorm.py`，对外只暴露 `normalize(text, kind)` 与 `scan(text)`，
  产出 `NormalizedText{plain, rich, issues}`；`backend/app/tests/unit/test_textnorm.py` 88 条全绿。
- **明确未做（不要误解为已生效）**：**没有任何既有模块 import 它** —— 导入阶段的
  `textnorm` 阶段、`blocks.normalized_*` 落库、以及 M5（证据门判定输入规范化）
  都还没做。当前线上"看起来正常"靠的是前端内核（D-71）与后端原有的清洗逻辑。
- **一处与任务书的偏离（有理由，已锁测试）**：plain 里未配对 `$` 写作 `\$`、
  未知标签写作 `&lt;unk&gt;`。任务书同时要求"plain 保留字面 `<unk>`"与"二次 normalize
  不再产 UNKNOWN_TAG"，这在纯字符串上不可兼得（plain 里出现字面 `<unk>` ⟺ 再命中一次）。
  选择幂等 + 不丢字符（转义可逆，测试断言实体解码后与原文逐字相同）。
- **下一步**：M5 把 `textnorm.normalize` 接进证据门（判定输入用 `plain`、保留 `raw` 供逐字核对），
  这才是它真正产生价值的地方。

## D-76 图片查看器加旋转/缩放（"很多图方向反了"）

- **用户实测**："很多图方向反了，要求点击图片展示时加旋转按钮。"
- **修法**：新增 `frontend/components/media/MediaViewer.tsx`（旋转 90° 步进 / 缩放 / 复位，
  工具栏浮在右上角并显示当前角度与倍数）+ `frontend/lib/mediaView.ts`（角度归约、
  缩放夹取、transform 串的**纯逻辑**）。接入两处看图入口：`MediaModal`（点"图 N"打开的大图）
  与 `SourceMedia` 的原件/整页预览（图谱节点详情也走 SourceMedia，因此自动获得该能力）。
- **纪律（任务书 P6）**：旋转**只存在于视图层**（CSS `transform`），不改资产字节、不上传；
  组件卸载即复位；缩放夹在 0.25–4 倍；旋转 90/270° 时容器改为可滚动
  （宁可滚动，不裁掉内容）。旋转后点图仍能打开大图（工具栏按钮在图片节点之外，不误触发）。
- **测试**：`npm run test:media`（6 条）：角度恒在 {0,90,180,270}、左转不出现负角度、
  缩放边界夹取、非法输入回落、transform 串正确、旋转后容器高度不缩水。

## D-77 证据门：判定输入先规范化 + 判定理由必须透出来（M5）

- **用户实测**："这些未转义导致证据链里引用到这些证据显示『未支持』"。
- **根因（两处）**：
  1. `evidence.service.validate` 把 `_evidence_text_for(...)` 拿到的**原文切片原样**送给
     语义判定模型 —— 切片里带着 MinerU 的 `$P _ { d r o p } = 0 . 1$`、`<sup>∗</sup>`、
     跨行 `$$…\tag{1}$$`，模型读到的是符号噪声而不是可读句子，判定大面积落到
     `insufficient`（界面就是"引用到的证据却显示未支持"）；
  2. 模型**其实输出了 `reason` 字段**（`_Verdict.reason` 是必填），但 `judge()` 返回时
     被丢弃成固定串"模型语义判定"，`gate.semantic_model_reason` 也不存在 ——
     用户问"为什么判未支持"时**没有任何答案可看**。
- **修法**：
  - 新增 `evidence.semantic.normalize_evidence_text(text) -> (clean, issues)`：走
    `textnorm.normalize`（M1），**只返回新串、不就地改写原文**（落库引文仍逐字来自原文块，
    纪律 3 不破）；`textnorm` 不可用时**降级为原文**，绝不中断 gate；
  - `judge()` / `batch_judge()` 内部对陈述与证据都做规范化（所有调用方自动受益）；
  - `judge()` 把模型的 `reason` 作为 message 返回；`GateInput` 新增
    `semantic_model_reason`，`service.validate` 重跑 gate 时把它带进去 →
    `ValidationReport.reasons[].message` 里能直接看到"模型语义判定：<模型给的理由>"。
- **实测（真实数据，容器内探针 `.scratch/verify_m5.py`）**：paper 7 的 **173 个 block 中
  有 48 个**带 `$`/`<sup>`/`\tag`；规范化后 `Ashish Vaswani<sup>∗</sup> Google Brain …`
  → `Ashish Vaswani∗ Google Brain …`，`$`/`<sup>`/`\tag` 残留**为 0**。
  （即：此前**约 28% 的证据切片**是带着符号噪声进判定模型的。）
- **如实说明（未做完的部分）**：本次**只证明了"送进模型的输入干净了"**，
  **尚未**用同一批 statement 跑"修前/修后 supports 率对比" —— 那需要重跑 verify 阶段
  （LLM 调用量大），是下一步。所以"未支持变少"目前**只是机制上的推论，不是实测数字**。
- **测试**：`backend/app/tests/unit/test_evidence_semantic_normalization.py`（10 条）：
  脏证据送模型前已干净、原文不被就地改写、干净文本零 issue、陈述同样规范化、
  批量判定同样规范化、依赖不可用降级为原文、模型 reason 透出、空 reason 回落、
  非法 verdict 仍不猜、gate 状态不被破坏。全量 **709 passed / 0 failed**。

### D-77 附（**实测推翻了我自己的因果假设**，必须更正）

上一段把"证据显示未支持"归因到"脏文本干扰判定"。**实测不支持这个因果**。
A/B 对照（同一批陈述、同一段原文、同一个模型，只差输入是否规范化）：

| 样本 | A 臂（未规范化） | B 臂（已规范化） |
|---|---|---|
| 已通过验证的 8 条陈述（`verify_m5_ab.py`） | 6 supports / 2 insufficient | **6 / 2（完全一致）** |
| 6 段脏 block 当证据（`verify_m5_dirty.py`） | 6 supports | **6 supports（完全一致）** |

→ **判定改变 0 条。** `qwen-plus` 对 `$P _ { d r o p } = 0 . 1$`、`<sup>∗</sup>` 这类噪声
并不敏感。另外第一份样本里 **脏切片 0 条**：能通过 gate 的陈述，其证据本来就是干净的
（脏 block 是作者行/公式行，从来不是被引用的那一段）。

**结论**：M5 的规范化仍然值得保留（送进模型的文本干净、理由可解释、可审计），
但**它不是"未支持"的原因**；把它写成"修好了未支持"会是假归因。

## D-78 「未支持」的**真实分布**（实测，问题定位，修法待下一轮）

- **实测方法**：直查 `validations` 表按 `(semantic_status, decision)` 分组，并打印非
  `supports` 记录的 `reasons`（`.scratch/verify_unsupported.py`，paper 7）。
- **实测结果**：非 supports 的记录里，`reasons` 稳定是这一组：
  - `quote_mismatch`「引用的原文片段在该 block 中找不到」
  - `coordinate_missing`「所有候选引用都未能在原文中定位」
  - `unsupported_entailment`「**证据原文为空**」
  - 另有 `numeric_mismatch`（陈述含数字但无证据）、以及一条 `contradiction`（Adam 优化器那条）。
- **关键推断（有据但尚未验证）**：`证据原文为空` 说明**语义判定根本没跑到**
  （`judge()` 在证据为空时直接返回未判定）—— 也就是说这些"未支持"与
  `$`/`<sup>` 无关，而是**引用定位失败**导致的空证据。
- **两个待查点（下一轮，按此顺序）**：
  1. `locator` **已经**有"规范化回溯匹配"与"去空白匹配"两级兜底
     （`locator.match_quote_text` step 2/2b），需要实测它在这批数据上**为什么没命中**
     —— 是候选 block 选错了，还是 proposed_quote 与 block 根本不同源；
  2. 样本里出现了 `[15] Rafal Jozefowicz…` 这种**参考文献条目被当成陈述**的记录：
     claims 起草阶段的产出质量本身可能就是"未支持"的大头（垃圾进 → 定位失败 → 未支持）。
- **纪律**：在上述两条查清之前，**不修改判定阈值、不放松 quote 校验**（那是拿指标换好看）。

### D-78 结案：真因是"引用挂错块"，修法是**全文逐字重定位**（不是放松校验）

**直查 DB 后的真因**（`.scratch/diag_quote.py`，paper 7）：每条 quote_mismatch 记录里，
**陈述文本与 proposed_quote 逐字一致**，但 `citations[].block_id` 指向的是**另一段原文**
（4 条样本里 3 条指到同页别的句子、1 条指到一个内容就是 `"2"` 的块）。
也就是说：**引用是真的、逐字存在于论文里，只是被挂到了错误的块上**，
而 `gate.build_candidates` **只在那一个块里找** → 找不到 → 「证据原文为空」→
语义判定根本没跑 → insufficient。`locator.locate_anywhere` 其实早就写好了，
**但全代码库没有一处调用它**（死代码）。

**修法**（`gate.build_candidates` + 新增 `gate._relocate_quote`）：引用在指定块里
定位不到时，在**本 revision 的全部块**里找真身。硬纪律：

- **只接受 precise**（精确子串优先，其次 locator 的规范化回溯匹配）；
  **模糊相似一律不返回** —— 那是拿指标换好看；
- `origin="generated"` 的 AI 摘要块**永远不能**成为重定位目标；
- 重定位后仍从**原文切片**取 `source_text`（不伪造 quote），并在 `reasons` 里留下
  可审计的一条：「模型给出的引用块不含该引用，已按全文逐字重新定位到块 X（匹配方式 exact）」；
- 只改**归因**，不改判定阈值、不放松 quote 校验。

**现场效果（真实数据、不调 LLM，`.scratch/verify_relocation.py`）**：
paper 7 里**全部 18 条**此前被判非 supports 的陈述，现在**都拿得到条目候选**，
其中 **17 条是靠重定位救回的**（此前它们的证据切片为空）。样例（陈述 ↔ 重定位到的块）：

```
Recurrent neural networks, long short-term memory [13] and gated … ↔ 同句所在的块
Attention mechanisms have become an integral part of compelling … ↔ 同句所在的块
In this work, we presented the Transformer, the first sequence … ↔ 同句所在的块
```

**如实说明**：这一步证明的是"**证据不再为空、能定位到逐字原文**"。
"最终 verdict 变成 supports/verified"还要走一遍语义 gate（需重跑 verify 阶段，LLM 调用量大），
那是下一轮的第一件事 —— 本节**不声称** supports 率已经提升。

**测试**：`test_evidence.py::TestQuoteRelocation`（6 条）—— 挂错块被重定位且指向真身块、
重定位理由是「重新定位」且带真身块 id、**只有模糊相似时绝不放行**、
全篇都没有的引用仍然失败、本来就在对的块里则不触发重定位、
`origin=generated` 的块绝不能被当证据。另更新一条旧用例
（`test_same_page_unrelated_content_not_supported`）：它原先把"引用挂了别的块"当成
必须失败的场景，与 D-78 的新语义冲突，已改用**全篇都不存在**的引用来守原意图，
并补一条"挂错块应当被重定位"的正向用例。

### D-78 收尾实测（重跑 verify，不是推演）

`.scratch/reverify_paper.py` 把 18 条非 supports 陈述**真的重跑**语义 gate 并落库（paper 7）：

| 阶段 | verified | 其他 |
|---|---|---|
| 重跑前 | 53 | 17 rejected(insufficient) / 2 rejected(supports) / 1 contested |
| D-78 重定位后 | **70** | 2 rejected / 1 contested |
| **18 条里 17 条翻转为 supports** | | |

**但翻转名单暴露了新问题**：里面混着 `[15] Rafal Jozefowicz…`（×3）、
`[20] Diederik Kingma and Jimmy Ba.`、`Provided proper attribution…`（Google 许可声明）。
这些句子**逐字就在论文里**（所以定位、引用校验都会通过），但它们**不是研究发现** ——
放进图谱/讲解就是"乱"。→ D-79。

## D-79 「非研究发现」过滤：参考文献/许可声明不许当已验证事实

- **触发**：D-78 重定位后，paper 7 有 **5–6 条参考文献/许可声明被判定为 verified**。
- **修法**（确定性文本形态，不看模型脸色）：`gate._is_non_claim_statement()` 识别
  `[N] 作者…`、`arXiv:xxxx.xxxxx`、`provided proper attribution`、`hereby grants`、
  `permission to reproduce|make|use`、`all rights reserved`；命中即在 `semantic_verdict`
  里直接返回 `insufficient`，理由写明「该句不是研究发现（参考文献/许可声明/页脚），不进入事实层」，
  由 `decide()` 落到非发布状态。
- **实测（同一条流水线，`.scratch/reverify_paper.py` + 正则筛选）**：那 6 条重跑后全部变成
  `insufficient / unverified`，**不再进事实层**。
- **最终净效果（paper 7）**：verified **53 → 64**（**12 条真实研究发现被救回**：
  此前因"引用挂错块 → 证据为空"被误杀），同时 **6 条噪声被挡在门外** ——
  两头都没有拿阈值换数字。
- **测试**：`test_evidence.py::TestNonClaimStatementFilter`（3 条）：参考文献条目不得 verified
  且理由含"参考文献"、许可声明不得 verified、普通研究句不被误伤（含 `arXiv:` 页脚判正例）。
  全量 **727 passed / 0 failed**。

## D-80 「原件媒体不可用」的真因：公式本体在 caption 里，不在 extracted.latex

- **用户实测（问题③）**："原件媒体里很多『不可用的标签 / 未找到任何可展示原件资产』，
  下面介绍还是 `$$ \operatorname{Attention}…\tag{1} $$` 未转义。"
- **实测数据（paper 7 的 14 条 media，`.scratch/verify_media_policy.cjs`）**：
  `('equation', extracted='-', asset='-') × 5` —— **5 条公式既无资产、`extracted.latex`
  也是 `null`**；而公式本体完整地躺在 **`caption`** 里（`$$…\tag{1}$$`）。
  旧策略只看 `extracted.table_html/latex` → 判 `unavailable`；同时正文又把 caption 当普通
  题注渲染 → 用户**同时**看到"不可用"和"未转义的 LaTeX 源码"。两半其实是同一个根因。
- **修法**：新增 `sourcePolicy.latexFromCaption()`（从严：必须含 `$$…$$`、`$…$` 或 LaTeX 命令，
  普通题注一律返回空串）与 `hasExtractedRepresentation()`；策略在"无原件裁剪/无页锚点"时
  把 **caption 里的公式**也算作一份"再排版/提取"表示；`ExtractedFormula` 在
  `extracted.latex` 为空时用 caption 渲染；`SourceMedia` 在这种情形下**不再把同一段公式
  当题注重复显示**。
- **实测（真实数据、真实资产）**：paper 7 前端策略分布从「9 extracted + 5 unavailable」
  变成 **「9 extracted + 5 original + 0 unavailable」**；5 条公式全部拿到提取表示。
  （上一版探针传了空资产清单，把图片误判成不可用 —— 已改成逐条取详情，避免得出假结论。）
- **如实说明（未做完）**：**后端 `visual/policy.py` 与前端 `resolveMediaPolicy` 仍然分叉** ——
  同一批数据上 **10/14 条判定不一致**（公式：前端 `extracted` / 后端 `unavailable`；
  图片：前端 `original` / 后端 `extracted`）。本次只修了**前端**（用户实际看到的那条路径）；
  按 REFACTOR_PLAN M4 把策略收敛成"后端一次判定、前端纯渲染"是**下一步**，本节不声称已完成。
- **测试**：`npm run test:policy`（`frontend/tests/sourcePolicy.spec.ts`，6 条）：
  caption 公式被识别、公式不再判不可用、普通题注仍如实判不可用（不许无中生有）、
  表格提取不受影响、真实 source 上的 synthetic 仍拒绝展示、有原件资产仍优先原件。

### D-80 收尾：前后端策略**收敛为 0 分叉**（M4）

- **实测发现的分叉（上一轮的探针）**：同一批 14 条 media 上，前端 `resolveMediaPolicy`
  与后端 `visual/policy.build_policy` **10/14 条判定不一致**：
  公式（前端 `extracted` / 后端 `unavailable`）、图片（前端 `original` / 后端 `extracted`）。
- **两个根因**：
  1. 后端 `_has_extracted()` 不认 caption 里的公式（前端已认）→ 公式被判"原件不可用"；
  2. 对**未验证绑定的 MinerU 裁剪**（实测 `repr=mineru_crop, verif=unverified`），
     后端判 `extracted`（标签"解析器提取图（来源未验证）"），前端判 `original`
     （标签"整页预览"）——**前端在把"位置推断"当成原件展示**，违反本项目"展示层不得
     把位置推断当原件/题注匹配"的纪律。
- **修法**：
  - 后端：`_MATH_IN_CAPTION` + `_caption_has_formula()`，`_has_extracted()` 认 caption 公式；
  - 前端：未验证裁剪一律 `default_mode: 'extracted'` + `UNVERIFIED_CROP_LABEL`
    （"解析器提取图（来源未验证）"），**但 `original_asset_ids` 照旧返回**；
  - `SourceMedia` 把**"视图选择"与"定性"分开**：后端 policy 定性（给如实标签），
    前端只决定拿什么渲染 —— **有图就给图，没图才用提取表示**。
    若不分开，"未验证裁剪"被判 `extracted` 后图片会凭空消失、只剩表格视图。
- **实测（真实数据 + 真实资产，`.scratch/verify_media_policy.cjs`）**：
  分叉行 **10 → 0**；14/14 前后端一致。
- **测试**：后端 `test_visual_policy_caption.py`（5 条：caption 公式算提取表示、
  行内 `$…$` 也算、普通题注不算、空 caption 仍不可用、`extracted.latex` 有值行为不变）；
  前端 policy 测试加到 7 条（新增"未验证裁剪 → extracted + 如实标签 + 资产仍返回"）。
  后端全量 **732 passed / 0 failed**；前端 `npm run test:lib` 45 条全绿。

## D-81 M11 文本卫生门禁：把"不乱"变成**可复跑的门禁**（而不是靠人眼看）

- **背景**：D-71 修好了渲染，但"以后别再乱"只能靠人眼截图验证，无法防回归。
- **做了什么**（两层，语料同一批、全部取自实测的 paper 7 / paper 10）：
  1. **离线门禁（CI 常绿、无外部依赖）**
     - 后端 `backend/app/tests/unit/test_text_hygiene_gate.py`：12 条真实脏样本 ×
       6 类不变量 = 72 条参数化断言（`plain` 无落单 `$`、无 `$$` 残留、
       `rich` 叶子无定界符/`\tag`、issue code 在枚举内、二次规范化不冒新 issue 种类、
       无控制符残留）；
     - 前端 `tests/richtext.spec.ts` 新增语料整批扫描（同一批样本渲染后：
       无多余 `$`、无被转义标签字面量、无 `\tag`）。
  2. **真实语料门禁（需要 backend 在跑）**：`frontend/scripts/verify-render-hygiene.cjs`
     + `npm run test:hygiene` —— 把线上 API 返回的论文文本整批喂给内核，
     发现"固定语料里还没有的新脏模式"。
- **门禁必须能红（自验证）**：两侧各有一条"故意喂未归类脏模式"的测试 ——
  后端断言 `<mark>` 被报成 `UNKNOWN_TAG`、前端断言同一样本也会被报出来。
  一个永远不会失败的门禁等于没有门禁。
- **踩到并修正的一个判定口径**：前端门禁第一版写成"输出里不许出现任何 `$`"，
  于是把 `the rf\$importance`（**字面美元**，渲染成 `$` 是**正确**的）判成违规。
  已改成"渲染出的 `$` 数量 ≤ 源串里 `\$` 的数量"，只有**多出来的**才算残留。
- **实测**：
  - `npm run test:hygiene`：paper 7（文本段 70，KaTeX 1302）、
    paper 10（文本段 106，KaTeX 1287）→ **多余 `$` 0 / 被转义标签 0 / 残留 `\tag` 0**；
  - 后端全量 **807 passed / 0 failed**；前端 `test:rich` **25 passed**。
- **一处两侧约定差异（记录，不是缺陷）**：未知标签在**后端 `plain`** 里写作实体
  `&lt;mark&gt;`（转义可逆 + 保证二次规范化幂等，见 D-75），在**前端渲染**里保留字面量、
  输出 HTML 时才转义。两侧都满足"不静默吞掉用户可见字符"。

## D-82 M10 收尾：未评测的**原因码**一路透到界面，并加一条双读一致性契约测试

- **背景**：D-10 已给 `MetricValue` 加了 `reason`，但前端读的是 legacy 投影
  （`metrics` 是 `name → number|null` 的 dict），里面**只有 `not_evaluated` 名单**，
  没有原因 —— 界面仍然只能说"未评测"，说不清"为什么测不了"。
- **修法**：
  - 兼容投影新增 `metrics["not_evaluated_reasons"] = {指标名: 原因码}`（**加法**，不破坏既有字段）；
    **两处投影都加**：`schemas/adapters.to_legacy_evaluation` 与
    `modules/evaluation/legacy.to_legacy_evaluation`；
  - 前端 `EvalView` 的"未评测指标"区把原因码翻译成人话显示（如
    `source_pdf_has_no_coordinate_rects → "原文没有坐标矩形，无法算区域命中（不编造 IoU）"`），
    并保留 hover 里带原因码的完整说明；未知码原样显示（不吞）。
- **实测（live）**：`GET /api/papers/7/evaluation` →
  `not_evaluated: ["anchor_region_hit_rate"]`、
  `not_evaluated_reasons: {"anchor_region_hit_rate": "source_pdf_has_no_coordinate_rects"}`，
  `overall_score=null` 且 `ai_overall_score=86.67`（人工真值口径与 AI 口径并存、互不冒充）。
- **测试**：新增 `test_eval_reason_exposure.py`（4 条）：适配器投影带原因码、legacy 投影带原因码、
  **两处投影的名单与原因表逐项相等**（这是 M9"双读一致性"契约测试的第一片，
  专门防"只修一处"——本仓库已经因为两处投影分叉出过事故）、原因表不得夹带数值。
  后端全量 **811 passed / 0 failed**。

## D-83 本轮验收记录（REFACTOR_PLAN M1–M8、M10、M11 全部落地）

**代码与测试（在 commit `0405292` 上实测）**

| 层 | 命令 | 结果 |
|---|---|---|
| 后端单测 | `python -m pytest backend/app/tests -q` | **811 passed / 0 failed** |
| 前端零依赖单测 | `npm run test:lib` | **47 passed**（rich 25 / graph 9 / media 6 / policy 7） |
| 前端真实语料门禁 | `npm run test:hygiene` | paper 7/10：多余 `$` 0、被转义标签 0、残留 `\tag` 0 |

**端到端验收（对着**运行中的四容器**跑，全部 0 失败）**

| 套件 | 覆盖 | 结果 |
|---|---|---|
| `.scratch/verify_route_a.py` | 论文 manifest/sections/exhibits/页码锚点/作者/年份 等路由与字段 | 失败 0 |
| `.scratch/verify_graph.py` | 图谱节点/边/无断裂图/断点证据可达 | 失败 0 |
| `.scratch/verify_e2e_extra.py` | `/claims` 详情、statement/evidence 字段、SSE 事件序列与 final 非空、前端 bundle 关键路径 | 失败 0 |
| `.scratch/verify_metrics_live.py` | 评测指标口径（proxy 有值、not_evaluated 不冒充 0、overall 未盖章） | 失败 0 |
| `.scratch/verify_qa_stability.py`（额外） | 论文 2/3 各 3 轮问答的稳定性 | 空答案 **0/9** |

**交付物清单（对应任务书章节）**：M1 `modules/textnorm/`；M2/M3 `lib/richtext.ts` + 六处消费方；
M4 `MediaViewer` + 前后端策略收敛；M5 `semantic.normalize_evidence_text` + 引用重定位 + 证据理由；
M6 SSE 终结事件保证 + 断流恢复端点；M7 判据加宽 + 拒答非空；M8 `lib/graphLayout.ts`；
M10 `MetricValue.reason` + 投影透出 + 双读一致性测试；M11 两层卫生门禁。
决策记在 D-71 … D-83。

**未纳入本轮（REFACTOR_PLAN 的优化项，留给后续版本）**：
M9 投影层收敛（把 `schemas/adapters.py` 与五处 `modules/*/legacy.py` 的重复投影合并成一处——
本轮只补了"双读一致性"测试作为安全网）、M12 阶段进度与断点续跑。

---

# 第六批：REFACTOR_PLAN_R3（docs/REFACTOR_PLAN_R3.md）

## D-84 M1 证据文本渲染**扩面**：漏面才是"未转义字符还在"的真因

- **用户实测**：证据链里仍看到 `For the base model, we use a rate of $P _ { d r o p } = 0 . 1$` 原文。
- **真因（纯展示层漏面，与判定无关）**：D-71 统一了渲染内核，但有 **8 处**直接把论文文本
  当 JSX 子节点裸插值，绕过了内核：`QAView`（问答正文、**证据卡 ×2**）、
  `GraphView`（节点正文、证据引文、节点题注）、`PresenterView`（分镜摘要、句标、图题）、
  `PaperView`（图题 ×2）、`EvidenceDrawer`（证据原文）。
  配合 D-77 附录的 A/B 实测（脏字符**不改变**判定，12 条样本 0 变化），可以定论：
  **不是引用没重做，也不是原文脏字符导致判定失败，就是漏面。**
- **修法**：8 处全部改为 `<MathText text={...} />`（委托 `lib/richtext.ts`）。
- **防回归（关键）**：新增 `frontend/scripts/check-text-paths.cjs` ——**穷举展示路径清单**
  （8 个文件 + 各自"显示什么"），在这些文件里禁止
  `>{ …source_text|quote|answer|body|caption|.text… }<` 这种裸插值；并带 `--self-test`：
  **往检测器里塞已知坏样本，断言它必须被报出来**（门禁必须能红）。已挂进
  `npm run test:lib`（`npm run test:textpaths`）。
- **实测**：门禁首次运行就报出 **8 处**（我原以为只有 2–4 处），修完转绿：
  「清单内所有展示点的论文文本都经过渲染内核 ✅」。
- **测试**：`npm run test:lib` 五套全绿（rich 25 / graph 9 / media 6 / policy 7 / eval 12）
  + 路径门禁 + 自验证。

## D-85 M8 指标解析统一：修"对象当数字用"，并发现**两份报告本身不一致**

- **用户实测**："说好了全部 ai 评测，但还是全部显示未评测。"
- **根因一（前端 bug）**：`EvalView` 优先读 `/exhibits` 里持久化的 canonical report，其
  `metrics` 是 `list[MetricEntry]`、每项 `entry.value` 是 `MetricValue` **对象**；旧代码把对象
  当数字用 → `toNumber(对象)` = NaN → **全部按"未评测"渲染**，而且因为该键已存在，
  legacy 的数字**不会覆盖**它。→ 新增 `frontend/lib/evalMetrics.ts` 作唯一解析入口
  （吃 number / `MetricValue` 对象 / `list[MetricEntry]` / dict 四种形态；认不出的形态标
  `unparsable` 并在界面显式报"数据异常（解析失败）"，**绝不静默当未评测**）。
- **根因二（数据本身，实测发现）**：用**真实响应回放**时发现两份报告打架 ——
  持久化报告把 10 项标成未评测/0，而 `/evaluation` 现算有真值：
  `quote_exact_rate 1.0`、`support_precision 0.6667`、`input_tokens 5213`、
  `qa_first_verified_ms 3767`、`unanswerable_refusal_rate 1.0` …
  → 解析规则定为**有值优先**（canonical measured/proxy 权威；canonical 无值时用现算值），
  同时 `findConflicts()` 把"两源不一致"**显式**提示给用户（不静默挑一个）。
- **实测（真实响应回放）**：`0.3571 / 1 / 1 / 5213 / 3767 / 1` 均可显示，
  仅 `anchor_region_hit_rate` 仍是未评测，并按 M9 标"**不适用**"（原文无坐标矩形、拒绝编造 IoU）。
- **留给下一轮（如实登记，未解决）**：① canonical 的 `support_precision = 0 (proxy)`
  会盖掉现算的 `0.6667` —— "有值即权威"分不清"真实的 0"与"过期的 0"，
  需要后端明确持久化报告是否权威（或重算时刷新它）；② 回放中解析出一个未知名 `ai_judge`，
  **没查清其真实形态、没有猜着改**。
- **测试**：`npm run test:eval` 12 条（四种形态同值、回归锁"对象挡住数字"、冲突检测、
  元信息键不入列表、unparsable 不静默、人工/AI 口径互不回退）。

## D-86 M6 断流恢复：失败路径**先取回**，并且不许再说"没有生成内容"

- **用户实测**：三条默认问题都显示"本次回答被中断或超时，没有生成内容"。
- **服务端实测（排除法）**：完全按浏览器的方式 POST `/qa/stream`（body 带 `top_k/revision_id`、
  `Accept: text/event-stream`），事件序列 `meta → status → status → final`，4s 内必发 final；
  即**服务端无恙**，问题在客户端的失败处理。
- **修法（两层）**：
  1. `stream.state === 'failed'` 时**先**用 `meta.answer_id` 调
     `GET /papers/{id}/qa/answers/{answer_id}` 取回**已落库**的结果（服务端在发 final 之前
     就持久化了，连接断了不代表答案没了）；取不回再降级到非流式 `POST /qa`；最后才提示可重试。
     此前失败路径**直接**跳非流式，丢掉了"其实已经答完"的那种情况。
  2. 删掉禁用文案：`QAView` 里不再出现"没有生成内容"。改为
     「这次没能拿到完整结果，已保留你的问题，可以点「重试」再问一次。」
     / 有部分内容时「这次连接中断了（未收到完整结果），以上是已生成的部分；已为你保留。」
     ——全前端 grep 该文案 **0** 处残留。
- **测试/验证**：`tsc --noEmit` 通过；`npm run test:lib` 五套 + 路径门禁全绿；
  前端重建后 200。

**本轮（R3 Round 1）小结**：M8 → M1 → M6 三块已落地并各自实测。
下一轮按 R3 继续 **M4/M5**（问答策略放开 + 绝不空答不变量，后端）→ **M2/M9**（verdict 四分类、
评测口径分栏）→ **M3/M7/M10/M11/M12**。

## D-87 M4/M5 问答策略放开 + 绝不空答不变量

- **用户原话**："是不是应该直接完全放开，不要限制了更好。"
- **做了什么（后端 `qa/service.py`）**：
  1. **闲聊/问候规则前置**：`_is_chitchat()`（问候词表 + 短句且不含学术话题词）在**检索之前**
     判定 → 直接走通用回答，**不触发检索**（省一次云调用，也避免无关命中带偏）；
  2. **检索为空也放开**：新增 `_extract_object()`（**不依赖检索**从问句抽"具体对象"）。
     论文问题 + 检索为空 → 能抽到对象就 `not_mentioned`（点名"论文中没有提到 X"），
     抽不到就走通用回答；模型也不可用才落到如实说明 —— **任何分支都非空**；
  3. **`_ensure_readable` 升级为真不变量**：正文与句子皆空时按"能否抽出对象"选择兜底模板，
     并**记 warning 日志**（不变量被触发 = 上游有 bug，必须留痕）；
  4. 非论文问题且模型不可用时**不允许**掉进"论文中没有提到 X"（那句话会误导）——
     改为如实说明，并因此修掉一条既有回归（`test_abstention_never_grounded`）。
- **实测（paper 7，重建后端后按浏览器方式打 SSE）**：四条问题**全部**以 `final` 结束：
  - `这篇论文哪里最值得质疑？` → `abstained`，**正文非空**（解释 + 最接近的原文片段）
  - `主要贡献是什么？` → `generated`、grounded=True、带引用
  - `论文用了什么数据？` → `abstained`，**正文非空**
  - `你好，介绍一下你自己` → `general`
  即：**没有任何空答案，也没有任何"被中断"**。
- **一处如实说明（留给用户决策，我没有擅自改）**：第 1、3 条属于"论文相关、检索有命中但
  Evidence Gate 一条都没通过"，按 R3 §M4-3 的规格落到 `abstained` + 原因（**不降级为空白**）。
  若要把这类也改成"通用回答（标注未使用论文原文）"，等于**在没有论文证据时回答论文问题**——
  这是纪律取舍，需要用户点头；当前选择是"如实说明 + 给最接近的片段"。
- **测试**：新增 `test_qa_policy_open.py`（10 条：闲聊不触发检索 ×4、检索为空两档、
  通用回答标注、不变量补文案、不变量不误触发、兜底文案不含禁用字样）。
  后端全量 **821 passed / 0 failed**（较上一轮 +10）。

## D-88 M2 证据 verdict 四分类：别把"系统主动排除"说成"证据不足"

- **问题**：paper 7 实测 `verified 64 / unverified 6 / rejected 2 / contested 1`，
  界面上那 9 条非 verified **全被写成"未支持"**，语义被压平：
  - 6 条其实是**系统主动排除的非研究发现**（参考文献 `[15] …`、Google 许可声明）；
  - 1 条是**真矛盾**（原文 β₁=0.9、陈述写 0）；
  - 2 条是**有支持但未过其他检查**（`semantic=supports` 而 `decision=rejected`）。
  把它们都叫"证据不足"是误导 —— 用户会以为"系统没能证明"，实际是系统**拒绝**收录。
- **修法**：`frontend/lib/evidenceVerdict.ts` 作分类规则唯一真相（优先级：非研究发现 →
  矛盾 → supports+rejected → 其余回落 insufficient；未知组合**不抛错、reasons 一条不丢**；
  裸字符串 reasons 解析"码：文案"）+ `components/evidence/VerdictBadge.tsx`
  （四色标签 + 可展开看后端理由原文）。已接入 `PresenterView` 的断言选择面板
  （那里有 canonical statements 的 `validation`）。
- **测试**：`npm run test:verdict` 11 条（四类各一例、**反向断言 non_claim 不得显示"证据不足"**、
  未知组合回落且 reasons 不丢、落地验证不渲染徽标、空入参返回 null、理由逐字相等）。
- **如实说明**：分类库与徽标已完成并测试；**更深的接线**（ClaimView / GraphView 证据链、
  QAView 逐句）还需把 `validation` 载荷透传到那几个面板，属 M2 剩余部分。

## D-89 M9 评测口径分栏：AI 分不再顶替人工位

- **问题**：`EvalView` 用 `shownScore = 人工分 ?? AI 分` —— AI 分数**直接占在人工位上**，
  只加了一行小字说明。用户看到"综合评分 86"很容易读成"论文评分 86 分"。
- **修法**：两个口径**彻底分开**：主位只显示人工真值口径（未确认时显示"**未确认**"
  而不是 AI 数字），AI 口径单独成卡并明确标"**AI 评分（非人工真值）**"，
  文案写明"不等于人工真值分，也不与上面的综合评分互相顶替"。
- **测试/验证**：`tsc --noEmit` 通过；`npm run test:lib` 六套（rich 25 / graph 9 / media 6 /
  policy 7 / eval 12 / verdict 11）+ 展示路径门禁全绿；前端重建后 200。

## D-90 M7 流式审计：把"被中断"变成**可对账的数据**

- **动机（实测矛盾）**：用户报"三条默认问题都显示本次回答被中断"，但我用**完全相同**的
  POST 复现时服务端**每次都发 final**。问题在客户端侧 —— 可线上**一条对账数据都没有**：
  事件序列、终结事件有没有出去、客户端是否断开，全都查不到。
- **做了什么**：
  - 新表 `qa_stream_audits`（Alembic `0009`，纯 expand：只新增表与索引，字段全可空）：
    `id, paper_id, revision_id, answer_id, mode, events(JSONB，**只存事件类型名**),
    terminal, error_code, exception_type, elapsed_ms, created_at`；
  - `modules/qa/audit.py`：`record()`（**内部 try/except，写失败只记日志**，审计绝不改变流行为）、
    `list_audits()`（倒序、limit ≤ 200）、`AuditTimer`；
  - 挂在 `stream.py`：`_AuditedEncoder` 覆盖 `encode()` —— 它是事件的**唯一出口**，
    挂这里不会漏事件；审计写入放在 `try/finally` 的 `finally` 里，且**把 `meta` 事件也移进 try**
    （这样"客户端只收到 meta 就断开"也能留下 `terminal='none'` 的一行）；
  - 新端点 `GET /papers/{id}/qa/stream-audit?limit=`。
- **实测（重建后端 + 跑迁移后）**：
  打一次真实 SSE → 事件序列 `meta, status, status, citation, sentence, final`；
  查审计 → **1 行**：`terminal=final, mode=generated, elapsed_ms=5750,
  events=[meta,status,status,citation,sentence,final]`。
- **测试**：`test_qa_stream_audit.py` 6 条 —— 成功一次写一行且 `events` 首尾正确、
  `events` 只含类型名（不含正文）、异常路径记 `exception_type`、DomainError 记 `error_code`、
  **客户端断开记 `terminal='none'`**、`audit.record` 自己吞掉写库异常。
  后端全量 **827 passed / 0 failed**（较上轮 +6）。

## D-91 M11 验收套件入库：验收不再依赖「我这台机器上恰好有那几个脚本」

- **动机**：五套端到端验收脚本一直躺在 `.scratch/`（**被 gitignore**）。也就是说
  干净克隆根本跑不了验收 —— 每一轮"验收通过"都建立在一个无法复现的前提上。
- **做了什么**：迁移进 `scripts/acceptance/`（`verify_route_a / verify_graph /
  verify_e2e_extra / verify_metrics_live / verify_qa_stability`）+ 新增 `run_all.py`
  与 `README.md`：
  - `run_all.py` 一条命令跑全：**前置健康检查**（后端/前端不可达 → 打印
    `backend unreachable at {url}`、退出码 **2**，**绝不**把后续检查标成"跳过=通过"）、
    逐脚本串行执行、每套输出一行 JSON（`{script,status,failures,elapsed_ms,tail}`）、
    汇总写 `results.json`；退出码 0/1/2；
  - 脚本可独立跑（`python scripts/acceptance/verify_graph.py <base> [frontend]`）；
  - `.scratch/` 里这 5 个原文件已删除（其余一次性诊断脚本按方案要求不动）。
- **实测**：`python scripts/acceptance/run_all.py` → 5/5 pass；
  指向错误端口 → `backend unreachable at http://127.0.0.1:9`、**退出码 2**（假 pass 被堵死）。
- **迁移中踩到并修掉的两个真问题（值得记）**：
  1. **子进程输出编码**：Windows 上子脚本写 GBK、CI 上写 UTF-8；只按一种解码会让中文
     全变替换字符，连"失败断言：N"都正则不出来（`failures` 恒为 `null`），
     而且把 `U+FFFD` 打到 GBK 控制台还会直接抛 `UnicodeEncodeError` 把 runner 打挂。
     现在按 `utf-8 → gbk → mbcs` 依次尝试解码，并把 stdout/stderr 重配为 UTF-8。
  2. **失败计数行的真实文案是「总计失败断言：N」/「总失败断言：N」**，不是我最初以为的
     "失败数：N" —— 正则写错时 `failures` 会**静默为 null**（状态仍靠退出码判定，
     所以不会造成假绿，但机读字段是空的）。已按实测文案修正。
- **一处如实记录的偏离**：方案 §M11-2 要求"**每脚本**输出统一 JSON 行"；当前由
  `run_all` 统一汇总输出（各脚本保持原有人读输出与退出码）。理由：逐脚本改尾部输出结构
  收益低、改坏已验证脚本的风险不成比例；如需再补，只需在各脚本尾部加一行 `print(json.dumps(...))`。
  已写进 `scripts/acceptance/README.md`。

## D-92 M3 卫生门禁扩面：把"漏面"变成结构性可防

- **为什么要扩**：R3 用户问题的根因就是**漏面** —— 渲染内核统一了，但证据卡/证据抽屉/
  讲解引文这些地方仍是裸插值（M1 一次查出 **8 处**）。而当时的卫生门禁只扫
  **章节/表格/媒体题注**，**恰好扫不到出问题的那几类文本**。门禁覆盖面错了，
  比没有门禁更危险（会让人以为已经防住了）。
- **后端扩面**：新增 `test_hygiene_expanded.py`（**51 条**）—— 语料换成**实测文本**：
  证据引文切片（含 `$$…\tag{3}$$`、`$P _ { d r o p } = 0 . 1$`、`<sup>∗</sup>` 作者行）、
  **问答落库回答**（含拒答模板 + 最接近片段里的 LaTeX）、**评测 reason 文案**
  （含"模型语义判定：…β₁ = 0.9…"）；四类不变量逐条断言
  （无落单 `$`、无 `$$` 残留、`rich` 叶子无定界符、issue code 在枚举内、二次规范化稳定），
  并有**门禁必须能红**的三条自验证（这三类文本里塞未归类脏模式必须被报出）。
- **前端门禁扩面**（`scripts/check-text-paths.cjs`）：自验证从 2 条扩到 **4 条** ——
  ① 坏样本必被检出；② 合规写法不误报；③ **注入检测**：已登记文件里插一条裸插值必须变红；
  ④ **清单漂移**：清单登记了不存在的组件必须变红（防止清单腐化成"看起来在管、其实没管"）。
- **实测**：后端全量 **878 passed / 0 failed**（较上轮 +51）；前端六套 + 门禁（8 个展示点）全绿。

## D-93 M10 第一步：先建安全网，**当场抓到一处真实分叉**并收敛图谱域

- **做法（按方案 §M10 测试要点 1/2 先做前两件）**：
  1. 新增 `test_projection_dual_read.py`：**跨域双读一致性**（qa / graph / evaluation 各一例，
     同一 canonical 对象经 `schemas/adapters` 与 `modules/*/legacy` 两处投影必须逐字段相等）
     + **静态门禁**（`def to_legacy_` 只允许出现在白名单里；新增副本立刻变红；
     白名单里"已经没有投影"的条目也会变红，逼着清单随合并收敛）。
- **安全网第一次运行就抓到真分叉（这就是它存在的意义）**：
  `adapters.to_legacy_graph` 是**白名单式投影**（props 只列
  `status/claim_id/evidence_id/media_id/anchor_ids`），而
  `modules/graph/legacy.to_legacy_graph` 已经补上节点 `props` 透传（ADR-0058/D-48）。
  后果：**同一份 canonical 图谱，两条路径给出的结果不同** —— 图谱端点带
  `support_status`（证据节点的判定），走 adapters 的路径没有。这正是 D-48/D-60
  那类"改了一处、另一处没改"的事故结构，只是这次由测试而不是用户发现。
- **收敛**：`adapters.to_legacy_graph` 改为**委托** `modules.graph.legacy.to_legacy_graph`
  （函数内延迟导入避免循环依赖），只做 `GraphOut` 包装；`statements` 参数两侧都没用，
  保留签名仅为兼容。收敛后双读测试转绿。
- **实测**：双读一致性 5 条全绿；后端全量 **883 passed / 0 failed**；
  重建后端后验收 `verify_graph / verify_route_a / verify_metrics_live` **全绿**。
- **剩余（M10 未完）**：`scene`（`to_legacy_presentation` 两侧**签名就不一样**：
  adapters 版本多收 media/evidence/statements —— 合并前要先定哪份权威）、
  `qa`、`evaluation` 三域的合并；以及把实现真正迁到 `app/projection/` 并收白名单。
  本轮只完成了"安全网 + 一个域"，**不声称 M10 完成**。

## D-94 M12 现状核实（**先查再动手**）：后端阶段进度其实已经可用

- **做法**：按"先看现有实现再决定做什么"，直接查库里最近一次导入 job 的事件流
  （`select ... from job_events where job_id=(select max(id) from jobs)`）。
- **实测结果（job 7）**：事件流**已经是完整的 11 阶段时间线**，且 progress 单调不减：
  ```
  stage_started acquire 0.00 → stage_finished acquire 0.05
  → parse 0.05/0.25 → normalize 0.25/0.30 → media 0.30/0.45 → index 0.45/0.55
  → claims 0.55/0.70（含 degraded）→ verify 0.70/0.80 → exhibits 0.80/0.90（含 degraded）
  → qa_bank → evaluate → publish → completed
  ```
  基础设施也已在位：`job_events` 表、`job_stage_keys`（唯一键
  `revision_id+stage+input_digest+algorithm_version` + status）、`stage_finished/skipped`
  复用（`service.py` 里"直接复用产物 digest 返回 skipped"）。
- **结论**：M12 的**后端一半已经工作**（进度事件 + 幂等键表 + skipped 复用），
  不是"没做"。剩下的缺口按实测是：
  1. **`stage_started` 会重复发**（实测 job 7：`acquire` 发了 2 次、`claims` 发了 2 次）——
     根因是**两处语义不同的 emit 共用了同一个事件类型**：`create_job` 入队时发
     `stage_started acquire`（"任务已入队"），`claim_next` 领取时又发
     `stage_started <stage>`（"worker 已领取"）。界面上时间线会显示两次"开始"，像 bug；
  2. `POST /papers/{id}/process { from_stage }` 的**显式起点**未见实现（默认从第一个未完成阶段起；
     需要核实 canonical ingest 路径的入口参数）；
  3. **前端导入页的阶段时间线**（消费既有 `useJobEvents` 渲染 skipped/running 百分比）未做。
- **本轮为什么只核实不改造**：上面第 1 条要改的是**事件类型语义**，而事件流正被导入页消费；
  在上下文预算即将耗尽时改动它，改完无法完成"重建 + 真实导入一次 + 看界面"的验证闭环 ——
  按本项目一贯纪律（**不交付未经验证的改动**），本轮留作下一轮的第一件事，并已把根因写清楚。

## D-95 M12 前端：阶段时间线补上"当前阶段 / 已跳过 / 原因"

- **再查一次现状**（延续 D-94 的"先查再动"）：导入进度**不是没做** ——
  `components/jobs/JobProgress.tsx` 早已是从 `JobEvent[]` 推导的有序阶段列表（11 阶段 +
  进度条 + 当前阶段转圈 + 已完成打勾），并且 `app/paper/[slug]/page.tsx` 已经
  `useJobEvents` + `<JobProgress>` 接上了。若照方案从零实现，同样是重做已有能力。
- **本轮补的三处**（方案 §M12-5 明确要求、原实现缺）：
  1. 顶部进度数字旁**标出当前阶段名**（原来只有百分比，看不出"卡在哪一步"）；
  2. **`已跳过` 徽标**：后端把"复用既有产物、不重复执行"表达为 skipped（AI 类阶段跳过
     = 不重复计费），界面此前把它显示成"已完成" —— 现在按阶段最终事件的文案识别并显式标注；
  3. 每行 `title` 显示该阶段最终事件的**原因文案**（悬停可查"为什么跳过/降级"）。
- **实测**：`tsc --noEmit` 通过；`npm run test:lib` 六套全绿；前端重建后 200。
- **M12 仍然剩余（如实登记）**：`stage_started` 重复发（根因见 D-94：入队 emit 与领取 emit
  共用同一事件类型）、`POST /papers/{id}/process { from_stage }` 显式起点。

## D-96 M2 深接线：四分类徽标接到证据链列表（断言视图）

- **背景**：D-88 做完了四分类的**库与徽标**并接进 `PresenterView`，但用户最常看的是
  **断言列表（证据链）** —— 那里仍然只显示"未支持"，看不到"为什么"。
- **数据通路（一段都不少）**：
  `exhibits.statements[].validation`
  → `validationsByStatement`（statement_id → validation 映射）
  → `claimSummaryOf(c, statementsById, validationsByStatement)` 产出
  `ClaimSummary.validation`
  → `<ClaimView>` 里 `<VerdictBadge validation={c.validation} />`。
- **改了哪些文件**：`lib/types.ts`（`ClaimSummary` 加可选 `validation`）、
  `app/paper/[slug]/page.tsx`（映射 + 透传）、`components/views/ClaimView.tsx`（渲染徽标）。
- **实测**：`tsc --noEmit` 通过；`npm run test:lib` 六套全绿；前端重建后
  验收 `verify_route_a`（含 exhibits/claims 字段）与 `verify_e2e_extra`（含 bundle 关键路径）
  **均 0 失败**。
- **一处如实说明**：图谱视图（`GraphView` 证据节点）目前只有 `support_status`
  （supports/insufficient），**没有** `reasons`，所以那里仍用原有的文字标注 ——
  要把四分类徽标也接上去，需要后端在图谱节点 props 里带上 reasons（属后续小改动）。

## D-97 M12 收尾①：抑制**连续重复**的 `stage_started`

- **问题（实测 job 7）**：`stage_started acquire` 与 `stage_started claims` 各出现两次。
  根因是**两处语义不同的 emit 共用同一事件类型**：`create_job` 入队时发一次
  （"任务已入队"），`claim_next` / 上一阶段完成推进时又发一次（"worker 已领取"/"开始 X"）。
  界面上时间线会显示两次"开始"，看起来像 bug。
- **修法（不改事件词汇表，避免动到前端与既有存储格式）**：`pipeline/service._emit()` 加
  **幂等抑制** —— 若该 job 的**上一条事件**已经是同一 stage 的 `stage_started`，则跳过本次写入
  （新增 `repository.last_event()` 助手）。规则只压"连续重复"，
  **不会误伤**"阶段跑完再重跑"这种合法序列（那时上一条是 `stage_finished`）。
- **测试**：`test_pipeline_stage_events.py`（4 条）—— 连续重复被抑制（acquire 两次只留一条）、
  **跑完再重跑的新 started 必须保留**、不同 stage 的 started 都保留、progress 单调不减。
- **实测**：后端全量 **887 passed / 0 failed**（+4）；重建后端后
  `verify_route_a / verify_graph / verify_metrics_live` **0 失败**。
- **如实说明（未做的验证）**：本次**没有**再跑一次完整导入（约 4 分钟 LLM 时间）来现场看
  新 job 的事件序列 —— 重复抑制由 4 条单元测试覆盖，但"真实导入一次、确认新 job 里
  acquire/claims 只出现一次"这一步留待下次真实导入时顺带确认。

## D-98 M12 收尾②：断点续跑**决策层** + `GET /papers/{id}/resume-plan`

- **先查再动的结论**：管线**已经有**阶段幂等键（`job_stage_keys`）与"产物 digest 命中就
  `skipped`"（D-94 已核实），**唯独没有任何入口**能问"这篇论文续跑该从哪起" ——
  这正是方案 §M12-4 的缺口。
- **做了什么**：
  - `modules/pipeline/resume.py`：`plan_resume(succeeded, from_stage)` 是**纯函数**
    （无 DB、无副作用），`resolve_start_stage(scope, from_stage)` 只是薄薄一层 DB 读取；
  - `GET /papers/{id}/resume-plan?from_stage=`：返回 `start_stage / skipped / reason / stages`。
  - 规则：不传 → 从**第一个未成功**的阶段起（默认安全）；传 → 从指定阶段起（之前的跳过）；
    **非法 `from_stage` 视同没传**并把"已忽略"写进 reason（不猜、不报错）；全部完成 →
    `start_stage=null` + 原因。
- **实测（真实 paper 7，重建后端后）**：
  ```
  默认                  → start=claims     skipped=5  从第一个未完成阶段 claims 开始
  ?from_stage=evaluate  → start=evaluate   skipped=6  按指定起点从 evaluate 开始（之前的阶段跳过）
  ?from_stage=bogus     → start=claims     skipped=5  未知起点 'bogus' 已忽略；从…claims 开始
  ```
  前两条正是"**不重复烧 AI 阶段**"的证据：paper 7 的 claims 已完成，默认续跑不会再跑它。
- **测试**：`test_pipeline_resume.py` 9 条（空历史→acquire、worker 在 index 后崩→从 claims 起、
  中间有缺口→从缺口起、全部完成→null、脏阶段名被忽略、显式起点优先、
  显式起点时未成功的前置阶段不计入 skipped、非法起点回落、起点就是首阶段）。
  后端全量 **896 passed / 0 failed**（+9）。
- **如实说明（仍未做）**：这个端点只回答"**该**从哪起"，**还没有**把它接进
  `POST /process` 的入参（即"按计划真的从该阶段起跑"仍需在 ingest 入口接 `from_stage`）。
  本轮交付的是决策层 + 可查询入口，**不声称端到端续跑已完成**。

## D-99 M12 收尾③：`from_stage` 真正接进起跑入口（并修掉两个连带缺陷）

- **做了什么**：`POST /api/papers/{id}/resume {from_stage?}` —— 决策（D-98 的 `plan_resume`）
  → `service.enqueue(..., start_stage=…)` → `repository.insert_job(..., start_stage=…)`
  写进 `job.stage`（那就是 runner 的"当前阶段"），因此**起点之前的阶段天然不执行**。
  全部阶段已完成 → 返回 `status="noop"` 且**不建 job**（不产生空任务）。
- **实测（真实 paper 7，重建后端后）**：
  ```
  POST /resume {from_stage:"evaluate"} →
    {"status":"queued","job_id":9,"start_stage":"evaluate",
     "skipped":["acquire","parse","normalize","media","index","qa_bank"], ...}
  POST /resume {from_stage:"publish"} →
    {"status":"queued","job_id":10,"start_stage":"publish","skipped":[7 项], ...}
    job 10 的首个事件 = stage_started publish  ✅
  ```
- **过程中发现并修掉的三个真缺陷**（都是"照方案写会踩、实测才发现"）：
  1. **路由被 legacy 抢占**：方案写的路径是 `POST /papers/{id}/process`，但该路径**已被
     legacy 路由占用**（先注册者胜）—— curl 实测返回的是 legacy 的
     `{paper_id, job_id, status:"running"}`，新端点**永远不可达**。硬改优先级会破坏 legacy
     兼容契约，因此改用不冲突的 `/papers/{id}/resume`（`/process` 行为保持不变）。
  2. **`ProcessBody` 定义在端点之后**，且用了字符串注解 + `=None` → FastAPI 没能正确建路由
     （路由当时根本没注册）。已前移并把注解改成真实类型。
  3. **入队事件硬编码 `stage="acquire"`**：续跑时 job 的 stage 明明是 `evaluate`，
     界面却先报"acquire 开始"（实测 job 9 的首个事件就是错的）。已改为使用 job 的真实起点。
- **测试**：`test_pipeline_resume.py` 增至 11 条（新增 `enqueue(start_stage=…)` 必须写进
  `job.stage`、默认仍是 `acquire`）。后端全量 **898 passed / 0 failed**。
- **M12 至此闭环**（进度事件 + 去重 + 时间线 + 续跑决策 + 真正起跑），
  **唯一与方案文本的差异是路径名**：`/resume` 而非 `/process`（原因见上，已写进端点 docstring）。

## D-100 M10 收敛②：评测域投影合并（`qa` 域核实为**早已收敛**）

- **先核实再动手的结果**：
  - **`qa` 域本来就已经收敛**：`modules/qa/legacy.to_legacy_answer` 早在 ADR-0060 就改成了
    委托 `schemas/adapters.to_legacy_answer`，注释里写着"只保留一处实现"。**无需再动**。
  - **`evaluation` 域是真重复**：拿同一份 `EvaluationReport` 跑两处投影做**字段级比对**，
    结论是**键集合与取值完全一致**（既没有超集也没有差异）—— 也就是一份纯副本。
- **收敛**：`modules/evaluation/legacy.to_legacy_evaluation` 改为委托
  `schemas/adapters.to_legacy_evaluation`，自己只把 Pydantic 结果摊平成旧调用方要的 dict。
  两份并存只会重演 D-48/D-60 那类"改了一处、另一处没改"，而这次是**实测确认无差异**后才合的。
- **顺手把双读测试加强**：原来评测域只比 `not_evaluated / not_evaluated_reasons / proxy`
  三项 + 两个指标名 —— 这**漏得掉**"一边多/少一个顶层字段"这类分叉。现在改成
  **顶层键集合相等 + metrics 键集合相等 + 逐字段相等**。
- **实测**：双读一致性 5 条全绿（含加强后的评测域）；后端全量 **898 passed / 0 failed**；
  重建后端后 `verify_metrics_live / verify_route_a / verify_graph` **0 失败**。
- **M10 只剩 `scene`**：两侧**签名不同**（`adapters` 多收 `media/evidence/statements`），
  合并前必须先定哪份权威 —— 这一条**我需要用户拍板**，不自行决定（涉及产品语义，不是机械迁移）。

## D-101 M10 收敛③：`scene` 域（**我推翻了自己上一轮的默认方向**，理由是实测）

- **实测改变了判断**：`schemas/adapters.to_legacy_presentation` **没有任何调用方** ——
  全仓库只出现在它自己的 docstring 与 `__all__` 里；真正服务
  `GET /papers/{id}/presentation` 的是 `modules/scene/legacy` 那份，而且它被端到端验收覆盖。
- **因此收敛方向反过来**：上一轮我说"默认保留信息更多的 adapters 版"，但把**线上路径**
  换成一份"没人用过、也没被验收覆盖"的实现，风险高于收益。改为
  **module 为唯一实现**，`adapters.to_legacy_presentation` 委托它（`media` 列表转成
  `media_by_id` 映射），并**保留 `evidence` / `statements` 入参签名**以免破坏潜在调用方 ——
  若确实需要更丰富的引用，应当**在唯一实现里显式加**，而不是靠保留第二份副本来实现。
- **实测**：委托调用可跑通；后端全量 **898 passed / 0 failed**；重建后端后
  `verify_e2e_extra`（含 presentation/分镜路径）与 `verify_route_a` **0 失败**。
- **M10 四个域的收敛状态**：
  | 域 | 唯一实现位置 | 另一侧 |
  |---|---|---|
  | graph | `modules/graph/legacy` | adapters 委托（D-93） |
  | evaluation | `schemas/adapters` | modules 委托（D-100） |
  | qa | `schemas/adapters` | modules 早已委托（ADR-0060，D-100 核实） |
  | scene | `modules/scene/legacy` | adapters 委托（本轮） |
  即**每个域只剩一份真实实现**，另外一份是薄委托；配上双读一致性测试与静态门禁，
  "改了一处、另一处没改"这条事故路径已经堵住。
- **M10 仍未做（如实登记，不声称完成）**：方案 §M10-1/4 要求的**物理迁移**
  （把实现搬进 `app/projection/`、`adapters` 改 re-export、白名单收窄到只剩 `projection`）
  与 `projection/CONTRACT.md` 字段清单**尚未做**。当前是"逻辑上唯一实现 + 测试防漂移"，
  不是"包结构上的唯一入口"。这一步是纯机械迁移，风险低但要动 9 个函数与多处导入，
  我选择在上下文预算充足时单独做一轮，而不是赶在末尾半途而废。

## D-102 M10 契约清单 + **薄委托门禁**（"唯一实现"从此有守卫）

- **新增 `app/projection/CONTRACT.md`**：写清每个域**哪一份是真实实现**、另一份是薄委托、
  收敛记录（D-93/D-100/D-101），以及**为什么权威侧不在同一个包里**（按"线上在用且被验收
  覆盖"来定，而不是按包的位置 —— scene 的权威侧在 `modules/scene/legacy`，
  因为 `schemas/adapters` 那份根本没有调用方）。并如实登记"物理迁移未做"。
- **新增 `test_projection_thin_delegation.py`**（2 条）：把"薄委托"变成可执行不变量 ——
  对已知的非权威侧，断言其函数体 ① 足够短（≤45 行）、② 确实出现转发调用。
  这样"下次有人为了顺手加字段又把逻辑写回副本"会立刻变红（D-48/D-60 的事故路径）。
- **门禁第一次运行就抓到我自己写错的清单**：我把 `modules/graph/legacy.to_legacy_graph`
  与 `schemas/adapters.to_legacy_evaluation` 当成了委托方，实际它们是**权威实现** ——
  测试当场报"这两个没有转发调用（可能已成空壳）"。修正清单后转绿。
  （这正是"门禁必须能红"的价值：连作者的理解错误都能被它挡下。）
- **实测**：后端全量 **900 passed / 0 failed**；`git` 工作树干净。
- **M10 仍未做（未变）**：把实现物理迁移到 `app/projection/` 包、`adapters` 改 re-export、
  白名单收窄到只剩该包。

## D-103 R3 收口验收记录（M1–M12）

**在最终 commit 上实测（全部四容器在跑）**

| 层 | 命令 | 结果 |
|---|---|---|
| 后端单测 | `python -m pytest backend/app/tests -q` | **900 passed / 0 failed** |
| 前端零依赖单测 | `npm run test:lib` | **70 项全绿**（rich 25 / graph 9 / media 6 / policy 7 / eval 12 / verdict 11） |
| 前端展示路径门禁 | `node scripts/check-text-paths.cjs`（含 4 条自验证） | 8 个展示点全绿 |
| 前端真实语料门禁 | `npm run test:hygiene` | paper 7/10：多余 `$` 0、被转义标签 0、残留 `\tag` 0 |
| 端到端验收 | `python scripts/acceptance/run_all.py` | **5/5 pass**（route_a / graph / e2e_extra / metrics_live / qa_stability，空答案 0/9） |

**本轮（R3）交付物与对应问题**

| 用户问题 | 交付 | 验证 |
|---|---|---|
| ① 证据文本仍显示 `$…$` 源码 | M1 渲染扩面（**8 处**裸插值）+ 穷举展示路径门禁 | 门禁首跑查出 8 处；真实语料 0 残留 |
| ② 证据显示"未支持"说不清为什么 | M2 四分类（非研究发现/真矛盾/有支持未过其他检查/证据不足）+ 徽标接到**证据链列表** | 11 条测试含反向断言 |
| ③ 原件媒体"不可用" | M4 前端策略 + caption 公式兜底（D-80） | 实测 0 条不可用、前后端分叉 0 |
| ④ 问答"被中断/没有生成内容" | M6 断流恢复（answer_id 取回 → 非流式兜底）+ 文案红线 + M7 流式审计 | 实测四条问题全部 `final` 且非空；审计可查 |
| ⑤ 图片方向反了 | M4 查看器旋转/缩放/复位 | 6 条测试 |
| ⑥ 图谱堆叠/关系名看不见 | M8 分层布局（不重叠 + 边标签避让） | 9 条测试（含 100 节点） |
| "要完全放开" | M4/M5 问答放开 + 绝不空答不变量 | 10 条测试；闲聊不触发检索 |
| "自动评测全显示未评测" | M8 指标解析（修对象当数字）+ M9 口径分栏 | 真实响应回放 0.3571/1/1/5213… 全部显示 |
| （结构）投影重复实现 | M10 四域收敛 + 三套门禁 + CONTRACT.md | 双读一致性 5 条 |
| （新增）导入看不到进度 | M12 进度事件去重 + 时间线 + 断点续跑入口 | 实测 job 首个事件即指定阶段 |

**如实登记的未完成项（不在本目标内或需你裁决）**
1. **M10 物理迁移**：实现仍在各自模块/`adapters`，未搬进 `app/projection/` 包；
   防漂移由三层门禁覆盖（详见 `app/projection/CONTRACT.md`）。
2. **图谱节点 props 未带 `reasons`**：图谱证据节点仍用文字标注，未接四分类徽标。
3. **完整导入的现场复验**：`stage_started` 去重由 4 条单测覆盖，尚未在真实导入中现场确认。
4. **`anchor_region_hit_rate` 永远不可测**（原文无坐标矩形，拒绝编造 IoU）—— 设计选择。
5. **金标集仍是 AI 起草的 proxy**：`overall_score` 需人工确认后才有值。

---

## D-104 产品决策：**拒答退出产品语义**，可靠程度由置信度表达（R4-M3）

- **谁要求的**：用户原话——"拒答直接彻底消失，反正有置信度说明。"（并明确"可以附"最接近的原文片段）
- **推翻了什么**：
  - **D-65** 的"对象缺失 → 直接拒答"**用法**（判据本身保留为 `not_mentioned` 的确定性证据）；
  - `AnswerMode` 里的 `abstained` 取值（**从契约删除**，不再可能被新代码产出）；
  - 拒答类指标：`answerable_false_refusal_rate` **删除**；`unanswerable_refusal_rate` 更名
    `unanswerable_honesty_rate`（口径 = 不可答题如实说明率）。详见 D-106。
  - `docs/ARCHITECTURE.md` 的「无证据支持 → "模型未在论文中找到直接依据"（禁止编造）」改写。
- **为什么**：实测 paper 11 上三个默认问题里「这篇论文哪里最值得质疑？」走的是
  `mode=abstained / confidence=Low`（`qa/service.py` 阶段 3 的 `not grounded and not sentences` 分支），
  用户看到的是"被拒答/被中断"，而不是"一个低置信度的回答"。拒答把"我们没有把握"表达成了
  "我们不回答"，对用户没有信息量。
- **新的四处（原拒答路径）**：
  1. 模型不可用（闲聊/非论文问题兜底）→ `unavailable`（如实说明 + 已知信息，可重试）；
  2. 检索为空：能点名对象 → `not_mentioned`；抽不出对象 → `general`；
  3. **对象确实不在原文**（`_object_absent_from_hits`，确定性判据保留）→ `not_mentioned`
     **并附逐字原文片段**（决策 2）；
  4. 模型草稿全被 gate 拒 → **抽取式兜底** `extractive`（逐字原文）；连片段都没有 → `general`/`unavailable`。
- **保留的纪律（没有被一起推翻）**：
  1. `grounded` 语义**一字不改**（仍 = 逐句通过 Evidence Gate）——放宽它会让
     `unsupported_fact_escape_rate` 失守；
  2. 引文/片段必须**逐字**来自原文块，且片段**不是 evidence**（不进引用列表、不参与 grounded）；
  3. `not_evaluated` 不许写成 `0`。
- **代价**：不可答题更可能被"答"出来（抽取式兜底）。缓解 = `_object_absent_from_hits` 这条
  确定性判据仍前置拦截（"问 Kubernetes 却拿 8 块 GPU 顶"这类答非所问进不来），
  且诚实率指标（D-106）会把它量化出来。
- **实测**：后端 `pytest` **917 passed / 0 failed**（基线 900 + 新增 18，无丢失）。

---

## D-106 拒答类指标重定义（R4-M3 配套）

- **`answerable_false_refusal_rate` 删除**：它测的是"可答题被误拒"，而决策 1 之后**拒答动作不存在**，
  留着它就是一个恒为 0 的绿条 —— 那是假指标（违反"不编造、不凑数"）。
- **`unanswerable_refusal_rate` → `unanswerable_honesty_rate`**：口径改为"对 golden 不可答的问题，
  系统有没有**如实说明没有依据**"。命中的形态：`not_mentioned` / `general` /
  （`extractive` 且未 grounded）/ `unavailable`；对不可答题给出 `grounded=True` 的生成作答 = **不命中**。
- **完整同步清单**（漏一处就留下一个永远显示"未评测"的空格子，已逐项完成）：
  | 位置 | 改动 |
  |---|---|
  | `backend/app/contracts/evaluation.py::METRIC_NAMES` | 删旧 + 加新 |
  | `backend/app/modules/evaluation/metrics.py` | `OVERALL_WEIGHTS` 键名、`_is_refusal`→`_is_honest_unanswerable`、`refusal_metrics`→`honesty_metrics`、`__all__` |
  | `backend/app/modules/evaluation/service.py::_compute_entries` | 只写 `unanswerable_honesty_rate` |
  | 后端测试 | `test_evaluation.py` / `test_eval_metric_reporting.py` / `test_eval_answer_freshness.py` / `test_ai_judge_evaluation.py` 按新语义改写（**改写而非删除**，每条注明原语义为何失效） |
  | `frontend/components/views/EvalView.tsx`、`frontend/lib/evalMetrics.ts` | **待 R4-M5 落地时同步**（见该模块） |
  | `scripts/acceptance/verify_metrics_live.py` | **待 R4-M10 同步** |
- **历史报告怎么办**：不迁移。旧报告是时间点快照，改它等于改历史；读取端对旧名做别名映射
  （R4 规划 Q3），新报告只产新名。
- **历史 `mode='abstained'` 行怎么办**：**DB 不动**，在读取投影处（`service._row_to_answer` →
  `_legacy_mode`）映射：带"对象缺席"note → `not_mentioned`，否则 → `unavailable`。
  实测真实历史形态：旧代码里 `mode='abstained'` **只**由"没找到证据"产出（对象缺席那条路产的
  是 `not_mentioned`），所以绝大多数历史行落 `unavailable`。

---

## D-105 产品决策：**取消人工真值维度，自动评测全面 AI 化**（R4-M5，推翻 D-50/D-65）

- **谁要求的**：用户原话——"我建议就是直接取消一切跟人工有关的，那个自动评测直接全部 ai 评 ai 打分。"
  + "综合评分，各项指标什么率的全部 ai 直接完成，取消人工操作并且把综合评分右边的
  （人工真值口径）字段删掉。" + 拍板"人工有关的全部删掉""那就改成『AI 质量评分（自动）』"。
- **推翻了什么**：
  - **D-50**「机器构造的集合不得当人工真值；`support_precision/recall` 必须有标注集才叫 measured」；
  - 人工确认链路：`POST /papers/{id}/golden-set/confirm` 端点、`golden_builder.confirm_for_scope`、
    `EvaluationInput.golden_is_tuning` 字段、`build_and_save(annotated=)` 参数、
    `golden.py` 的 `is_tuning` 优先级（ORM 列保留，不再承载语义）；
  - 人工口径函数 `metrics.compute_overall` / `core_metric_missing`（**删除**，不是保留不用）；
  - 人工语义告警码 `golden_not_annotated` / `overall_not_evaluated`。
- **为什么（真实约束）**：人工确认在真实使用中**永远不会发生**（单人参赛、没有标注人力），
  于是主分恒为 `null`、界面永远显示"未确认"，用户永远看不到分数 —— 一条永不触发的纪律
  等于把产品功能关掉。
- **新语义**：
  - `overall_score` = **主分「AI 质量评分（自动）」**，用 `compute_ai_overall` 算
    （公式不变：0.4·support_precision + 0.2·quote_exact_rate + 0.2·anchor_page_accuracy
    + 0.2·unanswerable_honesty_rate），允许 `support_precision` 以 **proxy**（AI 裁判语义判等）参与；
  - 新增 **`overall_score_basis`** 字段（契约值 `"ai_generated"`），前端主卡下方固定一行小字
    "由 AI 裁判与程序测量自动得出，非人工评审"；
  - 金标集只剩一种形态（AI/确定性构造），`GET golden-set` 的 `status` 改为
    `ai_constructed（AI 从原文构造，非人工评审）`，`is_tuning` 字段从响应删除。
- **保留的纪律（D-50 里真正不能丢的部分）**：
  1. **proxy 就是 proxy**，不许声称 measured（AI 裁判给的支持度永远是 `proxy`）；
  2. AI 裁判没出结论 → `not_evaluated` + 原因码（`no_ai_judge`），**绝不用 0 冒充**；
  3. 核心指标缺失 → `overall_score=null` + 告警 `ai_overall_not_evaluated`（缺哪项列哪项）；
  4. **来源可追溯**：`overall_score_basis` + 主卡小字 + "金标集：AI 构造"徽标三处显式传达。
- **代价**：分数失去人工校验背书。缓解 = 上述第 4 条的三处标注，**不遮不掩**。
- **实测**：后端 `pytest` **935 passed / 0 failed**（M3 的 917 + 新增 12 + 改写若干）；
  前端 `test:lib` **96 项**全绿。
- **兼容**：`ai_overall_score` 字段保留一个版本周期（与主分同值，deprecated），
  前端 `parseOverall` 仍能读旧报告；`is_tuning` DB 列保留（删列需要迁移，且已无行为影响）。

---

## D-107 `anchor_region_hit_rate` 口径更正：**不是"原文没有坐标"，而是"缺少独立区域真值"**（R4-M6）

### 实测覆盖率（真实库，2026-09-13，逐篇 SQL 跑出）

| paper | blocks | with_bbox | bbox_units |
|---|---|---|---|
| 1 | 156 | **156** | normalized |
| 2 | 267 | **267** | normalized |
| 3 | 400 | **400** | normalized |
| 7 | 180 | **180** | normalized |
| 9 | 122 | **122** | normalized |
| 10 | 122 | **122** | normalized |
| 11 | 258 | **258** | normalized |

锚点 `segments[0].rect` 非空率：**0/258、0/100、0/144、0/15、0/9、0/9、0/16**。

### 断言被推翻的部分

- **旧结论**（D-52 遗留、R3 计划、UI 文案）："原文 PDF 没有坐标矩形，拒绝编造 IoU（设计上不可测）"。
  **前半个断言是假的** —— 块 bbox 覆盖率 100%。
- **真实原因有两条，条目各自成立**：
  1. **生产链缺一环**：`CandidateEvidence` 的两个构造点（引用定位、`page_only_candidate`）
     都硬写 `rect=None` → 锚点永远 page-only → 阅读器**永远画不出区域**（D13 的"不谎称已高亮"
     因此从来没有机会变成"真的高亮了"）。R4-M6 已补上这一环。
  2. **更关键的一条：即使补上，也没有独立真值**。证据锚点的矩形就是**引用块的 bbox**
     （`gate.block_rect` → `candidate_to_segment`），而"期望区域"同样是引用块的 bbox。
     两者**同源** → IoU 恒为 1.0 → 一个自证的满分，**比"未评测"更糟**（那是编造数字）。

### 本轮改了什么

1. **新增 rect 生产链**：`gate.block_rect(block)` 从 `raw_ref` 取 bbox 并**换算到契约空间**，
   候选与锚点带真实矩形 → 阅读器**首次具备画出区域高亮的能力**。
   实测被契约当场拦下：MinerU 的 `bbox_units="normalized"` 是 **0–1000 网格**，
   而 `AnchorSegment.rect` 的契约是 **0..1**（`validate_rect`）—— 必须除以 1000，否则直接抛错。
   `point` 单位需要页尺寸而 gate 层拿不到 → **返回 None**（宁缺勿造）。
2. **新增 `modules/evaluation/region.py`**：`normalize_rect`（三种单位 → 0..1）、
   `rect_iou`、`region_iou_or_none(expected, actual, *, independent)`。
   把"单位对齐"与"来源是否独立"变成**显式参数** —— 不声明就不算。
3. **装配点声明 `independent=False`**：`evaluation/legacy._navigation_checks` 现在填
   `expected_rect` / `actual_rect` / `rect_units`（`NavigationCheck` 新增三个可空字段，expand-first），
   但**拒绝产出 `region_iou`** —— 并配测试锁死这条纪律。
4. **原因码更正**：`source_pdf_has_no_coordinate_rects` → **`no_independent_region_truth`**；
   前端 `REASON_TEXT` 与新归因同步（旧文案"原文 PDF 未提供坐标矩形／拒绝编造 IoU"删除）。

### 仍然出不了值的（如实告知，不编造）

`anchor_region_hit_rate` 维持 `not_evaluated`。**要让它可测，需要第二个独立来源** ——
可行的具体做法是：同一份 PDF **同时**用 MinerU 与 PyMuPDF 解析（两者给出独立的区域估计），
再交叉比对区域。这是产品决策（多一次解析成本），留给用户拍板，本轮不动。

### 与规划的分歧（如实记录）

`docs/REFACTOR_PLAN_R4.md` 的 M6 写的是"expected=引用块矩形并集，actual=锚点 segment.rect"，
隐含假设 `segment.rect` 存在且**与 expected 独立**。实测两端都不成立（生产者原先不存在；
存在之后两者同源）。本 ADR 按**实测**定案，不按方案的假设实施 ——
否则产出的会是一个恒为 100% 的假指标。

---

## D-108 成果页可观测：**`manifest.capabilities` + `active_job` 是唯一进度真相**（R4-M7）

### 用户报的现象

> "点了处理之后他就直接跳转到成果那里了，但是一开始什么都没解析出，所以是一片空白，
> 我还要等一会然后手动刷新才能看到解析出的东西。"

### 根因（四条独立缺陷叠加，逐条读代码 + 实测确认）

1. `usePaperWorkspace.refresh()`：无 revision 时 `return` → `exhibits` 永远停在
   `{status:'idle', data:null}` 且**不重试**；
2. `paper/[slug]/page.tsx` 的"实时模式"门禁要求 `exhibits` 非空 → 恒为 null →
   **那段写死的 40×2.5s 轮询根本不会启动**；
3. `upload/page.tsx` 跳转时**丢掉 `job_id`** → `useJobEvents({job_id:0})` 永不连接
   （SSE 与 jobStatus 两条路都被挡掉）；
4. **页面早就拿得到进度真相却没人用**：`GET /manifest` 返回
   `capabilities[{name,state,reason}]` 与 `active_job`。实测全仓库只有 `fixtures.ts`
   与 `contracts.ts` 提到 `capabilities`，**没有任何组件消费它**。

### 改法

- 新增 `frontend/lib/paperProgress.ts`（纯函数，17 条单测）：
  `deriveProgress(capabilities, activeJob, elapsedMs)` → `{phase, domains, pending,
  currentReason, ratio, failureMessage, shouldPoll}`；
  三终态 `failed / unavailable / timeout`，以及 `extracting / ready`；
- **阻塞域 vs 非阻塞域**（实测发现的设计点）：真实库里 paper 11 的 `qa` 域**长期**
  `pending`（问答底库按需构建）。若"有 pending 就轮询"，每打开一篇已完成论文都会空转
  8 分钟 —— 那是轮询风暴。因此 `shouldPoll` 只在**有活跃作业**或
  **阻塞域（pdf/text/media/claims）未就绪**时为真；非阻塞域的 pending 照常显示。
- `LoadStateStatus` 新增 `'pending'`（"解析尚未产出 revision"是**正常中间态**，不是 idle）；
- `upload/page.tsx`：跳转带 `job_id`，**删除 900ms `setTimeout`**（它没有任何作用 ——
  响应里 job_id 已经有了，目标页本来就要处理 pending 态）；
- `page.tsx`：写死的轮询换成退避轮询（作业活跃 2s；空闲 1s→2s→5s 封顶；
  预算 8 分钟；页面隐藏时降频）；未就绪时渲染**分域进度 + 原因 + 三终态卡**，不再是空白。

### `stage_started` 现场核对（欠账 3，用库里真实作业事件）

```
job_id | stage    | starts       job_id 8..11（M12 修复后创建的作业）：
-------+----------+-------        无任何 stage 出现 2 次
     7 | acquire  |     2
     7 | claims   |     2
     6 | acquire  |     2         job 1..7（修复前创建）：
     6 | claims   |     2         acquire ×2（多为入队 emit 与领取 emit 各一次），
     6 | exhibits |     2         个别还有 claims / exhibits ×2
     5 | acquire  |     2
     4 | acquire  |     2
     3 | acquire  |     2
     2 | acquire  |     2
     1 | acquire  |     2
```

**结论（如实）**：M12 的"抑制连续重复 `stage_started`"在真实导入中**生效**——
修复后创建的作业（8/9/10/11）一次重复都没有；1–7 号作业是修复前留下的历史记录，
仍保留 2 次。**不修历史数据**（那是当时真实发生的记录）。

### 验收

后端 `pytest` **960 passed / 0 failed**；前端 `test:lib` **131 项**全绿（新增 17 项）。
手工判据见 `paperProgress.spec.ts` 的用例名（每条对应一个用户可见行为）。
