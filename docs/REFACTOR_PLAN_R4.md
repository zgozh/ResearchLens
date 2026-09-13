# ResearchLens 第四轮重构方案（R4）

> 版本：v1.0（2026-09-13）｜性质：方案文档，不含实现代码补丁
> 验收基线：后端 `pytest` **900 passed / 0 failed**（只许多不许少）、前端 `test:lib` **70 项**、`test:hygiene`、端到端 `scripts/acceptance/run_all.py` **5/5**
> 四条产品决策（§1.5）已拍板，本方案直接按其设计，不再提出开放问题。

---

## 前言：实际读过的文件与未能确认项

### 已读文件（本轮逐一打开核对）

**证据链**：`frontend/components/evidence/EvidenceDrawer.tsx`（全 159 行）、`frontend/components/evidence/VerdictBadge.tsx`（全 74 行）、`frontend/lib/evidenceVerdict.ts`（全 121 行）、`backend/app/modules/evidence/gate.py`（L320-360、L555-600）、`backend/app/modules/evidence/semantic.py`（L1-80）、`frontend/components/views/ClaimView.tsx`（L50-80）

**问答**：`backend/app/modules/qa/service.py`（L60-260、L1190-1310、L1340-1405）、`backend/app/modules/qa/answer_gate.py`（全 189 行）、`backend/app/modules/qa/stream.py`（L1-101）、`backend/app/modules/qa/audit.py`（全 104 行）、`frontend/hooks/useQAStream.ts`（全 72 行）、`frontend/lib/sse.ts`（全 135 行）、`frontend/components/views/QAView.tsx`（全 470 行）、`backend/app/contracts/qa.py`（grep：AnswerMode）

**评测**：`backend/app/modules/evaluation/metrics.py`（L180-340）、`backend/app/modules/evaluation/service.py`（L40-240）、`backend/app/modules/evaluation/ai_grader.py`（全 197 行）、`backend/app/modules/evaluation/golden_builder.py`（L1-80）、`backend/app/modules/evaluation/golden.py`（grep is_tuning）、`backend/app/modules/evaluation/legacy.py`（L140-210）、`backend/app/contracts/evaluation.py`（全 207 行）、`frontend/lib/evalMetrics.ts`（全 255 行）、`frontend/components/views/EvalView.tsx`（全 339 行）、`frontend/tests/evalMetrics.spec.ts`（L135-155）、`backend/app/api/canonical.py`（L85-214、L437、L534-552、L685-806）

**成果页**：`frontend/app/upload/page.tsx`（L1-111）、`frontend/app/paper/[slug]/page.tsx`（L250-410）、`frontend/hooks/usePaperWorkspace.ts`（全 63 行）、`frontend/hooks/useJobEvents.ts`（全 72 行）、`frontend/lib/contracts.ts`（grep：L986/1014-1015/1033）、`frontend/components/jobs/JobProgress.tsx`（L1-61）、`backend/app/modules/pipeline/service.py`/`repository.py`（grep stage_started/job_stage_keys）、`backend/app/modules/parse/normalize.py`（L135-175）

**决策记录**：`docs/DECISIONS.md`（D-50 L569-583、D-52 L602-629、D-65 L1050、D-84 L1567、D-100~D-103 L1916-1996）、`docs/ARCHITECTURE.md:125`

### 未能确认项（如实登记，不猜）

1. **`CandidateEvidence.rect/quads` 的生产者**：`gate.candidate_to_segment`（gate.py:570-590）消费 `cand.rect`，但候选的 rect 从哪个定位路径填、在真实论文上是否非空，本轮未追到装配点 → M6 第一步必须实证（见 M6 改法 0）。
2. **blocks 的 `raw_ref.bbox_values` 在真实 MinerU 产物上的覆盖率**：`normalize.py:145-161` 只在 `rb.bbox` 非空时写 raw_ref；真实论文有多少块带 bbox，需用库内数据实测（M6 改法 0 给出核对 SQL）。
3. **`docs/ARCHITECTURE.md:125` 的上下文**：只 grep 到一行，改写时需读全段。
4. **`stage_started` 在真实导入中是否重复**：只有单测覆盖，未做现场核对（与 M7 合并处理，给出核对步骤）。
5. **`frontend/scripts/check-text-paths.cjs` 的白名单结构**：未逐行读，M4/M5 改文案与展示点时需同步更新（已知它是 8 个展示点的门禁）。

### 与任务书实测的一处出入（如实说明）

任务书说 QAView 证据卡是 `{e.text || e.quote}` 裸渲染。本轮实读 `QAView.tsx:396/398`，两处**已经包在 `<MathText>` 里**（R3-M1 已修）。本轮不再把它当裸渲染处理；真正的 QA 前端问题在 §M4（interrupted 徽标与文案）。

---

## 模块计划

---

### M1 证据状态三态可解释 + Promise.all 全清 bug（需求 A）

**现状（带证据）**

- 三态文案来自三处不同状态，设计如此但不完整：
  - 「证据不足」= `SUPPORT_META.insufficient`（`EvidenceDrawer.tsx:64`）← 后端 `support_status="insufficient"`，语义判定跑过且结论为不足（gate.py:336 是无 LLM 时的产出之一）。
  - 「未判定」= `SUPPORT_META.unreviewed / ''`（`EvidenceDrawer.tsx:65-66`）← `gate.py:335`：`gate.llm_available` 为真但模型未返回结论时产出 `"unreviewed", None, "语义未判定（模型未返回结论）"`；`semantic.py` 的 docstring（L23-26）说明调用失败/超时/解析错**降级为 unreviewed**——即"未配置 LLM"与"判定超时"与"输出非法"三条成因被压成一个状态。
  - 「暂无证据」= 空态（`EvidenceDrawer.tsx:28-35`），成因至少三种：evidence_ids 为空（`EvidenceDrawer.tsx:87-88` 直接 `setEvidence([])`）、流水线未到 verify、拉取失败。
- **真 bug**：`EvidenceDrawer.tsx:93-99` `Promise.all(...).catch(() => setEvidence([]))`——任意一条证据请求失败即清空全部已取回证据，网络抖动被伪装成"没有证据"。
- 四分类徽标（`VerdictBadge.tsx` + `lib/evidenceVerdict.ts:97-116`）只接在 ClaimView 列表（`ClaimView.tsx:68`），抽屉内只有 `VerificationStatus` 单行结论，两者**不共用 reasons**。

**目标**

1. 三态各自可解释：抽屉里每条非 supports 证据可展开看原因，且与 VerdictBadge 共用同一份 reasons（不另造文案）。
2. 「未判定」必须区分成因：模型未配置 / 语义判定失败（超时、解析错）/ 流水线尚未执行——至少前两种要分开显示。
3. 「暂无证据」区分三成因：尚未抽取 / 该断言确无关联证据 / 拉取失败，三文案不同。
4. 修 Promise.all 全清：逐条降级，失败单条呈现。
5. 统一"支撑结论"与"四分类"的关系：抽屉以支撑结论（支持/反驳/证据不足/未判定）为主，四分类作为"为什么"的补充，共用 reasons。

**改法**

- 后端（小改，扩字段不改语义）：
  - `semantic.py` 降级路径把成因写入 verdict 产物的 reason 文案前缀（`模型未配置` / `语义判定失败:{exception_type}` / `输出非法`），gate.py:335 的 `_reason` 文案同步细分（产出不同 reason code：`semantic_unavailable` / `semantic_failed` / `semantic_timeout`）。`evidence_records` 加可空列或复用现有 reasons 通道下发（expand-first，可空）。
  - `GET /evidence/{id}` 响应的 validation 段补 `reasons`（抽屉展开用，与 ClaimView 列表同源）。
- 前端：
  - `EvidenceDrawer.tsx`：`Promise.all` → `Promise.allSettled`，每条失败渲染"该条证据拉取失败（可重试）"占位，不再全清。
  - 空态（L28-35）按 `evidence_ids.length === 0` 与"请求后为空"分两条文案；`evidence_ids` 为空时再结合 manifest capabilities.claims 状态区分"尚未抽取（流水线进行中）"与"该断言无关联证据"。
  - 抽屉每条证据在 `VerificationStatus` 旁挂 `<VerdictBadge validation={e.validation} showReasons />`（复用 M2 既有组件，不新造）。
  - `SUPPORT_META`（L61-67）增加 unreviewed 的子文案映射（按 reason code 显示"模型未返回结论（超时/失败）"vs"未配置语义判定"）。

**验收（先红后绿）**

- 新测试 `frontend/tests/evidenceStates.spec.ts`（tsc+node 零依赖框架，与 test:lib 同方式）：
  - 红→绿 1：`allSettled` 后 3 条证据 1 条 500 → 渲染 2 条正常 + 1 条失败占位，`evidence.length === 3`，不出现"暂无证据"。
  - 红→绿 2：`support_status='unreviewed'` 且 reasons 含 `semantic_timeout` → 文案含"超时"；含 `semantic_unavailable` → 文案含"未配置"；两者不混。
  - 红→绿 3：`evidence_ids=[]` + `capabilities.claims=pending` → "正在抽取证据…"；`claims=ready` → "该断言暂无关联证据"。
  - 红→绿 4：抽屉中 VerdictBadge 展开的 reasons 与 `classifyVerdict(validation).reasons` 逐项相等（共用断言）。
- 后端 `pytest`：新增 unreviewed 成因三分的 gate 用例 3 条；全量 900+ 不掉。
- 手工：对 paper 7 打开一条 insufficient 与一条 unreviewed 证据，分别展开确认文案不同源可辨。

**风险与回滚点**：`evidence_records` 加列的迁移失败 → 回滚 = 删除迁移文件，前端对缺 reasons 的旧响应降级为现行为（VerdictBadge 对 null validation 本就不渲染，VerdictBadge.tsx:42）。语义 reason code 前缀改动影响 `test_golden_provenance` 类既有断言 → 先跑全量 pytest 定位，改断言必须写清语义变化（纪律 2）。

---

### M2 证据面板 sticky 跟随滚动（需求 B）

**现状（带证据）**

- 桌面布局：`paper/[slug]/page.tsx:399-402`，`view === 'claim'` 时 `lg:grid-cols-[minmax(0,1fr),360px]`；grid 子项默认 `align-items: stretch`。
- 抽屉容器：`EvidenceDrawer.tsx:126` `hidden h-full w-80 shrink-0 overflow-y-auto ... lg:block`——面板高度被拉成左列行高（很高），内容贴在该超高盒子顶部，页面下滚时内容滚出视野。
- 页头 `sticky top-0 z-30`（page.tsx:340），底部 timeline `sticky bottom-0`（任务书实测，需避让）。
- 选中联动：`selectClaim`（page.tsx:306-315）只换数据，面板若内容超长，切到新 claim 后滚动位置留在原处——"点下面的证据但面板还在上面"的第二成因。

**目标**

桌面 rail 在页面滚动时始终可见；切换到下方 claim 时面板内容回到顶部。移动端抽屉行为不变。

**改法**

- `EvidenceDrawer.tsx:126`：`h-full` → `sticky` 自包含容器：`lg:sticky lg:top-[HEADER_OFFSET] lg:max-h-[calc(100vh-HEADER_OFFSET-TIMELINE_OFFSET)] lg:self-start`（`self-start` 解除 stretch；偏移量用现有 header/timeline 实测高度，定为常量并注释来源）。
- `EvidenceContent` 滚动容器改为面板内部滚动（`overflow-y-auto` 移到内层）。
- 选中联动：`EvidenceDrawer` 内 `useEffect` 监听 `evidence_ids` 变化（`idsKey` 已存在于 L84）→ 内容容器 `scrollTo({top:0})`。
- lg 以下分支（L133-156 移动抽屉）一行不动。

**验收（先红后绿）**

- 组件测试（jsdom 类零依赖断言，或编译期 props 断言 + 手工验证为主——本项以手工验证为主，测试覆盖 className 契约）：
  - `evidenceStates.spec.ts` 增补：桌面分支 className 含 `sticky` 与 `max-h-[calc(100vh`；移动分支不含 `sticky`。
- 手工验证（判据明确）：
  1. paper 7 证据链视图，滚动到列表最底部一条 claim，面板仍完整可见于视口内；
  2. 点击底部 claim 的"查看"，面板内容切换到该 claim 证据且滚动位置回顶；
  3. 页头与底部 timeline 不遮挡面板内容（首条证据完整可见）；
  4. 缩小窗口到 lg 以下，移动抽屉从底部滑出行为不变。

**风险与回滚点**：sticky 偏移量估错 → 被 header 遮挡；回滚 = 恢复 `h-full` 一行。grid `self-start` 影响右列其他内容（当前右列只有抽屉）→ 风险低。

---

### M3 拒答退出：qa/service 四处改造 + mode 取值表 + 置信度口径 + 指标重定义（需求 C 后端）

**现状（带证据）**

- 四处以"无证据"为由走向 `_abstained`（`service.py`）：
  1. 阶段 1.5/2.5 模型不可用兜底：L119-123、L140-144（`_abstained(...).model_copy(update={"text": ABSTAIN_TPL})`）；
  2. 阶段 2.55 检索为空：L149-164（`_abstained(reason="object_absent")` 产 `mode="not_mentioned"`）；
  3. 阶段 2.6 对象缺失直接拒答：L169-177（`_object_absent_from_hits` → `_abstained(reason="object_absent")`，D-65）；
  4. 阶段 3 `not grounded and not sentences`：L187-190。
  另有 `_ensure_readable`（L227-250）在兜底时仍可能写 `mode="abstained"`（L249），`_mode_for`（L1360-1363）对无句子返回 `"abstained"`。
- `_abstained`（L1205-1232）产 `mode="abstained"|"not_mentioned"`、`confidence="Low"`、note=`ABSTAIN_NOTE|NOT_MENTIONED_NOTE`；`_abstain_body`（L1235-1250）+ `_closest_snippet`（L1261-1284）已具备"最接近原文片段，标注未通过证据校验"能力——**正是拍板决策 2 要的形态，已存在，扩用即可**。
- 置信度：`answer_gate.py:173-179 _confidence`：`grounded=False` 一律 Low；`fact_count>=2 且 inference_count==0` → High；其余 Medium。`GateDecision.confidence` 默认 `"Low"`（L37）。
- 契约：`contracts/qa.py:18` `AnswerMode = Literal["generated","extractive","cached","abstained","general","not_mentioned"]`。
- 拒答类指标：`metrics.py:312-329 _is_refusal`（mode ∈ abstained/not_mentioned 或无内容即拒答）、`refusal_metrics`（L332 起）；`METRIC_NAMES`（contracts/evaluation.py:149-165）含 `unanswerable_refusal_rate` 与 `answerable_false_refusal_rate`；前端 `EvalView.tsx:35-36` RATIO_METRICS 两条标签；`evalMetrics.ts:241-255` REASON_TEXT。
- 文档：`docs/ARCHITECTURE.md:125`「无证据支持 → "模型未在论文中找到直接依据"（禁止编造）」。

**目标（按拍板决策 1/2 直接设计）**

1. `mode="abstained"` 从产品语义退出：API 响应不再产生该取值；所有问题都有回答 + 置信度。
2. 低置信回答内容来源优先级：①逐字原文块的抽取式内容（`_extractive_draft/_draft_from_hit/_closest_snippet` 既有能力）；②标注"未使用论文证据"的通用回答。禁止编造；允许附"最接近原文片段"并显式标注未通过证据校验（决策 2）。
3. 置信度三档判据（非感觉），grounded 语义不变（仍=逐句过 Evidence Gate，answer_gate.py 权威）。
4. 指标重定义：`answerable_false_refusal_rate` 删除；`unanswerable_refusal_rate` → `unanswerable_honesty_rate`（口径改为"对真不可答题，系统是否如实说明没有证据"）。

**改法**

- **新 mode 取值表**（contracts/qa.py:18 改为）：
  `generated`（有证据作答，grounded 可 true/false）/ `extractive`（抽取式作答，逐字原文）/ `general`（通用回答，标注未用论文证据）/ `not_mentioned`（论文未提及，如实说明）/ `cached`（缓存命中）/ `unavailable`（模型不可用，如实说明，retryable）。
  - `abstained`：从 `AnswerMode` 删除；DB 历史行不迁移，**读取投影处**（`service.py:_row_to_answer` L1340-1352 附近与 legacy 投影）映射：`abstained` → note 含"没有提到"时 `not_mentioned`，否则 `general`（详见"剩余技术性问题"Q1）。
- **service.py 四处改造**：
  1. L119-123 / L140-144（模型不可用兜底）：改产 `mode="unavailable"`，正文如实说明"模型服务暂不可用"+ 已知信息（若是论文问题且检索有命中，附 `_closest_snippet`），置信度 Low。
  2. L149-164（检索为空）：保持 `not_mentioned`（能抽对象）/ `general`（抽不出）——**这两个 mode 保留**，它们本来就是"有信息的回答"而非拒答；正文中附 `_closest_snippet`（有 hits 时）。
  3. L169-177（对象缺失）：不再走 `_abstained`。改为：`not_mentioned`（对象确认缺席，D-65 判据保留为**确定性证据**，note 点名对象）+ 附 `_closest_snippet(hits)`（标注未通过证据校验，决策 2），confidence=Low，grounded=False。
  4. L187-190（not grounded and not sentences）：不再拒答。改为抽取式兜底：用 hits 产 `_extractive_draft`/`_draft_from_hit` 内容（逐字原文），`mode="extractive"`，note 注明"由原文片段直接组成，未通过整句证据校验"，grounded=False，confidence=Low；hits 为空时回落 `general`。
  - `_abstained`/`_abstain_body` 函数体删除或收敛为 `_unavailable_body`（闲聊不可用兜底）；`_ensure_readable` L249 的 `"abstained"` 改 `"general"`；`_mode_for` L1362 对无句子不再返回 abstained（改由上层显式选 extractive/not_mentioned/general）。
- **置信度三档判据**（answer_gate.py 扩展，`_confidence` 不再只看 grounded）：
  - `High`：grounded=True 且 fact_count≥2 且 inference_count=0（现状保留）。
  - `Medium`：grounded=True 的其余情形；或 mode=extractive 且全部句子逐字来自原文块（quote_spans 全 exact）。
  - `Low`：grounded=False 的其余一切（含 not_mentioned/general/unavailable）。
  - UI 显示：每条回答徽标旁固定显示 `置信度 · High/Medium/Low`（QAView.tsx:355 已有位置），Low 时附 note 解释（不遮羞）。
  - **红线**：grounded 判定逻辑（answer_gate.py:52-131）一字不改——放宽它 = `unsupported_fact_escape_rate` 失守。
- **指标重定义**（metrics.py + contracts/evaluation.py + 前端同步）：
  - 删除 `answerable_false_refusal_rate`：`METRIC_NAMES` 条目、`metrics.refusal_metrics` 返回、`service._compute_entries` L221-223 赋值、`EvalView.tsx:36` 标签、相关测试与验收脚本断言——**同步清单**见下。
  - `unanswerable_refusal_rate` → `unanswerable_honesty_rate`：判据改为"对 golden 不可答题，回答 mode ∈ {not_mentioned, general} 或（mode=extractive 且 grounded=False 且 note 含未通过校验标注）"记命中；`_is_refusal`（L312-329）改写为 `_is_honest_unanswerable`，not_mentioned 仍是"如实"而非"拒答"。
  - 同步清单（漏一处留死格子）：`contracts/evaluation.py:METRIC_NAMES` / `metrics.py:refusal_metrics+_is_refusal` / `evaluation/service.py:_compute_entries` / `EvalView.tsx:RATIO_METRICS`（L35-36 两行改为一条 `unanswerable_honesty_rate 不可答问题如实率`）/ `evalMetrics.ts:REASON_TEXT` / `frontend/tests/evalMetrics.spec.ts` / 后端 refusal 相关 pytest / `scripts/acceptance/verify_metrics_live.py` / `docs/REFACTOR_SPEC.md` 指标表。

**验收（先红后绿）**

- 后端 pytest 新增（先写红）：
  - `test_no_abstained_mode.py`：注入"模型不可用 / 检索为空 / 对象缺失 / gate 全拒"四故障，断言响应 `mode != 'abstained'` 且正文非空；四者 mode 分别为 unavailable / not_mentioned|general / not_mentioned / extractive|general。
  - `test_low_confidence_answer.py`：对象缺失路径回答含"未通过证据校验"标注 + snippet 逐字存在于原文块（纪律 4 断言：snippet 是 hits 文本的子串）。
  - `test_confidence_bands.py`：三档判据各一例（High=grounded 双事实、Medium=extractive 全 exact、Low=general）。
  - `test_honesty_metric.py`：不可答 golden 题得到 not_mentioned → honesty 记 1；得到 grounded 生成答（胡说）→ 记 0；`answerable_false_refusal_rate` 不出现在报告 metrics 里。
  - 既有引用 `abstained` 的测试（grep 全库）按新语义改写——**每条改写注明原语义为什么失效**，不许直接删。
- 全量 pytest ≥ 900 passed；`run_all.py` 5/5（其中 qa_stability 的空答案断言继续为 0/9）。
- 手工：三个默认问题（QAView.tsx:25-29）各问一次，均见回答 + 置信度徽标；「哪里最值得质疑？」见 not_mentioned 或低置信 extractive，而非拒答文案。

**风险与回滚点**：四处分支改动面大（service.py 核心流）。回滚点 = git 单 commit 一个分支改动，回滚即恢复 `_abstained` 调用。风险：抽取式兜底质量差时回答"像摘抄"——用 Medium 封顶 + note 明示控制预期；`_is_refusal` 改写影响历史报告口径 → 新旧指标并存期在 method 文案注明版本（`rl.eval/2` bump EvaluationReport.version，contracts/evaluation.py:130）。

---

### M4 QA 前端：删"无证据→拒绝编造" + 「回答被中断」徽标根治（需求 C 前端）

**现状（带证据）**

- 空态文案：`QAView.tsx:329` `无证据 → 拒绝编造`（任务书要求删）。
- 「回答被中断」徽标唯一来源：`QAView.tsx:347-348`，`m.resp?.mode === 'interrupted'`；该 mode 由 `fallbackPartial()`（L210-240）写入，同时**硬编码** `confidence:'Low'`（L220）、`grounded:false`（L219）。触发条件是 `stream.state==='completed' && !finalEv`（L170）。
- 两个结构性可疑点（任务书指出，代码核实属实）：
  1. `lib/sse.ts:129-135` `parseSSEJson` 解析失败**静默**返回 null；`useQAStream.ts:47-48` `if (!ev) return;` 直接丢帧——final 帧若因任何原因解析失败（如超大 data 被代理截断），客户端永远判"被中断"且**零日志**。
  2. `streamDoneRef`（QAView.tsx:66）一次性锁：任一分支置 true 后，final 迟到到达也不再更新（L96/132/170 均检查 `!streamDoneRef.current`）——解释了用户说的"一直"被中断。
- 另有一处用户误读源：`QAView.tsx:410-411` `!m.resp.grounded` 时显示 `note || '检索到的证据不足以支撑回答，已拒答。'`——abstained 回答（grounded=False, Low）落到这条文案，"已拒答"被用户读成"被中断"。M3 之后 abstained 不再产生，此文案随决策 1 一并清理。
- `useQAStream.ts:58`：`onComplete` 无条件置 completed（即使没有 final）——这是"completed && !finalEv"状态的生产者，语义上它把"流读完"与"拿到结果"混为一谈。

**目标**

1. 删除"无证据 → 拒绝编造"及一切拒答语义文案；新文案表达"每个问题都有回答，回答带置信度"。
2. 「回答被中断」不再以"像正常业务结论"的形态出现：连接层异常就是连接层异常（recovering/failed 文案），不挂 `confidence:'Low'`、不伪装成回答。
3. 消除 final 静默丢失：解析失败必须有日志与计数；流读完但无 final 必须走恢复链而不是一次性锁死。

**改法**

- `QAView.tsx:329` 删除该行，替换为"每个问题都会得到回答；回答附置信度，低置信度会说明原因"（走 richtext 白名单，`check-text-paths.cjs` 白名单同步）。
- `useQAStream.ts`：
  - 丢帧计数：`parseSSEJson` 返回 null 时 `droppedFrames++` 并 `console.warn`（含 frame.data 前 120 字符）；流结束时把 `{gotFinal, droppedFrames}` 一并暴露给调用方。
  - `onComplete` 不再直接置 completed：无 final 时置新状态 `'recovering'`（R3 状态机语义补齐），由 QAView 走恢复链。
- `QAView.tsx`：
  - 删除 `mode:'interrupted'` 整条分支与 L347-348 徽标；"流读完无 final"统一进 `recovering`：先按 `meta.answer_id` 取回（`api.qaAnswer`），失败再 `askFallback`（非流式），再失败显示"连接异常，请重试"（**不挂置信度、不写成回答**）。
  - `streamDoneRef` 一次性锁改为"结果锁"：只有 `completed + final` 或恢复成功才置锁；recovering 期间 final 迟到仍可生效（比较 answer_id 一致才接受）。
  - L410-411 拒答兜底文案删除：`!grounded` 且 note 为空时显示"该回答未通过完整证据校验，置信度较低"（与 M3 置信度口径一致的表述）。
- 复现结论（本轮对代码的判定）：用户实测三条默认问题后端都发了 final（任务书 §2 需求 C），所以"被中断"徽标最可能的成因是 **`streamDoneRef` 锁 + 早期一次失败/无 final 分支留下的永久状态**，或 abstained 回答被 L352+L411 渲染成"无证据支持/已拒答"被误读为中断。本地无法 100% 复现网络层丢帧路径，因此**两处都修**（锁语义 + 丢帧可观测），修复后若线上再现，`droppedFrames` 与审计端点（qa/audit.py:60-91）能直接对账——这正是 M7 审计的设计目的，不需要再猜。

**验收（先红后绿）**

- `frontend/tests/qaStream.spec.ts`（新增，node 跑）：
  - 红→绿 1：mock 帧序列 `[meta, sentence]` 后流结束（无 final）→ 状态为 recovering，发起 `qaAnswer` 取回；取回成功 → completed，消息文本=取回答案，DOM 不含"被中断"、不含"没有生成内容"、不挂 `confidence:'Low'`。
  - 红→绿 2：recovering 期间迟到 final（answer_id 匹配）到达 → 仍以 final 为准完成。
  - 红→绿 3：final 帧 JSON 损坏 → `droppedFrames === 1` 且有 warn；随后走恢复链。
  - 红→绿 4：取回失败 + 非流式兜底成功 → completed（标注"已切换为非流式回答"）。
- 文案断言：QAView 渲染输出全文不含"拒绝编造"、不含"已拒答"、不含"被中断"。
- `node scripts/check-text-paths.cjs` 绿（白名单已同步新文案）；`npm run test:lib` 70+ 项不掉。

**风险与回滚点**：`onComplete` 语义变更影响 useJobEvents 之外只此一处消费（useQAStream.ts:58），面小；回滚 = 恢复 L58 一行 + QAView 分支。recovering 新增状态需 contracts.ts 的 `StreamState` 加值（前端类型，兼容：旧值不删）。

---

### M5 评测全面 AI 化：删除一切人工环节（需求 D，决策 3/4）

**现状（带证据）**

- 人工口径后端：`metrics.py:220-222 compute_overall`（要求四项核心全 measured）、`metrics.py:241-247 core_metric_missing`；`service.py:79-95` 两个口径并存 + `overall_not_evaluated` 告警。
- 人工确认链路：`canonical.py:781-803 POST /golden-set/confirm`（`confirm_for_scope`）、`golden.py:55-71 is_tuning` 字段、`contracts/evaluation.py:118-122 golden_is_tuning`；`canonical.py:763-778` GET golden-set 返回 `is_tuning` 与 `status: "draft（机器构造，待人工确认）"`（L768）。
- 调参集分支：`evaluation/service.py:165-199`（`input.golden_is_tuning` → AI 裁判 / `golden_not_annotated` 告警 / not_evaluated 兜底）。
- 前端人工语义：`EvalView.tsx:118`「综合评分（人工真值口径）」、L137-148「未确认 / NOT CONFIRMED」、L152-166 amber AI 副卡、L171-189 人工提示文案、L230-236「金标集待人工确认 / Golden Set 已确认」徽标；`evalMetrics.ts:27-32 OverallView{human, ai}`；`frontend/tests/evalMetrics.spec.ts:147` `assert.strictEqual(o.human, null, ...)`。
- AI 口径已存在：`metrics.py:230-238 compute_ai_overall`（AI_PROXY_CORE={support_precision}）、`ai_grader.py`（失败返回 None 绝不返回 0，L17/L136-138）。

**目标（按决策 3/4）**

人工线**删除**（不是隐藏）：confirm 端点、compute_overall、core_metric_missing、is_tuning/调参集概念、golden_not_annotated 人工语义、前端全部人工文案与"未确认"态。综合评分改名「AI 质量评分（自动）」直接出值，basis 标 AI。

**改法**

- 后端：
  - `service.py:79-82`：`overall_score = M.compute_ai_overall(report)`，并新增 `overall_score_basis="ai_generated"` 字段（contracts/evaluation.py 的 EvaluationReport，可空默认 None 兼容旧报告）；`ai_overall_score` 字段保留一个版本周期（deprecated，值与 overall_score 相同），下轮删除。`compute_overall`/`core_metric_missing` 函数删除；L84-95 的 `overall_not_evaluated` 告警改写为"AI 口径核心指标缺失"（缺哪几项列哪几项）。
  - `service.py:165-199`：`golden_is_tuning` 分支删除——金标集只有一种形态（AI/builtin 从原文构造），support_precision/recall 一律走 `_ai_judged_support`（已有）出值，status=proxy、method 注明 AI 判等；`golden_not_annotated` 告警删除，替换为 `golden_ai_constructed`（"金标集由 AI 从原文构造，评分为 AI 口径"纯说明性）。
  - `EvaluationInput.golden_is_tuning` 字段删除（contracts/evaluation.py:118-122）；`golden.py:55-71` 的 `is_tuning` 参数与列：ORM 列保留（DB 不删列），读写路径删除（新写入恒 False 或不写）；`confirm_for_scope` 删除。
  - `canonical.py:781-803` confirm 端点删除（路由+handler）；`canonical.py:768` 的 `status` 字段改为 `"ai_constructed"`，`is_tuning` 字段从响应删除（该端点是 admin 运维端点，兼容性风险低；仍在 changelog 注明）。
  - `metrics.py:196-217 _overall` 保留（compute_ai_overall 的底座），docstring 去掉"人工"字样。
  - `run_golden`（service.py:104-111）保留（它现在是"带金标集重算"的入口，不再有确认语义）。
- 前端：
  - `EvalView.tsx`：L118 →「AI 质量评分（自动）」；L137-148 未确认态删除（无值时显示"未评测"）；L152-166 amber 副卡删除；主卡下方一行小字"由 AI 裁判与程序测量自动得出，非人工评审"（来源标注，决策底线 2）；L171-189 提示重写为 AI 口径说明；L230-236 徽标改为"金标集：AI 构造"（`golden_ai_constructed`）。
  - `evalMetrics.ts`：`OverallView{human, ai}` → `{ score: number|null, basis: 'ai_generated'|null }`；`parseOverall` 同步；`evalMetrics.spec.ts:145-149` 用例 8 改写为"单一分数 + basis=ai_generated"（**改写而非删除**，spec.ts:147 的断言换成新语义）。
  - `frontend/lib/api.ts` 里 confirm 的封装（如有）删除；引用它的测试删除。
- **影响面清单（完整）**：
  - 端点：删 `POST /papers/{id}/golden-set/confirm`；改 `GET /papers/{id}/golden-set`（去 is_tuning/status 人工语义）。
  - 响应字段：EvaluationReport 增 `overall_score_basis`；`ai_overall_score` 转 deprecated；GET golden-set 删 `is_tuning`、改 `status`。
  - Warning.code：删 `golden_not_annotated`、`overall_not_evaluated`（人工语义）；增 `golden_ai_constructed`、`ai_overall_not_evaluated`。
  - 函数：删 `compute_overall`、`core_metric_missing`、`confirm_for_scope`、`golden.py is_tuning` 读写。
  - 测试：`test_golden_provenance.py`（5 条，D-50 产物）**按新语义重写**（不许直接删：原"调参集不得出分"语义被决策 3 推翻，新语义为"AI 构造集可出 AI 口径分且标 basis"）；EvalView/evalMetrics 前端 spec 同步；全库 grep `confirm_for_scope|is_tuning|golden_not_annotated|compute_overall|core_metric_missing` 清零（DB 列名除外）。

**验收（先红后绿）**

- 后端：`test_ai_overall_as_primary.py`（新）——金标集 AI 构造 + AI 裁判有结论 → `overall_score` 有值且 `overall_score_basis='ai_generated'`；裁判失败 → `overall_score=null` + `ai_overall_not_evaluated` 告警（**不填 0**，决策底线 1）。重写的 `test_golden_provenance.py`：AI 构造集出分且标 basis；grep 门禁脚本（新增 CI 断言）：上述五个标识符仓库零命中。
- 前端：`evalMetrics.spec.ts` 改写后全绿；EvalView 渲染断言：含「AI 质量评分（自动）」、不含"人工真值"、不含"未确认"、不含 amber 副卡。
- 全量 pytest ≥900、test:lib、hygiene、run_all 5/5。
- 手工：paper 7 评测页主卡直接出分，副卡与"未确认"不再出现。

**风险与回滚点**：这是推翻 D-50 的产品级转向，**必须配 ADR（D-105）**；回滚点 = 单 commit 恢复 confirm 端点与 compute_overall（函数体小，git revert 成本低）。风险：分数失去人工校验背书——缓解 = basis 标注 + 主卡下小字 + `golden_ai_constructed` 徽标三处显式传达，不遮。删除 `golden_is_tuning` 字段是 `extra="forbid"` 的 DTO（contracts/evaluation.py:109）——旧调用方传该字段会 422，需 grep 全部构造点同步删（测试里有多处）。

---

### M6 指标 AI 出值：anchor_region_hit_rate 查明 + support 系统一 AI 口径（需求 E）

**现状（带证据）**

- `anchor_region_hit_rate` 恒不可测：`metrics.py:303-309` 对 `with_iou` 为空返回 not_evaluated；`evaluation/legacy.py:194` 派生 NavigationCheck 时 **`region_iou=None` 硬写**（注释"块没有矩形就不给 IoU（宁缺勿造）"）。NavigationCheck 契约里**没有** expected_rect 字段（contracts/evaluation.py:46-50 只有 anchor_id/page_correct/region_iou/latency_ms；任务书说的 L74 附近的 expected_rect 在 `GoldenAnchor` 上，L74，不在 NavigationCheck）。
- 坐标数据链路：`parse/normalize.py:145-161` 块有 bbox 时写 `raw_ref.bbox_values/bbox_units`（`point|normalized|unknown`，normalize.py:159-160 做了白名单）；`candidate_to_segment`（gate.py:570-590）page_only 时强制 `rect=None, quads=[]`，否则带 `cand.rect/quads`——**cand.rect 的来源未确认**（前言未能确认项 1）。
- support_precision/recall：`metrics.py:253-276` 无金标时 precision=proxy、recall=not_evaluated；有金标时走 `_ai_judged_support`（service.py:173-177，AI 判等）或（M5 之后恒走 AI 判等）。
- D-52 遗留（DECISIONS.md:613）："anchor_region_hit_rate 仍无矩形可判（不编 IoU）"——本条要在实测后更正。

**目标**

1. 先实证后定案：查清 rect/quads/bbox 在真实论文上的覆盖率，决定"真算 IoU（measured）"还是"AI 裁判判区域命中（proxy）"。
2. support_precision/recall 统一 AI 金标 + AI 判等出值，status=proxy、method/basis 标 AI。
3. 产出最终指标清单（见下节表格），每个指标标明 程序算/AI 判、measured/proxy(ai)/not_evaluated(+reason)。

**改法**

- **改法 0（实证先行，不写实现）**：三条核对命令——
  1. SQL 统计：`SELECT count(*) total, count(raw_ref->'bbox_values') with_bbox FROM blocks WHERE revision_id=...`（真实 revision 各跑一篇 mineru 论文与 pymupdf 论文）；
  2. SQL 统计 anchors 的 `segments[*].rect` 非空比例；
  3. 追 `CandidateEvidence(rect=...)` 的构造点（grep `rect=` in evidence/locator.py 与 gate.py）。
  - **若覆盖率可用**（块 bbox 与锚点 rect 同页存在）：真算 IoU。单位对齐在**装配 NavigationCheck 处**（evaluation/legacy.py:191-196）做：统一转 normalized 0-1000（point→normalized 需页宽/高，从 PageORM 取；unknown 一律不算，不产生样本）。expected=引用块矩形并集，actual=锚点 segment.rect。契约：NavigationCheck 增可空 `expected_rect/actual_rect/rect_units`（expand-first）。
  - **若覆盖率不可用**：AI 裁判判区域命中——把"锚点声称的页/区域描述 + 引文实际所在块/页"交给 LLM 判一致（复用 ai_grader 的受控输出模式），status=proxy、method="ai_judged_region_consistency"、reason 文案写明 AI 判定。**不许用 0 或默认值填**。
  - 两条路都要把结论写 ADR（D-107），更正 D-52 遗留与 R3 计划"设计不可测"的结论。
- **support 系**：M5 之后 `_compute_entries` 的 support_precision/recall 恒走 `_ai_judged_support`；`support_metrics`（metrics.py:253-276）的 proxy 兜底保留为"无金标集"时的降级（method 写明 evidence-presence 口径）；recall 在无金标时仍 not_evaluated(reason=no_golden_truth)——**这是真出不了，写进最终清单并说明为什么**。
- 前端：`evalMetrics.ts:185-187 NOT_APPLICABLE_REASONS` 按实证结论更新（若真算/AI 判，`source_pdf_has_no_coordinate_rects` 从"不适用"集合移除或保留为 truly-absent 情形的兜底码）；EvalView.tsx:30 的 `anchor_region_hit_rate` 行按最终形态标注 proxy/AI。

**验收（先红后绿）**

- 实证记录：核对 SQL 输出贴进 ADR D-107（覆盖率数字必须真实跑出，不许编）。
- 后端：`test_anchor_region.py`（新）——构造同页块矩形与锚点 rect（单位一 point 一 normalized）→ IoU 计算单位对齐正确（断言归一化后交并比）；无矩形 → not_evaluated + 正确 reason；AI 裁判路径 mock 判一致 → proxy 值 + method 含 ai_judged。
- `test_support_ai_basis.py`：support_precision 出值时 status=proxy 且 method 含 AI 判等说明；AI 裁判 None → not_evaluated（不填 0）。
- 全量 pytest、run_all 的 verify_metrics_live 更新断言后 5/5。

**风险与回滚点**：单位对齐做错 = IoU 全错——缓解 = 对齐函数独立纯函数 + 单测覆盖三种单位组合；回滚 = 恢复 `region_iou=None` 一行（legacy.py:194）。AI 裁判路径增加一次 LLM 调用/篇——挂 digest 缓存（ai_grader.py:97-105 既有模式）。

---

### M7 成果页自己长出来：manifest.capabilities 驱动的可观测导入（需求 F + 欠账 3）

**现状（带证据，四条独立缺陷已逐条核实）**

1. `usePaperWorkspace.ts:44-45`：`const rev = m.revision?.id; if (!rev) return;`——无 revision 时 exhibits 永停 `{status:'idle', data:null}`，不重试。
2. `paper/[slug]/page.tsx:259-264`：实时模式条件 `exhibits && canonicalClaims.length===0 && source_mode==='upload'`——`exhibits` 是 `.data` 恒 null → processing 永不置真 → L266-284 的 40×2.5s 轮询不启动。
3. `upload/page.tsx:66` 与 `:84`：`goToPaper(up.paper_id)` 未传 jobId（`goToPaper` 定义 L52-54 支持 jobId 参数，调用方没用）；后端 upload 响应确有 job_id（`canonical.py:437` 注释实测 `{paper_id, job_id, status:"running"}`）→ `page.tsx:287 useJobEvents({job_id: 0})` 永不连接（useJobEvents.ts:32 对 job_id<=0 直接 idle）。
4. 进度真相闲置：`GET /manifest` 已返回 `capabilities[{name,state,reason}]` 与 `active_job`（canonical.py:89-132、191-214；contracts.ts:986、1014-1015），前端全仓库无组件消费（仅 fixtures/contracts 提到）。
5. 欠账 3（stage_started 去重）：`pipeline/service.py:127` 与 `:216` 两处 `_emit("stage_started")`，幂等靠 `job_stage_keys(revision_id+stage+input_digest+algorithm_version)`（repository.py:9、425-478）——真实导入是否重复只有单测覆盖，未现场核对。

**目标**

从上传/点处理到成果出现的端到端可观测：分域进度可见、就绪自动切换、终态各有界面、无需手动刷新。

**改法**

- **唯一进度真相** = `manifest.capabilities + manifest.active_job`：
  - 新增 `usePaperProgress(paper_id, job_id?)`：以 manifest 轮询为底座（job 活跃时 2s、空闲时停；指数退避 1s→2s→5s 封顶，总时长 8 分钟上限——导入预算 6 分钟 + 余量），有 job_id 时叠加 useJobEvents SSE 做阶段细粒度（JobProgress 复用）。
  - `usePaperWorkspace.ts:44-45`：`!rev` 时不再 return 后静止——把 exhibits 置为 `{status:'pending'}` 并触发下一轮 manifest 轮询（由 usePaperProgress 驱动）；revision 出现后自动取 exhibits，`LoadState` 增 `'pending'` 值（前端类型，兼容）。
  - `page.tsx:259-264` 实时模式条件改写：`processing = manifest?.active_job != null || capabilities 存在 pending`——不再依赖 exhibits 非空。L266-284 写死 40×2.5s 删除，轮询归并到 usePaperProgress。
  - `upload/page.tsx:66/84`：`goToPaper(up.paper_id, up.job_id)`；**900ms setTimeout 删除**——拿到响应立即跳转（响应里 job_id 已有，无需等待），上传页 stage 文案改为"已创建任务，正在跳转…"。
- **未就绪界面**：导入中视图 = 分域进度条（解析/媒体/断言/证据/图谱/讲解/评测，来自 capabilities 的 name 映射）+ 每个 pending 的 reason（capabilities 的 reason 字段，如"尚未解析"）+ JobProgress 阶段条（有 job 事件时）。替代现在的"一片空白"。
- **终态**：
  - `unavailable`（如 paper 8 的 pdf=unavailable reason="无源文件"，canonical.py:93）：整页错误卡 = "该论文没有可用源文件" + 各域 reason 列表 + "重新上传"入口（不是空白）。
  - 失败（job failed）：错误卡 + failed 阶段与 message + "重试"（调 `/jobs/{id}/retry`，canonical.py:549-552 已存在）。
  - 超时（轮询超 8 分钟仍 pending）：提示"处理时间超出预期" + 保留后台轮询降频继续 + 手动刷新按钮。
- **现场核对 stage_started（欠账 3）**：合并进本模块验收——真实导入一篇新论文后查 `SELECT type, data->>'stage', count(*) FROM job_events WHERE job_id=? GROUP BY 1,2`，判据：每个 stage 的 stage_started 恰 1 条；同时看 JobProgress 无重复阶段闪烁。若重复：修 service.py:127/216 的双发（补发前查 job_events 是否已有该 stage 的 started）。

**验收（先红后绿）**

- 前端 `paperProgress.spec.ts`（新）：
  - 红→绿 1：manifest 无 revision + active_job 存在 → exhibits 状态 pending 且轮询继续；第二轮 manifest 带 revision → 自动加载 exhibits 转 ready（无需手动刷新）。
  - 红→绿 2：capabilities 含 pending → processing=true；全 ready → processing=false 且内容渲染。
  - 红→绿 3：pdf=unavailable → 渲染"无源文件"终态卡（断言含 reason 文案）。
  - 红→绿 4：upload 跳转 URL 含 `job_id=`（断言 goToPaper 调用参数）。
- 新验收脚本 `scripts/acceptance/verify_upload_progress.py`（进 run_all.py，退出码约定 0/1/2 不变）：上传 fixture PDF（或复用已导入 paper 的重建）→ 轮询 manifest 断言 capabilities 从 pending 渐进到 ready → 断言 active_job 出现与消失 → 断言全程无 5xx。环境不可达 → 退出码 2 + 明确报错。
- 现场核对：上面 SQL 输出贴 ADR/验收记录；stage_started 每阶段恰 1。
- 全量：pytest ≥900、test:lib、run_all 6/6（含新脚本）。

**风险与回滚点**：轮询风暴——缓解 = 退避+上限+页面隐藏时暂停（visibilitychange）；回滚 = 恢复 usePaperWorkspace L44-45 与 page.tsx 轮询段（两处均单 commit）。`LoadState` 加 `'pending'` 需 grep 消费点补分支（否则 pending 被当 idle 渲染空白——那正是本模块要消灭的现象，必须全grep）。

---

### M8 M10 物理迁移 projection（欠账 1）

**现状（带证据）**

- D-101（DECISIONS.md:1946-1959）：四域收敛状态 = graph 权威在 `modules/graph/legacy`（adapters 委托）、evaluation 权威在 `schemas/adapters`（modules 委托）、qa 权威在 `schemas/adapters`（modules 早已委托）、scene 权威在 `modules/scene/legacy`（adapters 委托）——**逻辑唯一实现 + 薄委托门禁**（D-102，`test_projection_thin_delegation.py` ≤45 行 + 有转发调用）。
- 未做：物理迁移到 `app/projection/` 包、adapters 改 re-export、白名单收窄（D-101 L1955-1959、D-102 L1975-1976 明确登记）。

**目标**

完成纯机械迁移：`app/projection/` 成为四域唯一实现的家；`schemas/adapters.py` 与两处 modules 权威实现改为 re-export/薄委托；静态门禁白名单收窄到只允许 `app/projection/`。

**改法**

1. 迁移：把四份权威实现（`modules/graph/legacy.to_legacy_graph`、`schemas/adapters.to_legacy_evaluation/to_legacy_answer`、`modules/scene/legacy.to_legacy_presentation` 及各自私有辅助）原样搬入 `app/projection/{graph,evaluation,qa,scene}.py`；claims 域（D-93 已收敛的形态）核实后一并归位。
2. 原位置改薄委托（≤45 行 + 转发调用，满足 D-102 门禁的既有断言形态）；`schemas/adapters.py` 收敛为 re-export + DeprecationWarning。
3. 白名单收窄：静态门禁从"允许 modules/graph|scene/legacy + schemas/adapters"收窄为"只允许 app/projection"；`test_projection_thin_delegation.py` 的已知委托方清单同步更新（D-102 教训：清单写错门禁会红，先核对再改）。
4. `projection/CONTRACT.md` 更新：权威侧全部同包，删除"为什么权威侧不在同一个包里"的解释段。
5. 900 测试保障：迁移前后各跑一次全量 pytest；双读一致性测试（五域逐字段 deep equal）必须在迁移后原样全绿——它们是防搬丢字段的网。

**验收（先红后绿）**

- 白名单收窄后门禁先红（旧位置还有实现）→ 迁移完成转绿。
- 双读一致性五域全绿；全量 pytest ≥900；run_all 5/5（迁移不动行为）。

**风险与回滚点**：纯机械但动 9+ 函数与多处导入——按域分 4 个 commit（graph/evaluation/qa/scene），每个 commit 后跑全量；回滚 = 逐 commit revert。风险：私有辅助函数被原模块其他代码引用（如 `_navigation_checks` 之类）——迁移前 grep 每个待搬符号的引用点，只搬投影本体。

---

### M9 图谱节点 reasons 接线（欠账 2）

**现状（带证据）**

- 图谱节点投影只带 `support_status`：`modules/graph/service.py:504` `"support_status": (row.support_status or "")`；repository.py:206/221 同样只有 support_status——VerdictBadge 需要的 `validation{decision, semantic_status, reasons}` 三件套不在节点 props 里，M2 徽标接不上 GraphView。
- 前科：to_legacy_graph 白名单曾丢 `props.support_status`（任务书 §3 欠账 2 描述）——本次加字段必须同步改**唯一实现**（M8 之后是 `app/projection/graph.py`）+ CONTRACT.md 清单 + 双读测试，否则就是又一次"投影丢字段"。

**目标**

图谱证据节点 props 带 `validation{decision, semantic_status, reasons}`，GraphView 节点挂 VerdictBadge。

**改法**

- 后端：`graph/service.py:504` 节点装配处从 validations 表带出三件套（按 statement 关联，JOIN 或批量查，避免 N+1）；legacy 投影唯一实现同步加字段（新增字段可选，兼容）；CONTRACT.md 字段清单更新。
- 前端：GraphView 证据类节点渲染 `<VerdictBadge validation={node.props.validation} showReasons />`（compact 模式，不破坏布局；graphLayout.ts 节点高度对带徽标节点 +24px 或在节点 tooltip 内展示——实现时取不影响布局断言的方案）。

**验收（先红后绿）**

- 后端：双读一致性测试加 `props.validation` 字段比对；图谱端点响应含三件套（无 validations 的节点为 null，前端不渲染徽标）。
- 前端：graph 测试（test:lib graph 9 项）增节点徽标用例；布局断言（包围盒不相交）继续全绿。
- 手工：paper 7 图谱上点开一条 non_claim 节点，徽标显示"非研究发现"。

**风险与回滚点**：N+1 查询——批量预取 validations；回滚 = 撤字段（可选字段，前端对 null 不渲染，天然兼容）。

---

### M10 验收套件扩充（需求 F 验收 + run_all 门禁）

**现状（带证据）**：`scripts/acceptance/` 5 脚本 + run_all.py（退出码 0/1/2 约定），D-103 实测 5/5。

**目标**：新增 `verify_upload_progress.py`（M7 配套）与 `verify_qa_modes.py`（M3/M4 配套：三默认问题 mode ∈ 新取值表、无 abstained、正文非空、置信度在场）；run_all.py 汇总 7 脚本；退出码约定不变（0 通过 / 1 断言失败 / 2 环境不可用）。

**改法/验收**：两脚本遵循既有机读 JSON 行格式；健康检查失败退出码 2 且不产生假 pass。先红后绿：M3 未实施前 `verify_qa_modes` 对 abstained 路径红，实施后绿。全量 run_all 7/7 作为本轮交付门禁。

**风险**：upload 类脚本依赖真实 MinerU 云调用，CI 无凭据时需降级——用已导入 paper 的 `/rebuild-derived` 路径替代真实上传（在脚本 README 注明两档跑法）。

---

## 指标最终清单（需求 E 要求的表）

| 指标 | 出值方式 | 状态 | basis/口径 | 备注 |
|---|---|---|---|---|
| source_asset_coverage | 程序算 | measured | — | 不变 |
| anchor_page_accuracy | 程序算 | measured | — | 不变（legacy.py:191-196 交叉校验） |
| anchor_region_hit_rate | 程序算 IoU（单位对齐）**或** AI 裁判 | measured **或** proxy | ai_judged（若走裁判） | M6 实证定案，D-107 更正"不可测"结论 |
| quote_exact_rate | 程序算 | measured | — | 不变 |
| support_precision | AI 金标 + AI 判等 | proxy | ai_generated | M5 后恒走 `_ai_judged_support`；无金标时降级 evidence-presence 口径 proxy |
| support_recall | AI 金标 + AI 判等 | proxy | ai_generated | 无金标时仍 not_evaluated(no_golden_truth)——**真出不了，如实保留** |
| unsupported_fact_escape_rate | 程序算 | proxy | — | 不变（method 已注明口径） |
| ~~unanswerable_refusal_rate~~ → **unanswerable_honesty_rate** | 程序算 | measured | — | 口径改为"不可答题如实说明率"（M3） |
| ~~answerable_false_refusal_rate~~ | **删除** | — | — | 行为已不存在（决策 1），同步清单见 M3 |
| qa_first_verified_ms | 程序算（usage.elapsed_ms） | measured | — | 不变 |
| qa_total_ms | 程序算 | measured | — | 不变 |
| ingest_ms | 程序算（jobs 表） | measured | — | 不变 |
| input_tokens / output_tokens | 程序算（usage） | measured | — | 不变 |
| recovery_success_rate | 程序算（按答案粒度） | measured | — | 不变 |
| **overall_score** | AI 口径公式（compute_ai_overall） | measured/proxy 混合 | **ai_generated（新字段 overall_score_basis）** | 主分「AI 质量评分（自动）」；核心指标缺失时 null + `ai_overall_not_evaluated` 告警，**不填 0** |

仍然出不了值的（如实告知）：`support_recall` 在无金标集时（no_golden_truth）；任何指标在 AI 裁判调用失败时（不填 0、不编造，标 not_evaluated+reason）。

---

## 剩余的技术性问题（实现层取舍，每条给建议+理由+不选的代价）

**Q1：DB 历史行里 `mode='abstained'` 怎么迁移？**
建议：**DB 不动**，在读取投影处（`_row_to_answer` service.py:1340-1352 与 legacy 投影唯一实现）做映射——note 含"没有提到"→ `not_mentioned`，否则 → `general`，并在 method/warnings 留 `legacy_mode_mapped` 痕迹。理由：答案缓存 key 含 question+snapshot+source_digest（service.py:97-102），UPDATE 改行不影响缓存一致性，但投影映射零迁移风险、可灰度。不选 UPDATE 迁移的代价：历史行的 note 文案仍是旧拒答腔（"已按 Evidence Gate 拒绝进入事实层"），直到该题被重新问（缓存自然换新）——可接受，因为新问不再产生该文案。

**Q2：`AnswerMode` 里直接删 `abstained`，还是保留为死值？**
建议：**contracts 删除**（contracts/qa.py:18），ORM 列不动；Pydantic 反序列化旧行时靠 Q1 的映射先转再构 AnswerRecord，旧值永远不进 API 响应。理由：Literal 里留着 = 类型系统继续允许新代码产出它，决策 1 要求"前端永远见不到"。不选的代价：若某条漏网路径把旧值直接透出，API 校验会 500 而非静默——这其实是想要的失败方式（fail loud），配 grep 门禁 `"abstained"` 在 contracts/前端 zero-hit。

**Q3：`unanswerable_honesty_rate` 改名期，旧报告里的 `unanswerable_refusal_rate` 条目怎么办？**
建议：报告重算时只产新名；**读取端**（evalMetrics.ts）对旧名做一次别名映射（旧名→新名，标 `method` 注明旧口径），不迁移历史报告行。理由：历史报告是时间点快照，改它等于改历史。不选的代价：新旧两篇论文并排时一个显示旧名一个显示新名——可接受，别名映射让 UI 标签统一。

**Q4：rect 单位对齐放在哪一层？**
建议：放在**装配 NavigationCheck 处**（evaluation/legacy.py:191-196 附近），单独纯函数 `normalize_rect(rect, units, page_size) -> normalized_0_1000`。理由：parse 层保留原始单位是事实（不该改），锚点层（candidate_to_segment）也不知道页尺寸；装配处两层数据都有，是唯一能把单位对齐做对的地方。不选的代价：在对齐前任何地方算 IoU 都会把 MinerU 的 0-1000 和 PyMuPDF 的 point 直接相减——必错。

**Q5：upload 的 900ms setTimeout 直接删？**
建议：删，立即跳转（响应已含 job_id，canonical.py:437 实证）。理由：等待没有任何作用（不等 job 建完，只是人为延迟）。不选的代价：无——跳转后目标页本来就要处理"job 刚开始"的 pending 态（M7 的目的）。

**Q6：`ai_overall_score` 字段保留一个版本还是立即删？**
建议：保留一个版本周期（deprecated，值=overall_score），前端 M5 同步改读 overall_score+overall_score_basis，下轮删字段。理由：`/exhibits` 持久化报告与 `/evaluation` 现算两路都有该字段的消费（evalMetrics.ts:169-182），立即删会在过渡期留下 unparsable。不选的代价：多带一个 deprecated 字段一轮——可忽略。

---

## 实施顺序

```
W1（产品语义核心，必须先做）
  M3 拒答退出 + 指标重定义 ──┬─→ M4 QA 前端（依赖 M3 的 mode 表与文案）
                            └─→ M5 评测 AI 化（与 M3 并行；两者在 metrics.py/service.py
                                有文件级交集 → 同一执行者串行改，或分 ownership 后合并）
W2（可并行）
  M1 证据三态（独立）｜ M2 sticky（独立、小）｜ M6 指标出值（依赖 M5 的 basis 字段 → 排在 M5 后）
W3（可观测与收敛）
  M7 成果页（独立）＋ M9 图谱 reasons（依赖 M8 则排在 M8 后；也可先做 service.py:504 再随 M8 迁移）
  M8 projection 物理迁移（行为不变，任何时候可做；建议放在功能改动之后，避免迁移与改字段交织）
W4（门禁收口）
  M10 验收套件扩充（依赖 M3/M4/M7 落地）→ run_all 7/7 + 全量 pytest + ADR 落笔
```

| 模块 | 预估改动面（文件 / 测试） |
|---|---|
| M1 | 后端 2 + 前端 2 / pytest +4、lib +4 |
| M2 | 前端 2 / lib +2、手工为主 |
| M3 | 后端 5 + 前端 3 + 契约 2 + 文档 2 / pytest +12、改写既有 ~8 |
| M4 | 前端 4 / lib +6 |
| M5 | 后端 6 + 前端 4 + 契约 1 / pytest 重写 5 + 新增 4、lib 改写 3 |
| M6 | 后端 4 + 前端 2 / pytest +6 |
| M7 | 前端 5 + 验收脚本 1 / lib +5、acceptance +1 |
| M8 | 后端 ~10（4 commit）/ 门禁改写 2 |
| M9 | 后端 2 + 前端 2 / pytest +2、lib +1 |
| M10 | 验收脚本 2 / acceptance +2 |

## ADR 清单（D-104 起，每条一句话结论）

- **D-104 产品决策：拒答退出产品语义，置信度表达可靠程度**——推翻 D-65 的"对象缺失直接拒答"用法（判据保留为 not_mentioned 的确定性证据）、改写 ARCHITECTURE.md:125 的"禁止编造 → 未找到依据"表述；保留 grounded 语义、引文逐字、低置信标注三条纪律。
- **D-105 产品决策：取消人工真值维度，自动评测全面 AI 化**——推翻 D-50（机器构造集不得当真值/需人工确认）；理由 = 真实约束（没有人工标注资源，人工确认永远不发生，分数永远 null）；保留 = not_evaluated≠0、AI 来源标注（overall_score_basis）、引文逐字可追溯；代价 = 分数失去人工校验背书，UI 三处显式标注（主卡名「AI 质量评分（自动）」+ 小字 + golden_ai_constructed 徽标）传达。
- **D-106 拒答类指标重定义**——answerable_false_refusal_rate 删除；unanswerable_refusal_rate 更名 unanswerable_honesty_rate（口径 = 不可答题如实说明率）；附完整同步清单（M3）。
- **D-107 anchor_region_hit_rate 口径更正**——推翻 D-52 遗留与 R3-M9 的"设计上不可测"结论：以实测覆盖率（SQL 数字）定案为 真算 IoU（单位对齐） 或 AI 裁判 proxy(ai_judged)；source_pdf_has_no_coordinate_rects 的语义随之收窄。
- **D-108 成果页可观测：manifest.capabilities + active_job 为唯一进度真相**——废除"exhibits 非空"间接信号与写死 40×2.5s 轮询；三终态（unavailable/失败/超时）各有界面。
- **D-109 M10 收口：projection 物理迁移完成**——四域唯一实现入住 app/projection/，白名单收窄，薄委托门禁与双读一致性继续生效（承接 D-101/D-102 登记的待办）。
