# 给 Kimi K3 的第四轮提示词（R4）：证据链状态、问答全放开、评测全面 AI 化、导入后自动长出来

> 使用方式：把本文件**全文**粘贴给 Kimi K3。它是自包含的，不依赖之前几轮的对话上下文。
> 项目根目录：`D:\develop\workspace\ResearchLens`（下称「仓库根」）。

---

## 0. 你的角色与硬性纪律

你是 ResearchLens 的架构师。任务不是"给我一份看起来合理的方案"，而是**先读代码、拿到证据、再写方案**。

**第一步必须先读代码**（不许跳过、不许凭项目类型想象）。读完之后，方案里每一条"现状"断言都必须带 `文件路径:行号` 证据；凡是没能读到证据的地方，写「未能确认」而不是猜。

纪律（违反任一条，方案作废）：

1. **不许编造数字**。任何指标没有真实算出来就写 `not_evaluated`，绝不用 `0` 冒充。这一条在本轮尤其重要，因为用户要求"全部 AI 直接打分"，很容易退化成"用 0 填满表格"。
2. **不许为了让测试通过而放宽阈值或删断言**。要改判据必须写清楚：原来是什么、为什么原来是错的、新判据的语义是什么。
3. **不许把 AI 判定伪装成客观测量**。AI 打分必须带 `basis="ai_generated"` 之类的来源标记，并在 UI 上写明"这是 AI 判定，不是人工真值"。
4. **原文可追溯性是底线**：任何"引文/证据原文"必须逐字来自解析出的原文块，禁止改写、禁止润色、禁止用示意图顶替。
5. **先写失败测试，再改实现**。每个模块的验收必须包含"改之前测试是红的"。
6. 后端改动后必须跑**全量** `pytest`（当前基线 **900 passed / 0 failed**），只许多不许少。前端跑 `npm run test:lib`（当前 70 项）与 `npm run test:hygiene`。端到端跑 `python scripts/acceptance/run_all.py`（当前 5/5）。
7. 方案要按 **M1、M2、M3…** 模块切分，每个模块给出：**现状（带证据）→ 目标 → 改法 → 验收（含红→绿的测试）→ 风险**。最后给**实施顺序**与**回滚点**。
8. 凡是要推翻已有决策的，必须指出被推翻的 ADR 编号（在 `docs/DECISIONS.md` 里），并写一条新 ADR 说明"为什么现在要反过来"。

---

## 1. 必读代码清单（请逐个打开，标注你读到的关键行）

### 1.1 证据链与证据状态

| 文件 | 读什么 |
|---|---|
| `frontend/components/evidence/EvidenceDrawer.tsx` | 全文。注意 `SUPPORT_META`（第 61–67 行）、`EvidenceContent` 空态（第 28–35 行）、`Promise.all` 取证据（第 86–107 行）、桌面 rail 容器（第 124–130 行） |
| `frontend/components/evidence/VerdictBadge.tsx` | 全文。四分类徽标 + 可展开 reasons |
| `frontend/lib/evidenceVerdict.ts` | 全文。四分类是"唯一真相"，含 `classifyVerdict`、`isNotApplicable` |
| `backend/app/modules/evidence/gate.py` | 重点 `_reason(...)` 的调用点、第 335 行 `unreviewed` 的产出、第 565–590 行 `candidate_to_segment` |
| `backend/app/modules/evidence/semantic.py` | 全文。`None` 表示"未判定"的三条来源 |
| `frontend/components/views/ClaimView.tsx` | 第 60–68 行：列表上的"已支持/未支持"与 `VerdictBadge` |
| `backend/app/contracts/evidence.py` | `support_status` 与 reason code 的合法取值 |

### 1.2 证据问答

| 文件 | 读什么 |
|---|---|
| `backend/app/modules/qa/service.py` | **最重要**。`answer()` 全流程（第 71–224 行），特别是：阶段 2.5 通用回答、阶段 2.55 检索为空、**阶段 2.6 `_object_absent_from_hits` 直接拒答**（第 166–177 行）、**阶段 3 `not grounded and not sentences → abstained`**（第 185–190 行）；再看 `_abstained`（第 1205 行起）、`_abstain_body`（第 1235 行起）、`_ensure_readable`（第 227 行起）、`_mode_for`（第 1360 行起） |
| `backend/app/modules/qa/answer_gate.py` | 全文。`grounded` 的唯一权威判据、`_confidence` |
| `backend/app/modules/qa/stream.py` | 终端保证、`final` 事件的构造与落库顺序 |
| `frontend/hooks/useQAStream.ts` | 全文（`final` → `completed`，`error` → `failed`） |
| `frontend/lib/sse.ts` | 全文（`parseSSEJson` 解析失败**静默返回 null**，第 128–135 行） |
| `frontend/components/views/QAView.tsx` | 全文。重点：`PRESETS`（第 25–29 行）、流式成功分支（第 93–131 行）、**流式失败分支**（第 132–164 行）、**`completed` 但没有 final → `fallbackPartial()`**（第 165–241 行，注意 `mode:'interrupted'`、硬编码 `confidence:'Low'`、`streamDoneRef` 一次性锁）、空态文案"无证据 → 拒绝编造"（第 329 行） |
| `backend/app/modules/qa/audit.py` + `backend/app/models/audit.py` + `GET /papers/{id}/qa/stream-audit` | 流式审计，用来对账"到底是客户端断了还是服务端没发 final" |

### 1.3 自动评测

| 文件 | 读什么 |
|---|---|
| `backend/app/modules/evaluation/metrics.py` | 第 193–247 行：`_overall` / `compute_overall`（人工口径）/ `compute_ai_overall`（AI 口径）/ `AI_PROXY_CORE` / `core_metric_missing`；第 293–310 行 `anchor_page_accuracy` 与 **`anchor_region_hit_rate`** |
| `backend/app/modules/evaluation/service.py` | `compute`（第 45 行起）、`run_golden`（第 104 行起）、`_compute_entries`（第 143 行起，注意第 217 行）、`_ai_judged_support`（第 368 行起） |
| `backend/app/modules/evaluation/ai_grader.py` | 全文。LLM 裁判，失败返回 `None`（未判定），绝不返回 0 |
| `backend/app/modules/evaluation/golden.py`、`golden_builder.py` | 金标集的"草案/调参集"概念、`confirm` |
| `backend/app/api/canonical.py` | `POST/GET /papers/{id}/golden-set`、`POST /papers/{id}/golden-set/confirm`（第 693–805 行）；以及 evaluation 相关端点 |
| `backend/app/contracts/evaluation.py` | 全文。`MetricValue`（`status/value/reason/method/unit`）、`overall_score_basis`、`NavigationCheck.region_iou` |
| `frontend/lib/evalMetrics.ts` | 全文（唯一指标解析入口，`measured/proxy/not_evaluated/unparsable` 四态） |
| `frontend/components/views/EvalView.tsx` | 全文。重点：第 86–111 行（human vs ai 两个口径）、**第 118 行"综合评分（人工真值口径）"**、第 137–166 行（"未确认"态 + AI 副卡）、第 171–189 行提示文案、proxy 标注 |
| `backend/app/modules/evaluation/legacy.py` | 第 150–195 行：`NavigationCheck` 是怎么从 anchor 派生出来的（`expected_rect` / `region_iou` 有没有被填） |
| `docs/DECISIONS.md` | **D-50 / D-65 / D-84 / D-101~D-103**：金标集来源纪律、"机器构造的集合不得当人工真值"、`anchor_region_hit_rate` 不可测的理由 |

### 1.4 导入后的成果页

| 文件 | 读什么 |
|---|---|
| `frontend/app/upload/page.tsx` | 第 52–91 行：`goToPaper(paperId, jobId?)`、上传/网址两条路径的 `router.push`（**注意第 66、84 行都没有传 jobId**） |
| `frontend/app/paper/[slug]/page.tsx` | 全文。重点第 115–136 行（slug 解析）、第 208–229 行 `loadLegacy`、**第 258–284 行"实时模式"门禁与轮询**、第 286–302 行 job 事件流、第 383–397 行 loading/error 分支 |
| `frontend/hooks/usePaperWorkspace.ts` | 全文。**注意第 44–45 行 `if (!rev) return;` 直接把 `exhibits` 留在 `{status:'idle',data:null}`** |
| `frontend/hooks/useJobEvents.ts` | 全文 |
| `frontend/lib/contracts.ts` | `PaperManifest.capabilities` / `active_job`（第 1005–1035 行附近）、`Capability` 的 `state` 取值 |
| `frontend/components/jobs/JobProgress.tsx` | 现有阶段进度组件 |
| `backend/app/api/canonical.py` | `GET /papers/{id}/manifest` 的实现：`capabilities` 与 `active_job` 是怎么算出来的 |
| `backend/app/modules/pipeline/service.py`、`resume.py` | 阶段推进、`job_events` 的 `stage_started/stage_finished` |

---

## 1.5 已拍板的产品决策（硬约束，**不得再作为开放问题提出**）

以下四条是**产品负责人（用户）已经明确拍板**的，不是"待讨论选项"。方案必须直接按这四条设计；**不许**在方案里再问"要不要保留人工确认""拒答是否彻底消失"之类的问题，也不许设计出"留一半"的折中（例如"默认自动确认但仍保留人工入口"）。

| # | 决策 | 原话 |
|---|---|---|
| 1 | **拒答彻底消失**。所有问题都可问、都返回回答，用置信度表达可靠程度。`mode=abstained` 从产品语义中退出。 | 「拒答直接彻底消失，反正有置信度说明。」 |
| 2 | **低置信度回答允许附"与问题最接近的原文片段"**（必须标注未通过证据校验、逐字来自原文）。 | 「可以附。」 |
| 3 | **一切跟人工有关的全部删掉**：人工确认端点、人工真值口径、草案/已确认状态、相关字段与文案，一律删除（不是隐藏、不是保留但不用）。 | 「人工有关的全部删掉。」 |
| 4 | **综合评分改名为「AI 质量评分（自动）」**，作为主分直接出值；不再有"人工真值口径"字样、不再有"未确认"占位。 | 「那就改成"AI 质量评分（自动）"。」 |

**这四条会连带推翻已有的 ADR（至少 D-50、D-65；决策 1 还会影响 D-84 一带的问答策略与 `docs/ARCHITECTURE.md:125` 的"禁止编造 → 未找到依据"表述）**。方案里必须：逐条列出被推翻的 ADR/文档位置，并写新 ADR 说明"为什么现在反过来、保留了哪些纪律"。

**唯一不允许被这四条推翻的东西**（这是本项目的底线，请在方案里显式复述）：

1. `not_evaluated` 不许写成 `0`；缺失值必须带原因码。
2. AI 判定必须标注来源（AI ≠ 客观测量）；「AI 质量评分（自动）」这个名字里的 "AI/自动" 不许省。
3. 引文/原文片段必须**逐字**来自解析出的原文块，禁止改写、润色、用示意图顶替。
4. 改完必须能跑通全量测试（后端 900 passed 基线只许多不许少）。

---

## 2. 用户本轮提出的问题（逐条，含我已实测到的证据）

> 下面「已实测」的结论是上一轮在**真实运行环境**（`docker-compose` 四容器都在跑，后端 `8002`、前端 `4002`）里跑出来的，可以直接采信为出发点，但**你仍要打开代码确认行号**，并补上我可能漏掉的路径。

### 需求 A：证据链里"未支持"的理由（证据不足 / 未判定 / 暂无证据）是不是原本的设计？

用户原话：

> 我还发现证据链里会有一些证据显示未支持，理由有证据不足，未判定和暂无证据，这是原本就这么设计的吗。

**已实测结论：是设计，但设计得不完整，另外有一个真 bug。** 三个词来自三层不同状态：

1. `证据不足` → `EvidenceDrawer.tsx:64` 的 `SUPPORT_META.insufficient`，对应后端 `evidence_records.support_status="insufficient"`（语义判定跑了，结论是"原文不支持这句话"）。
2. `未判定` → `EvidenceDrawer.tsx:65-66` 的 `SUPPORT_META.unreviewed / ''`，对应 `gate.py:335` 产出的 `"语义未判定（模型未返回结论）"`。真实成因通常是**语义判定器没跑或中途失败**（`semantic.py`：未配置 LLM / 调用失败 / 全局 deadline 过期 → 返回 `None`）。`docs/DECISIONS.md` 里有过一次实测事故：用默认 120s deadline 导致"所有 claim 变 unverified，看起来像这篇论文没有可验证断言"。
3. `暂无证据` → `EvidenceDrawer.tsx:28-35` 的空态，因为**选中的这条 claim 的 `evidence_ids` 为空**。

**真 bug（实测）**：`EvidenceDrawer.tsx:93-99` 用 `Promise.all(evidence_ids.map(...))` 逐条拉证据，`.catch(() => setEvidence([]))` —— **任意一条请求失败就会把已经取回的证据全部清空**，界面显示"暂无证据"，把一个网络抖动伪装成"没有证据"。

**你要做的**：
- 三态在 UI 上必须**各自可解释**：点开能看到原因（与 `VerdictBadge` 的 reasons 展开同源，不要另造一套文案）；`未判定` 必须把后端原因码/原因文本显示出来（"模型未返回结论 / 语义判定超时"是两种完全不同的用户可操作状态）。
- 区分 `暂无证据` 的三种成因：**尚未抽取**（流水线未到 claims/verify 阶段）／**该断言确实无关联证据**／**拉取失败**。三者不许都显示"暂无证据"。
- 修掉上面那个 `Promise.all` 的全清 bug：要么 `allSettled` 逐条降级，要么把失败单独呈现。
- 判断一下：`证据不足`（insufficient）与 M2 的四分类徽标（`non_claim / contradiction / rejected_other / insufficient`）在同一个界面上**同时出现会不会互相打架**？如果会，给出统一方案（我倾向：抽屉里以"支撑结论"为主、四分类作为"为什么"的补充，且两者共用同一份 reasons）。

### 需求 B：证据面板要跟随页面滚动（sticky）

用户原话：

> 证据链里的右边的那个证据面板应改为随着页面滚动而一直保持滚动，就是在证据链里往下滑的时候那个证据面板也应该始终在页面里可见，不然我点查看比较下面的证据但是证据面板里的内容一直在最上面我还要划上去才能看到，观感不好。

**已实测根因**：`frontend/app/paper/[slug]/page.tsx:399-402` 的容器在 `view === 'claim'` 时是 `lg:grid-cols-[minmax(0,1fr),360px]`，grid 子项默认 `stretch`；抽屉在 `EvidenceDrawer.tsx:126` 是 `h-full overflow-y-auto`。于是"面板高度 = 左列（很高的）行高"，面板内容永远贴在它自己那个超高盒子的**顶部**，页面往下滚时内容就滚出视野了。

**你要做的**：桌面 rail 改成 `sticky`（顶部偏移要避开页面顶部那条 `sticky top-0 z-30` 的 header，以及底部 `sticky bottom-0` 的 timeline），高度用 `max-h-[calc(100vh-…)]` + 面板内部滚动；`lg` 断点以下（移动抽屉）行为不变。请顺带检查：**滚动到列表下方的某条 claim 时，面板内容是否也跟着切到那条 claim**（用户描述里"我点查看比较下面的证据"就是这个场景，如果点击后不自动滚回面板顶部，粘住也没用）。

### 需求 C：证据问答删掉"无证据 → 拒绝编造"，所有问题都可问，只给置信度

用户原话：

> 然后证据问答直接删掉无证据 → 拒绝编造这个字段，所有问题都可问，只不过会给出置信度。比如我现在问那三个默认问题依旧是一直被中断理由显示low置信度，我觉得不应该这么设置，而是全部问题都可问，然后给回答保持置信度就行了不要直接中断那些低置信度问题。

**已实测证据（真实调用后端，`POST /api/papers/11/qa/stream`）**：

- 三个默认问题 = `QAView.tsx:25-29`：`这篇论文哪里最值得质疑？` / `这篇论文的主要贡献是什么？` / `论文用了什么数据集？`
- 问「主要贡献」→ SSE 事件序列 `meta,status,status,citation×3,sentence×3,final`；final：`grounded=True, confidence=High, mode=generated`。
- 问「用了什么数据集」→ 同样有 `final`；`grounded=True, confidence=High, mode=generated`。
- 问「哪里最值得质疑」→ `meta,status,status,final`（**没有 citation / sentence**）；final：`grounded=False, confidence=Low, mode=abstained`，note = `论文中没有足够的已验证证据支持回答；已按 Evidence Gate 拒绝进入事实层。`，正文是拒答文案 + 「与问题最接近的原文片段（论文原文，仅供参考、未通过证据校验）」。
- 所以：**后端三条都发了 `final`**，"low 置信度"确实存在（走的是 `service.py:185-190` 的 abstain 分支），但**"回答被中断"这个徽标不是后端发的**。

**结论分两半，你要分别处理**：

1. **拒答彻底消失（已拍板，见 §1.5 决策 1）**：`service.py` 里有**至少四处**以"无证据"为由走向 `_abstained`：阶段 2.55 的 `object_absent`（第 157 行）、阶段 2.6 的 `_object_absent_from_hits` 直接拒答（第 166–177 行）、阶段 3 的 `not grounded and not sentences`（第 187–190 行）、以及闲聊/非论文问题在模型不可用时的兜底（第 119–123、140–144 行）。**这四处全部不再返回拒答**，改成"给回答 + 标置信度"。要求：
   - **`mode="abstained"` 这个取值要从产品语义里退出**。请给出新的 `mode` 取值表（起码要有：有证据作答 / 抽取式作答 / 通用回答 / 论文未提及 / 缓存），并说明 `abstained` 是删掉、还是仅保留为内部兼容取值（若保留，必须是**前端永远见不到**的死值，不能出现在 API 响应里）。
   - **低置信度回答的内容来源**：优先**逐字来自原文块**的抽取式内容（`_extractive_draft` / `_draft_from_hit` / `_closest_snippet` 已有能力）；退而求其次才是**明确标注"未使用论文证据"**的通用回答。禁止编造。**已拍板：允许附"与问题最接近的原文片段"**（决策 2），但必须显式标注它未通过证据校验，且片段逐字来自原文。
   - **置信度口径**：给出 High / Medium / Low 三档的**判据**（不是感觉），并说明每一档在 UI 上怎么显示。注意 `answer_gate._confidence`（`answer_gate.py:173-179`）现在只在 `grounded=True` 时给 High/Medium，`grounded=False` 一律 Low——这套逻辑要么改，要么扩，请写清。
   - **`grounded` 的语义不变**：它仍只表示"逐句通过 Evidence Gate"（`answer_gate.py`）。**不许**因为"不再拒答"而放宽 `grounded`——否则 `unsupported_fact_escape_rate` 等指标会直接失守。也就是说：以后一个回答可以是「`grounded=False` + `confidence=Low` + 有正文 + 有原文片段」，用户看到的是"低置信度的回答"，不是"拒答"。
   - **两个拒绝类指标必须重新定义，不许留成永远为 0 的死指标**：`unanswerable_refusal_rate` 与 `answerable_false_refusal_rate`（`metrics.py` 的 `refusal_metrics`），以及判据函数 `_is_refusal`（`metrics.py:312-329`）。既然"拒答"动作消失了：
     - `answerable_false_refusal_rate` 测的行为**已经不存在** → 倾向于**删除该指标**（并同步删它的 `METRIC_NAMES` 条目、前端标签、以及 `not_evaluated` 映射），而不是留一个恒为 0 的绿条。
     - `unanswerable_refusal_rate` 的口径要从"是否拒答"改成"对真正不可答的问题，系统是否**如实说明没有证据**（`not_mentioned` / 低置信度标注）"，并相应改名（例如 `unanswerable_honesty_rate`）。改名要同步改 `METRIC_NAMES`、前端 `EvalView.tsx` 的 `RATIO_METRICS`、`evalMetrics.ts` 的原因码表、以及相关测试。
     - 无论删还是改名，**必须给出完整的同步清单**（后端常量 / DTO / 前端标签 / 测试 / 文档 / 验收脚本），漏一处就会留下一个永远显示"未评测"的空格子。
   - 前端 `QAView.tsx:329` 的「无证据 → 拒绝编造」文案删除，换成能表达"每个问题都有回答，回答带置信度"的文案。
2. **「回答被中断」徽标（先复现再改）**：这个徽标只有一个来源 —— `QAView.tsx:165-241` 的 `fallbackPartial()`，触发条件是 `stream.state === 'completed' && !finalEv`（流正常结束但**没有 final 事件**）。而 `confidence:'Low'` 是那里**硬编码**的。有两个可疑点，请**先复现、再定位、再修**：
   - `lib/sse.ts:129-135` 的 `parseSSEJson` 解析失败会**静默返回 null**，`useQAStream.ts:48` 直接 `if (!ev) return;` 丢弃该事件 → final 消失 → 客户端判"被中断"，而且**没有任何日志**。
   - `streamDoneRef` 是一次性锁：一旦走了 `fallbackPartial()`，之后即使 final 到达也不会再更新消息，"被中断"就永久留在界面上（这解释了用户说的"一直"）。
   - **要求**：给出一个**能稳定复现**的用例（或明确说"我在本地复现不出来，用户看到的是 abstained+Low 那条路径"），并据此决定改法。无论哪种，`fallbackPartial` 都不该把"连接层异常"呈现成一个**看起来像正常业务结论**的"回答被中断 · 置信度 Low"。

### 需求 D：自动评测全面 AI 化，取消一切人工环节

用户原话：

> 我建议就是直接取消一切跟人工有关的，那个自动评测直接全部ai评ai打分。……然后自动评测就按我刚刚说的改，综合评分，各项指标什么率的全部ai直接完成，取消人工操作并且把综合评分右边的（人工真值口径）字段删掉。

**已实测现状**：

- `EvalView.tsx:118` 的标题就是「综合评分（人工真值口径）」；人工分为 null 时显示「未确认 / NOT CONFIRMED」（第 137–148 行），并在第 152–166 行单独挂一张 amber 的「AI 评分（非人工真值）」副卡。
- 两个口径在后端是分开算的：`metrics.compute_overall`（要求四项核心指标全 `measured`）与 `metrics.compute_ai_overall`（允许 `support_precision` 以 `proxy` 参与，`AI_PROXY_CORE`）。
- 「人工真值」之所以出不来，是因为金标集是**机器从原文自动构造的草案**，`docs/DECISIONS.md` 的 **D-50** 明文规定"机器构造的集合不得当人工真值"，且 `golden_builder` 有 `build_and_save_ai`（AI 起草）与 `confirm_for_scope`（人工确认）两条路。

**你要做的**（决策 3、4 已拍板，见 §1.5）：把"人工"这条线**从产品里彻底删除**，不是隐藏、不是留一个默认自动点一下的确认按钮。

- **后端**：
  - `overall_score` 直接用 **AI 口径**（`compute_ai_overall`）出值，`basis` 标明来源是 AI。人工口径函数 `compute_overall` / `core_metric_missing` **删掉**（不是保留不用）。
  - `POST /papers/{id}/golden-set/confirm` **删除**（路由、handler、schema、前端调用、`api.ts` 里的封装、以及引用它的测试一并删）。`golden_builder.confirm_for_scope` 与 `golden` 的 `is_tuning`/"草案 vs 已确认"概念**删掉**；金标集只剩一种形态：AI 从原文构造。
  - `POST/GET /papers/{id}/golden-set` 保留（它是 AI 生成金标集的入口），但响应里不再有 `status: "draft（机器构造，待人工确认）"` 这类人工语义字段。
  - `golden_not_annotated` 这条 warning 与 `EvalView` 里 `goldenTuning` 的分支同理：要么删，要么改成纯 AI 口径的说明。
  - 给出**完整影响面清单**：哪些端点、哪些响应字段、哪些 `Warning.code`、哪些测试会因此变化或删除。
- **前端**：
  - 删掉 `EvalView.tsx:118` 的「（人工真值口径）」字样。
  - **主卡标题改为「AI 质量评分（自动）」**（决策 4，原话要求）——这是主分，不再是"未确认"占位。
  - 删掉第 137–148 行的"未确认 / NOT CONFIRMED"态；删掉第 152–166 行那张 amber 副卡（AI 分数已经上主位，不再需要副卡），但**保留"这是 AI 判定、不是人工真值"这句来源说明**（可以缩成主卡下方一行小字）。
  - 删掉第 171–189 行里所有"需要人工确认 / 人工真值"的提示文案，重写成 AI 口径的说明。
  - `frontend/lib/evalMetrics.ts` 的 `OverallView { human, ai }` 双口径结构收敛为单一分数字段（**注意：`frontend/tests/evalMetrics.spec.ts:147` 有 `assert.strictEqual(o.human, null, ...)`，这条断言要跟着改，不许直接删掉测试**）。
- **纪律不能丢**：
  - `not_evaluated` 仍然不许写成 `0`；缺失项仍要显示"未评测 + 原因码"。
  - 评分来源必须可见（AI 判定 ≠ 客观测量）。用户要的是"不用人来点确认"，**不是**"不要标注来源"。所以「AI 质量评分（自动）」这个名字本身就要保留"AI/自动"字样，不许简化成中性的"综合评分"。
- 这会**推翻 D-50 / D-65**。请写新 ADR（编号接在 D-103 之后），标题类似"产品决策：取消人工真值维度，自动评测全面 AI 化"，正文必须包含：**被推翻的旧决策、推翻的理由（真实约束是什么）、保留了什么（哪些纪律没有被放弃：`not_evaluated≠0`、来源标注、引文逐字可追溯）、代价是什么（分数不再具备人工校验的可信度，UI 必须靠标注传达这一点）**。

### 需求 E：各项"率"全部要 AI 出值

用户原话：

> 各项指标什么率的全部ai直接完成。

**已实测现状**：

- `anchor_region_hit_rate` 现在是"永远不可测"：`metrics.py:303-309` 在 `with_iou` 为空时返回 `not_evaluated(reason="无区域 IoU 样本")`，对外映射为 `source_pdf_has_no_coordinate_rects`；`docs/DECISIONS.md` 与 R3 计划都把它定为**设计选择**（"原文 PDF 没有坐标矩形，拒绝编造 IoU"）。
- **但我实测到坐标数据可能是存在的**：`backend/app/modules/parse/normalize.py:145-161` 会给块的 `raw_ref` 带上 `bbox_values` / `bbox_units`（`mineru` 是 0–1000 归一化网格，`pymupdf` 是 point），`documents.py:168-170` 有 `bbox_values/bbox_units/coordinate_frame` 字段。而 `NavigationCheck.region_iou`（`contracts/evaluation.py:74` 附近的 `expected_rect`、以及 `region_iou` 字段）看起来**从来没有被填过**，`evaluation/legacy.py:150-195` 派生 check 时是否带上 rect 需要你确认。
- 其余 `support_precision` / `support_recall`：`metrics.py` 里它们是 `status="proxy"`（`support_metrics`），已有 `_ai_judged_support`（`service.py:368` 起）用 LLM 判等给 AI 口径的值。

**你要做的**：

- **先查清 `anchor_region_hit_rate` 到底能不能真算**：把 `parse → normalize(AnchorSegment.rect / quads) → evidence.gate.candidate_to_segment → evaluation.legacy 派生 NavigationCheck` 这条链走一遍，确认 `rect`/`quads` 在真实论文上是否非空。结论只有两种，都要给出证据：
  - **能算** → 真算 IoU（注意 MinerU 是归一化网格、PyMuPDF 是 point，**单位必须先对齐**，不许把两种坐标直接相减）；R3 里"不可测"的结论要更正，并写 ADR。
  - **不能算** → 用 **AI 裁判**给区域命中判定（把"锚点声称定位到的区域"与"引文实际所在的块/页"交给 LLM 判是否一致），`status` 标 `proxy` 或新的 `ai_judged`，`method` 写清口径，UI 标"AI 判定"。**不许**用 0 或任何默认值填。
- `support_precision` / `support_recall` 在"取消人工真值"后，统一走 AI 金标集 + AI 判等出值，并标 `basis`。
- 给出**最终指标清单**：每个指标一行，标注 `measured / proxy(ai) / not_evaluated(+reason)`，以及"这个值是程序算的还是 AI 判的"。如果最后仍有指标**真的**出不了值，明确写出来并说明为什么——用户要的是"尽量全出"，不是"必须全出，出不了就编"。

### 需求 F：导入后"成果页"要自己长出来（现在是白屏 + 手动刷新）

用户原话：

> 然后现在真实导入正常了，但是我点了处理之后他就直接跳转到成果那里了，但是一开始什么都没解析出，所以是一片空白，我还要等一会然后手动刷新才能看到解析出的东西，这一点应该给出方案改动。

**已实测根因（四条独立缺陷叠加，我已逐条读代码确认）**：

1. `frontend/hooks/usePaperWorkspace.ts:44-45`：`const rev = m.revision?.id; if (!rev) return;` —— 解析尚未产出 revision 时**提前返回**，`exhibits` 永远停在 `{status:'idle', data:null}`，而且**不会自动重试**。
2. `frontend/app/paper/[slug]/page.tsx:259-264`：进入"实时模式"的条件是 `exhibits && canonicalClaims.length === 0 && detail?.source_mode === 'upload'`。`exhibits` 是 `.data`，此时恒为 `null` → **`processing` 永远不会置真 → 第 266–284 行那段 40×2.5s 的轮询根本不会启动**。
3. `frontend/app/upload/page.tsx:66` 与 `:84`：`goToPaper(up.paper_id)` **没有传 `jobId`**。于是 `page.tsx:287` 的 `useJobEvents({job_id: 0})` 永远不会连上 SSE（第 288–302 行的 jobStatus 轮询同样被 `!jobId` 挡掉）。→ **上传路径完全没有进度可观测性**。
4. 页面已经有现成的进度真相却**完全没用**：`GET /api/papers/{id}/manifest` 返回 `capabilities: [{name, state, reason}]` 和 `active_job`。我实测 paper 11（已完成）：`pdf/text/media/claims/graph/presentation/evaluation = ready`、`qa = pending`；paper 8（从未成功处理）：`pdf=unavailable(reason="无源文件")`、`text/media/claims/graph/presentation/evaluation = pending(带 reason)`。**前端全仓库只有 `fixtures.ts` 和 `contracts.ts` 提到 `capabilities`，没有任何组件在用**（我已 grep 确认）。

**你要做的**：给一条"从上传/点处理到成果出现"的**端到端可观测方案**，至少覆盖：

- 以 `manifest.capabilities` + `manifest.active_job` 作为**唯一的进度真相**（别再依赖"exhibits 非空"这种间接信号）。
- 未就绪时页面显示什么：**分域进度**（解析 / 媒体 / 断言 / 证据 / 图谱 / 讲解 / 评测）而不是一句"正在解析论文…"；每个 `pending` 的 `reason` 要能显示出来。
- 就绪后**自动**切到内容，无需手动刷新；无 `job_id` 时也要有轮询（给退避策略与上限，别再写死 40×2.5s）。
- `unavailable` / 失败 / 超时三种终态各自的界面与文案（现在 paper 8 那种"无源文件"会让用户对着一片空白）。
- 顺带评估：`upload/page.tsx` 那 900ms `setTimeout` 后再跳转是否合理？是否应该在跳转前就把 `paper_id + job_id` 都拿到（需要后端在 upload/from-url 响应里返回 job_id——请确认现在返回了什么，我实测 `/api/papers/upload` 的返回类型里**有 `job_id` 字段**，说明数据是有的，只是前端没用）。

---

## 3. 我（上一轮的执行者）建议一并纳入的事项

这几条是已知的、还没做完的欠账，用户大概率会让你一起做，请一并纳入方案（如果认为不该做，请给出理由）：

1. **M10 物理迁移（未完成）**：R3 的 M10 只做到了"一份真实实现 + 薄委托 + 三层门禁"（双读一致性 / 静态 `to_legacy_` 白名单 / 薄委托行数），**四域实现并没有真的搬到 `app/projection/` 包**。这已经在 `docs/DECISIONS.md` 的 D-101/D-102 和 `backend/app/projection/CONTRACT.md` 里显式登记为待办。请给出这一步的具体迁移方案（移动哪些文件、`adapters` 如何 re-export、白名单如何收窄、怎么保证 900 个测试不掉）。
2. **图谱节点的四分类徽标没接线**：`GraphView` 的证据节点只有 `support_status`，**没有 `reasons`**，所以 M2 做好的 `VerdictBadge` 接不上去。需要后端在投影图谱节点 props 时带上 reasons（顺带确认这是不是又一次"投影丢字段"——上一轮已经因为 `to_legacy_graph` 白名单把 `props.support_status` 丢掉而踩过一次）。
3. **真实导入现场核对 `stage_started` 去重**：目前只有单测覆盖，没做过一次完整的真实导入去核对 `job_events` 里 `stage_started` 是否还会重复。恰好和需求 F 是同一片区域（`useJobEvents` / `JobProgress`），请合并处理并给出**现场核对步骤**（用什么命令、看什么输出、判据是什么）。
4. `EvidenceDrawer` 的 `Promise.all` 脆性（见需求 A 的"真 bug"）。
5. **验收脚本**：`scripts/acceptance/` 现有 5 个脚本（`run_all.py` 是入口）。需求 F 需要一个**新的现场验收**（上传 → 进度可见 → 内容自动出现 → 无需刷新），请把它加进 `run_all.py`，并保持退出码约定（0 通过 / 1 断言失败 / 2 环境不可用）。

---

## 4. 交付物格式（严格按此输出）

1. **前言**：你实际读了哪些文件（路径列表）、有哪些地方你没能读到/无法确认。
2. **模块计划**：`M1 … Mn`，每个模块按固定五段写：
   - **现状**（每条带 `文件:行号` 证据）
   - **目标**
   - **改法**（具体到函数/组件/字段；涉及接口变更的要写清新旧字段与兼容策略）
   - **验收**（先红后绿的测试名 + 断言内容 + 手工验证步骤）
   - **风险与回滚点**
3. **指标最终清单**（需求 E 要求的那张表）。
4. **剩余的技术性问题**（**只允许问实现层面的，不许再问 §1.5 里已拍板的四条**）：把你实现时确实拿不准、且需要工程取舍的问题列出来（例如：`mode` 旧值 `abstained` 在数据库已有历史行时怎么迁移；`unanswerable_refusal_rate` 改名的兼容期怎么处理；`candidate_to_segment` 的 `rect` 单位对齐在哪一层做）。每条给出**你的建议 + 理由 + 不选的代价**。**如果这一节里出现了"是否取消人工确认""拒答是否保留"这类问题，视为没有认真读 §1.5。**
5. **实施顺序**：M 之间的依赖关系，哪些可以并行，哪些必须串行；每个模块预估的改动面（文件数、测试数）。
6. **ADR 清单**：本轮需要新增/推翻的决策编号与标题（从 D-104 起），每条一句话结论。
7. **不要写代码补丁**。这一轮只要方案。方案里可以引用关键代码片段（≤15 行）来说明问题，但不要给出完整实现。

---

## 5. 附：几个容易被搞错的事实（省得你踩坑）

- 数据是**双轨**的：legacy 表 + canonical 表（`claim_records/statements/validations/evidence_records/media/job_stage_keys/qa_stream_audits/...`），legacy 通过 `adapters` / `modules/*/legacy` 投影。改任何一处都要想清楚投影层。
- `not_evaluated` 与 `0` 是两个不同的东西，这是本项目反复强调的纪律，**注意：D-50 会被本轮推翻，但这一条纪律不随之作废**（它和"要不要人工真值"是两件事）。实现细节见 `frontend/lib/evalMetrics.ts` 的四态（`measured / proxy / not_evaluated / unparsable`）与 `backend/app/contracts/evaluation.py` 的 `MetricValue`。
- 流水线阶段顺序是 `STAGE_ORDER = ["acquire","parse","normalize","media","index","claims","verify","exhibits","qa_bank","evaluate","publish"]`，进度事件写进 `job_events`，幂等靠 `job_stage_keys`（唯一键 `revision_id + stage + input_digest + algorithm_version`）。
- 前端**没有测试框架**：测试是 `tsc` 编译到 `.tmp/<name>-test` 再用 `node` 跑（见 `frontend/tests/*.spec.ts` 与 `package.json` 的 `test:lib`）。不要引入 vitest/jest。
- 所有前端展示文本必须走统一富文本内核（`frontend/lib/richtext.ts` + `<MathText>`），并且有门禁脚本 `frontend/scripts/check-text-paths.cjs` 在盯着**允许列表**——新加展示点要同步更新白名单，否则门禁会红。
- 后端跑测试用 `backend\.venv\Scripts\python.exe -m pytest`，并且**不要并发跑**（并发会抢同一个 `_tmp_shared/unit.db` 导致 PermissionError）。改动 schema 时需要先删 `backend/app/tests/unit/_tmp*/` 下的测试库。
- 容器用 `docker-compose`（**不是** `docker compose`），且必须从仓库根目录执行。
