# recon/OSS_DEEP_DIVE — 开源权威项目深度阅读报告

> 目的：在重写 Spec 前，深入读懂三份开源权威项目的**业务、架构、模块划分、数据流、评价体系**，
> 抽象出可复用的设计模式，作为 ResearchLens 重构的「架构教材」。只取思想，不贴代码。

---

## 1. showlab/Paper2Video（NUS Show Lab）

仓库：https://github.com/showlab/Paper2Video （MIT） · NeurIPS'25 SEA Workshop

### 1.1 业务定位
- **PaperTalker**：把一篇论文 + 一张人像图 + 一段音频，自动生成**学术演讲视频**。
- **Paper2Video**：一套**评测基准**，衡量演讲视频质量。

### 1.2 模块划分（src/ 目录即模块化）
每个文件 = 一个边界清晰的子模块，流水线串联：

```
pipeline.py / pipeline_light.py      # 编排器（含/不含 talking-head）
  ├── slide_code_gen_select_improvement.py   # 幻灯片（LaTeX/代码）生成
  ├── subtitle_cursor_prompt_gen.py          # 字幕 + 光标 提示生成（多模态 agent）
  ├── subtitle_render.py                     # 字幕渲染
  ├── cursor_gen.py / cursor_render.py       # 光标生成/渲染
  ├── speech_gen.py                          # 语音合成
  └── talking_gen.py                         # 数字人头像生成（hallo2）
```

**抽象出的可复用模式**：
- **「一模块一职责」**：Slides / Subtitles / Speech / Cursor / TalkingHead 各自独立，可单独运行。
- **结构化提示生成**：每个生成模块读 `prompts/` 下的任务提示文件，把论文+页面图喂给 LLM/VLM，返回结构化内容（字幕、光标轨迹）。见 `subtitle_cursor_prompt_gen.py`：读 prompt 文件 → 收集 slide 图 → 多模态 agent → 返回 subtitle + usage。
- **light 版 vs 完整版**：`pipeline_light.py` 去掉数字人头像，保留字幕+语音（正是 Spec §13 的「Presenter 可降级」思想）。
- **编排器注入配置**：LLM 名、VLM 名、GPU 列表、阶段开关、输出目录。

### 1.3 评价体系（src/evaluation/）
```
MetasSim_audio.py      # 元相似度（音频层面）
MetasSim_content.py    # 元相似度（内容层面）
PresentArena.py        # 双盲竞技（LLM 擂台比较）
PresentQuiz/           # 依据论文出题 → 用 LLM 作答判分（grounded QA 评测）
IPMemory/              # 知识产权/记忆留存
```
**双维度口径**：
- 面向**观众**：能否忠实传达论文核心思想、是否对多样受众友好（faithful + accessible）。
- 面向**作者**：是否凸显原创贡献与身份、是否提升可见度（contribution + visibility）。

> **对本项目的启发**：评测不只算「准确率」，而应按「观众/作者」双维度；PresentQuiz（出题→答疑→判分）与我们的 **Grounded Q&A + Answer Grounding 指标**高度同构；PresentArena 启发「对比评测」。

---

## 2. Gen-Verse/Paper2Video（Preacher，ICCV 2025）

仓库：https://github.com/Gen-Verse/Paper2Video

### 2.1 业务定位
把论文 PDF 自动转成**视频摘要**，采用类似人类做摘要的**自顶向下分层规划**。

### 2.2 流程（四阶段，多智能体）
```
High-Level Planning   # LLM 读 PDF，决定要做哪些「场景」
  ↓
Low-Level Planning    # 细粒度规划每个视频片段，降低误差
  ↓
Video Generation      # 调用 Manim / Wanx / Tavus / Qwen-tts 等工具生成
  ↓
Evaluation            # evaluator 智能体评估每阶段输出，不合格则调度重生成
```
三种智能体角色：`plan_by`（规划）/ `eval_by`（评审）/ `art_work`（创作）。

### 2.3 输出布局（每次运行）
```
output/(PDFNAME)/
├─ logs/         workflow.log · highplan.txt · llm_qa.md · final_video.mp4
├─ scene_0/      audio.wav · video.mp4
└─ scene_1/      audio.wav · video.mp4
```

### 2.4 评价体系
GPT-4 打 1~5 分：
```
Accuracy          内容正确性、无错误
Professionalism   领域专业知识运用
Aesthetic Quality 视觉吸引力、设计与呈现
Alignment         与论文的语义一致
```
外加 CLIP（prompt 一致性）+ Aesthetic Score（美学）。

> **对本项目的启发**：**分层规划**（高层场景 → 低层细节）正是我们的「Scene/分镜」模型；
> 每场景自包含产出 = 我们的 scene 单元；`eval_by` 智能体 = 我们的自动评测（打分数值化）。
> 用 Docling 解析 PDF、用 Manim 做专业图 —— 我们可用程序化 SVG 渲染替代（对 Spec 更契合，零 GPU）。

---

## 3. langgenius/dify

仓库：https://github.com/langgenius/dify （Dify Open Source License，基于 Apache-2.0 + 附加条款）

### 3.1 业务定位
LLM 应用开发平台：从原型到生产，可视化。

### 3.2 模块化能力（每条皆可独立 + 皆提供 API）
```
Workflow       可视化画布搭建 AI 工作流
Model          数百模型/供应商，含任意 OpenAI 兼容，模型治理/多供应商
Prompt IDE     提示词工程、模型对比（可加 TTS 到聊天应用）
RAG Pipeline   文档摄取→检索（PDF/PPT 文本抽取开箱即用）
Agent          Function Calling / ReAct 定义智能体 + 50+ 内建工具（搜索、绘图等）
LLMOps         日志、指标、追踪（接入 Opik / Langfuse / Phoenix）
BaaS           一切能力都暴露为 REST API，可嵌入自有业务
```

> **对本项目的启发**：**规范化「能力即模块、模块即 API」**；模型治理（多供应商/降级）；
> RAG 摄取→检索；**可观测**（我们能落地成「任务追踪 + 每模块状态 + 指标」）；
> 前端参考其「Workflow 可视化」的把内容/阶段可视化呈现的质感。

---

## 4. 综合抽象：ResearchLens 重构应吸收的设计模式

1. **模块正交、单一职责、可独立运行**：按业务域切分（解析/结构/断言/证据/图谱/场景/问答/评测/视觉），
   每个模块有自己的数据模型 + API + UI + 评价口径（参考 Paper2Video 子模块 + Dify 模块化）。
2. **自顶向下分层规划**：高层场景 → 低层细节；每场景自包含（参考 Preacher）。
3. **结构化提示生成**：LLM/VLM 只产出结构化中间表示（参考 Paper2Video 的提示文件 + 多模态 agent）。
4. **Evidence-first + Grounded Q&A + 自动评测**：断言必须带证据；问答出题→判分（参考 PresentQuiz）；
   评测按「观众/作者」双维度 + 分项打 1~5 + 关键指标（参考 Paper2Video + Preacher + 现有 ResearchLens Eval）。
5. **视觉程序化渲染**：图表/SVG 用代码渲染，零 GPU、零版权风险（参考 Preacher 用 Docling/Manim 的专业图，但我们用 SVG/Canvas）。
6. **降级策略**：完整链路 -> light 链路（去数字人头像，保留字幕+语音）——参考 `pipeline_light.py` 与 RAG 的 graceful degradation。

> 结论：把 ResearchLens 重构为「**模块化流水线 + 厚实数据 + 高信息密度交互**」，
> 每个模块对齐上述一个参考项目的精髓，但只复用「架构与思想」，代码全自研（保持原创、规避开源 License 边界）。
