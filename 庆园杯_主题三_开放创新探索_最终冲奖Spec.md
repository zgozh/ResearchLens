# 第二届“庆园杯”人工智能创新应用大赛
# 主题三：开放创新探索——最终冲奖项目 Spec v4.0
# 项目名称：AI 科研视界 ResearchLens
# 中文副标题：让一篇论文从“文档”变成“可验证、可演示、可交互的科研成果”
# 编码：UTF-8

> 本 Spec 是面向正式参赛作品的“施工总图”，不是概念方案。
> 核心目标：在主题三的自由度下，做一个同时具备“前沿 AI 技术含量、强视觉表现、明确真实场景价值、可量化验证、现场稳定演示”的作品。
>
> 重要限制：不承诺一等奖，也不把“AI 自主发挥”当卖点。方案通过“资料约束 + 结构化中间表示 + 模板化渲染 + 预生成演示 + 外部 API + Docker”控制随机性。

---

# 0. 先回答：为什么最终不再做 AI 世界生成器

## 0.1 对第一届的重新观察

2025 年首届官方决赛共有 10 支队伍，最终 1 项一等奖、3 项二等奖、6 项三等奖。官方赛后新闻点名的优秀作品覆盖手语无障碍、药物递送材料设计、无人机河湖治理、NO₂ 预测、芯片设计、教学、学习助手、网络安全等真实问题。官方报道同时强调把 AI 创意转化为产品、技术转化为服务，以及“懂技术、懂场景、懂需求”和成果转化。citeturn949293search0turn949293search1

第一届一等奖《灵眸智译》尤其值得作为 benchmark：它不是“大模型套壳”，而是硬件 + CV + 可量化识别效果 + 明确民生对象 + 可现场展示的完整系统。citeturn949293search0

## 0.2 对第二届主题三的判断

第二届主题三官方要求并没有规定必须做 Agent，而是允许选择开发平台或开发工具，发布智能体或可执行程序；题目明确鼓励多模态、生成式 AI、智能决策、数字人等方向，并要求非智能体应用同步提交源代码、素材和可执行程序。fileciteturn1file6L369-L371

因此真正有竞争力的路线应该是：

```text
前沿技术
+
真实痛点
+
可验证产出
+
强视觉演示
+
低现场风险
```

## 0.3 最终放弃的路线

不做：

```text
随机图片 → AI 自由理解 → AI 编故事
```

不做：

```text
一句话 → 多 Agent 辩论 → 输出长报告
```

不做：

```text
一句 Prompt → 现场生成整个 3D 世界
```

原因：上述方案都把比赛最重要的 5 分钟展示押在模型随机输出上，而第一届的优胜案例证明“能解决问题、能证明效果、能落地”的作品更有竞争基础。citeturn949293search0

---

# 1. 最终项目：ResearchLens AI 科研视界

## 1.1 一句话

> **把一篇科研论文自动转换成“证据驱动的可交互科研展项”：论文结构 → 核心方法 → 实验结果 → 证据链 → 动画化讲解 → 可点击研究图谱 → AI 问答。**

## 1.2 为什么这个项目适合主题三

它同时覆盖：

- 多模态 AI：论文正文 + 图表 + 公式 + 图片；
- 生成式 AI：自动生成讲解、分镜、可视化说明；
- 智能决策/推理：自动识别研究结论与证据对应关系；
- 数字人：可选科研讲解员；
- 交互式 Web：论文不再只是 PDF，而是可操作的科研体验。

更重要的是，它不是为了“玩具世界”造世界，而是解决一个明确问题：**科研成果复杂、学生/教师难快速理解、论文图表难快速讲解、成果展示依赖人工制作。**

---

# 2. 最强 Demo 场景

不要比赛现场上传随机论文。

准备 3 篇高质量、授权明确的公开论文：

```text
Demo A：人工智能 / 视觉
Demo B：网络空间安全
Demo C：校园 / 教育 / AI
```

优先采用你所在专业能讲清楚的内容。

## 2.1 演示开场

屏幕中央只有一个入口：

```text
DROP A PAPER

把论文交给 ResearchLens
```

然后选择：

```text
《某某论文》
```

## 2.2 15 秒后出现

```text
Paper Map

Problem
Method
Dataset
Experiment
Result
Limitation
```

## 2.3 点击 Method

论文图中算法流程自动动画化：

```text
Input
 ↓
Backbone
 ↓
Feature Extraction
 ↓
Attention / Module
 ↓
Prediction
```

## 2.4 点击某个实验结果

出现：

```text
Claim
“方法 A 在数据集 B 上达到 X%”

Evidence
Table 2 · Page 6

Original figure
[论文原图]
```

## 2.5 点击“AI 讲解”

科研数字讲解员出现，按证据讲解，而不是自由编故事。

## 2.6 最后问

```text
“这篇论文最大的局限是什么？”
```

系统必须回答：

```text
基于论文第 8 页 Discussion：……
```

并展示引用位置。

这个 Demo 比“让 AI 随便造世界”更稳，因为内容来源始终被论文和证据链约束。

---

# 3. 核心创新：Evidence-first Generation

本项目的核心技术不是“生成一段文章”，而是：

```text
Paper
 ↓
Structure Extraction
 ↓
Claim Extraction
 ↓
Evidence Linking
 ↓
Research Graph
 ↓
Presentation Spec
 ↓
Visual Rendering
 ↓
Narration / Digital Guide
```

### 关键规则

任何 AI 生成内容都必须绑定：

```text
claim_id
source_page
source_region
source_text
confidence
```

没有证据：

```text
不能作为“事实”展示
```

只能标记：

```text
“AI 解释 / 推断”
```

---

# 4. 技术架构

```text
                     ┌─────────────┐
                     │ Paper / PDF │
                     └──────┬──────┘
                            ↓
                  ┌──────────────────┐
                  │ Multimodal Parser│
                  └────────┬─────────┘
                           ↓
                  Paper Structure
                           ↓
                  Claim / Evidence
                           ↓
              ┌────────────┴────────────┐
              ↓                         ↓
       Research Graph             Presentation Spec
              ↓                         ↓
       Citation Engine          Visual Renderer
              └────────────┬────────────┘
                           ↓
                   Interactive Viewer
                           ↓
             ┌─────────────┼─────────────┐
             ↓             ↓             ↓
           Explain       Explore       Ask
                           ↓
                     Digital Guide
```

---

# 5. 不使用复杂 Multi-Agent

只需要：

```text
Parser
Research Analyst
Evidence Validator
Presenter
```

更严格地说，第一版甚至可以把它们实现为一个有状态 Pipeline，而不必须引入多 Agent。

重点是：

> **让评委看到“可验证 AI 工程”，而不是“Agent 数量”。**

---

# 6. OSS 复用策略

## 6.1 主参考：showlab/Paper2Video

GitHub：

```text
https://github.com/showlab/Paper2Video
```

该项目来自新加坡国立大学 Show Lab，项目定位就是“从科研论文自动生成演讲视频”，输入论文、图像、音频，PaperTalker 使用幻灯片、字幕、光标、语音与视频等模块生成演示；项目采用 MIT License。citeturn464734search0turn464734search1

### 可复用思路

```text
Paper → Presentation → Narration
```

### 不直接复用的部分

其完整数字人视频路线涉及额外的 talking-head 模型和 GPU，README 给出的最低推荐显卡是 NVIDIA A6000 48GB。比赛项目不应该依赖这条链路。citeturn464734search1

我们只抽取：

```text
Paper parsing ideas
Slide / narration architecture
Evaluation ideas
```

并改造成浏览器交互式体验。

---

# 7. OSS 第二参考：Preacher / Paper2Video

```text
https://github.com/Gen-Verse/Paper2Video
```

该项目把科学论文转换为视频摘要，采用层级规划，并使用 accuracy、professionalism、aesthetic quality、alignment 等评价维度，还加入 CLIP / Aesthetic Score 等自动评价思路。citeturn464734search3

我们重点借鉴：

```text
内容正确性
视觉质量
论文一致性
```

最终建立自己的：

```text
ResearchLens Quality Score
```

---

# 8. OSS 第三参考：Dify

```text
https://github.com/langgenius/dify
```

Dify 提供成熟的 Workflow、RAG、Agent、模型管理和可观测能力，并支持 Docker Compose 部署、OpenAI-compatible 模型等。citeturn259725search5turn259725search12

本项目不需要嵌入整个 Dify，而是：

```text
参考 Workflow UX
参考 Provider abstraction
参考模型配置理念
```

---

# 9. 前端原则：直接借成熟创作型 UI

不要生成普通 Admin Dashboard。

主界面只有三个核心区域：

```text
┌────────────────────────────────────────────┐
│ ResearchLens                               │
│                                            │
│   PAPER        VISUAL STAGE       EVIDENCE│
│                                            │
│   Outline      [论文动态展示]     Claim   │
│   Method                         Citation │
│   Results        [动画]           Page 6  │
│                                            │
│──────────── Timeline ─────────────────────│
│ Problem → Method → Experiment → Result    │
└────────────────────────────────────────────┘
```

核心风格：

```text
科研杂志 × Apple Keynote × AI Studio
```

不是 SaaS 后台。

---

# 10. Paper View

PDF 页面右侧：

```text
AI Interpretation
```

点击论文任何图：

```text
Figure 3
 ↓
What is it?
 ↓
Why it matters?
 ↓
Related Claim
 ↓
Evidence
```

---

# 11. Research Graph

将论文构建成：

```text
Problem
  ↓
Method
  ↓
Experiment
  ↓
Claim
  ↓
Evidence
```

例如：

```text
Claim C07
  │
  ├── Table 2
  ├── Figure 4
  └── Page 6
```

这会成为整个项目最强的“技术展示页面”。

---

# 12. AI Storyboard

自动生成：

```text
Scene 01
标题：研究背景

Scene 02
问题

Scene 03
方法

Scene 04
实验

Scene 05
结果

Scene 06
局限
```

每个 Scene 都绑定证据。

---

# 13. 数字人只是“Presenter”

数字人不要作为项目主体。

它只是：

```text
Research Presenter
```

负责讲解当前 Scene。

允许：

```text
预生成头像/数字人视频
或
Three.js 简易 Presenter
```

TTS 采用外部 API。

这样即使 Avatar 服务挂掉：

```text
字幕 + 音频
```

仍然能展示。

---

# 14. 生成式 AI 的控制原则

## 14.1 Source Grounding

LLM 只能访问：

```text
Paper Text
Figures
Tables
Extracted Claims
Evidence
```

## 14.2 JSON Schema

所有中间结果必须 JSON。

## 14.3 Evidence Gate

没有 citation 不进入事实层。

## 14.4 Fixed Templates

```text
Research Intro
Method
Experiment
Result
Limitation
```

使用固定模板。

## 14.5 Deterministic Demo

比赛 Demo 使用预生成结果。

实时生成只作为第二条路线。

---

# 15. Demo Mode

```env
DEMO_MODE=true
```

没有 API Key：

```text
浏览
→ Demo Paper
→ Interactive Research Graph
→ Timeline
→ Evidence
→ Presenter
→ Q&A Mock
```

都有。

Live Mode 才调用模型。

---

# 16. 一键部署

最终必须做到：

```bash
cp .env.example .env
# 填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL

docker compose up --build
```

打开：

```text
http://localhost:3000
```

不允许要求：

```text
CUDA
Ollama
本地模型
ComfyUI
GPU
```

---

# 17. 技术栈

```text
Frontend:
Next.js
React
TypeScript
Tailwind
Framer Motion
React Flow
PDF viewer

Backend:
FastAPI
Pydantic
SQLAlchemy

AI:
OpenAI-compatible API
Vision model
Structured Output
RAG

Data:
PostgreSQL
pgvector / Qdrant（二选一）

Runtime:
Docker Compose
SSE
```

第一版不增加多余中间件。

---

# 18. 数据模型

```text
Paper
PaperPage
Figure
Table
Section
Claim
Evidence
ResearchGraph
Presentation
Scene
Narration
Question
Answer
GenerationJob
```

---

# 19. Claim Schema

```json
{
  "id": "claim_07",
  "statement": "方法A在数据集B上的准确率为...",
  "type": "RESULT",
  "evidence": [
    {
      "page": 6,
      "region": "table_2",
      "text": "..."
    }
  ],
  "confidence": 0.97
}
```

---

# 20. Q&A 规则

回答必须：

```text
Answer
Evidence
Confidence
```

例如：

```text
这项方法的主要局限是数据集规模较小。

Evidence:
Paper p.8 / Discussion

Confidence: High
```

模型不知道：

```text
“论文未说明。”
```

禁止编造。

---

# 21. 自动质量评分

建立：

```text
ResearchLens Score
```

指标：

```text
Citation Coverage
Claim-Evidence Alignment
Unsupported Claim Rate
Structure Extraction Accuracy
Visual Consistency
Answer Grounding
```

其中：

```text
Unsupported Claim Rate
```

必须尽可能接近 0。

这就是区别普通 AI 文案生成器的重要地方。

---

# 22. 现场量化展示

准备一个固定 Benchmark：

```text
10 papers
100 claims
```

运行：

```text
Claim Extraction Accuracy
Evidence Coverage
Citation Accuracy
```

现场展示一个：

```text
ResearchLens Evaluation

Evidence Coverage      96%
Citation Accuracy      98%
Unsupported Claims      2%
```

注意：必须用真实测得的数据，不能编造数字。

---

# 23. 比赛 5 分钟演示

根据首届决赛官方公开信息，现场采用 5 分钟演示 + 3 分钟问答。citeturn949293search0

因此 Demo 设计：

### 0:00–0:20

“论文是科研传播的载体，但不是人人都能快速读懂。”

### 0:20–0:40

拖入一篇论文。

### 0:40–1:10

自动生成 Paper Map。

### 1:10–1:50

点击 Method。

显示算法流程动画。

### 1:50–2:30

点击实验表格。

Claim → Evidence → Page。

### 2:30–3:10

开始 AI Presenter。

### 3:10–3:40

问：

```text
“这篇论文哪里最值得质疑？”
```

显示 Discussion 证据。

### 3:40–4:20

打开 Research Graph。

展示：

```text
Problem
↓
Method
↓
Experiment
↓
Claim
↓
Evidence
```

### 4:20–4:50

打开 Architecture。

解释：

```text
AI 提取内容
→ 结构化
→ 证据约束
→ 可视化
```

### 4:50–5:00

结束语：

> “ResearchLens 不是让 AI 替科研人员读论文，而是让 AI 把论文变成人人都可以理解、验证和探索的科研成果展项。”

---

# 24. 为什么它比普通“论文总结工具”更有技术力

普通：

```text
PDF → Summary
```

ResearchLens：

```text
PDF
 ↓
Multimodal Parsing
 ↓
Structure
 ↓
Claims
 ↓
Evidence Graph
 ↓
Interactive Presentation
 ↓
Grounded Q&A
 ↓
Evaluation
```

关键在“中间表示”。

不是 prompt magic。

---

# 25. 为什么它比 AI 视频生成平台更稳

视频生成平台最大风险：

```text
生成慢
生成失败
画面随机
人物不一致
API 限流
```

ResearchLens 的主体验是：

```text
HTML/CSS/Canvas/SVG
+ 预制动画
+ 原论文图片
+ 轻量生成
```

生成式 AI 只负责：

```text
结构化内容
讲解
场景说明
```

视觉输出由程序渲染。

稳定性高很多。

---

# 26. EPIC 0：OSS Recon

只做：

```text
Paper2Video
Preacher
Dify
```

确定：

```text
License
Commit
可复用代码
仅参考代码
```

产出：

```text
OSS_REUSE.md
ARCHITECTURE.md
DECISIONS.md
TASKS.md
```

---

# 27. EPIC 1：运行 Paper2Video 参考链

目标：理解：

```text
Paper → Slides → Narration
```

不改业务。

---

# 28. EPIC 2：Paper Parser

完成：

```text
PDF
→ pages
→ sections
→ figures
→ tables
```

---

# 29. EPIC 3：Claim / Evidence

建立：

```text
Claim
Evidence
Citation
```

---

# 30. EPIC 4：Research Graph

使用 React Flow。

---

# 31. EPIC 5：Presentation Engine

生成：

```text
Scene
Slide
Narration
```

---

# 32. EPIC 6：Interactive Viewer

重点打磨：

```text
Paper
Graph
Stage
Evidence
```

---

# 33. EPIC 7：Presenter

完成：

```text
TTS
Avatar fallback
Subtitle
```

---

# 34. EPIC 8：Grounded Q&A

完成：

```text
Question
→ Retrieval
→ Evidence
→ Answer
```

---

# 35. EPIC 9：Evaluation

至少建立：

```text
10 papers
100 claims
```

自动测试。

---

# 36. EPIC 10：Demo Worlds

固定：

```text
Cybersecurity
Computer Vision
Education AI
```

---

# 37. EPIC 11：Docker / Fallback

必须：

```text
API failure
→ cached result

Model failure
→ mock

TTS failure
→ subtitle
```

---

# 38. EPIC 12：Final Integration

最终路径：

```text
Docker
↓
Paper
↓
Map
↓
Method
↓
Evidence
↓
Presenter
↓
Q&A
↓
Evaluation
```

---

# 39. Agent 编排

```text
Architect
 ├── OSS
 ├── Backend
 ├── Frontend
 ├── AI Pipeline
 ├── Evaluation
 └── DevOps
```

禁止一个 Agent 从零重写整个系统。

---

# 40. 前端 Agent 强制规则

必须：

```text
先寻找 OSS UI
再改
```

禁止：

```text
“请帮我生成一个漂亮的 Dashboard”
```

这类 prompt 极容易得到廉价 AI SaaS 风格页面。

---

# 41. 许可证策略

所有 OSS 与素材记录：

```text
URL
Commit
License
作者
文件
修改范围
```

建立：

```text
OSS_REUSE.md
ASSET_LICENSES.md
```

庆园杯明确要求参赛作品原创、团队拥有完整合法知识产权，因此不能把“开源底座”当成自己的全部成果。fileciteturn1file7L471-L489

---

# 42. 最终技术亮点

答辩只讲：

```text
1. 多模态论文理解
2. Claim-Evidence Graph
3. 证据约束生成
4. 交互式科研可视化
5. Grounded Q&A
6. 自动质量评测
```

不要堆几十个框架名。

---

# 43. 最终比赛定位

不要说：

> AI PDF 阅读器

不要说：

> AI 论文总结工具

不要说：

> AI PPT 生成器

说：

> **ResearchLens——面向科研成果的多模态证据理解、交互式演绎与智能讲解平台。**

---

# 44. 一等奖竞争视角的评分目标

不能保证一等奖，但开发目标按下面的优先级设计：

```text
真实问题       ★★★★★
技术壁垒       ★★★★★
创新表达       ★★★★★
Demo冲击       ★★★★★
可落地         ★★★★★
可量化         ★★★★★
稳定性         ★★★★★
```

最重要的一条：

> **宁可少 5 个炫技功能，也必须把“Paper → Evidence → Interactive Result”做得极其完整。**

---

# 45. 主 Agent 第一条指令

```text
阅读本 Spec。

不要直接开发 ResearchLens。

第一阶段执行 EPIC 0。

1. 检查 showlab/Paper2Video
2. 检查 Gen-Verse/Paper2Video
3. 检查 langgenius/dify
4. 锁定 commit
5. 分析 License
6. 运行能运行的部分
7. 对比其前端、Paper pipeline、Evaluation
8. 输出 OSS_REUSE.md
9. 输出 ARCHITECTURE.md
10. 输出 DECISIONS.md
11. 输出 TASKS.md

原则：
OSS 能复用不重写；
已有成熟前端不重新设计；
没有必要的复杂依赖不引入；
不部署本地大模型；
不要求 GPU；
不从零实现论文解析的全部基础能力。

EPIC 0 完成后停止，等待人工审核。
```

---

# 46. 最终一句话

> **第一届一等奖告诉我们的不是“必须做 Agent”，而是“必须让技术真正解决问题，并且在现场证明它”。ResearchLens 的目标就是把前沿多模态生成式 AI 做成一个能够被看见、被验证、被质疑、被交互的科研成果产品。**
