# recon/EXTERNAL_TOOLS_AUDIT — 外部优质工具接入审计

> 结论先行：ResearchLens 主链路（解析→断言/证据→图谱/讲解/问答）中，**最值得接入的外部工具是 MinerU 文档解析**（已接入）。
> 其余节点的外部工具多为「锦上添花」，按「是否对应核心卖点」「是否降级友好」评估，见下。

---

## 1. 已接入：MinerU 文档解析 ✅

**定位**：PDF/Doc/PPT/图片 → reading-order Markdown + 结构化表格(HTML) + 真实图(裁剪) + OCR + 公式。
**接口**：`POST /api/v4/extract/task`（URL 提交）或 `/api/v4/file-urls/batch`（本地文件签名上传），异步轮询，返回 zip：
- `full.md`（正文 markdown，阅读顺序）
- `*_content_list.json`（分类型条目：text/table/image/chart/equation + page_idx + bbox）
- `images/*.jpg`（真实裁剪图）
- `layout.json` / `*_model.json`（版式/OCR 细节）

**接入方式**：`app/services/mineru.py` + `ingest.py` 优先走 MinerU，失败降级 pymupdf。
**效果**（3 篇中文软件学报真实论文实测）：
| 论文 | 旧(pymupdf) | 新(MinerU) |
| --- | --- | --- |
| JPEG 隐写载体选择 | 3 图 / 0 表 | **6 图 / 3 表** |
| 移动应用接受度 | 3 图 / 0 表 | **6 图 / 2 表** |
| Solidity 缺陷预测 | 6 图 / 0 表 | **6 图 / 11 表** |
+ 每篇 10~25 页 reading-order 正文，图片为真实裁剪（含子图题注如 "(a) 原图"）。

**关键参数**：`MINERU_TOKEN`（API 管理页创建）；`model_version=vlm`；`is_ocr=true`；`enable_formula/table=true`；`language=ch`。
**限流**：≤200MB/200 页；每账号每天 1000 页最高优先级。**费用**：本 key 为额度制。
**坑**：MinerU CDN（`cdn-mineru.openxlab.org.cn`）偶发 `Connection refused` → 已加 `_download_zip` 重试。github/aws 等境外 URL 会超时，须用境内可公开访问的 URL。

---

## 2. 其他候选外部工具：评估结论

| 环节 | 候选工具 | 建议 | 理由 |
| --- | --- | --- | --- |
| 正文/图表解析 | **MinerU** | ✅ 已接入 | 唯一大幅提升「识别出多少内容」的节点 |
| 图生成/查看 | — | 可用 MinerU 真实图 | 已由 MinerU 画像填充，无需额外工具 |
| QA 语义检索 | 本地词面检索 → **Embedding+RAG** | 后续可做 | 当前 QA 用 `qwen-plus`+全文上下文，多数场景够用；要做更强引用检索再引入嵌入 |
| 公式 → LaTeX | MinerU 已给公式 | ✅ 已覆盖 | `enable_formula` |
| 数字人/语音讲解 | — | 不在卖点 | 无语音是刻意设计（简洁），不引入 |
| 人像/3D | — | 不做 | 非论文理解工具，偏离科研语义 |

---

## 3. 结论 / 后续建议

1. **MinerU 是本次最有价值的升级**：把「识别不出表格/图/公式/扫描页」这个核心短板补上了，3 篇中文真实论文图表数从 0→2~11 张。
2. 其余环节（QA 检索、讲解、图谱）在当前数据质量下已能自洽，外部工具收益边际递减。
3. 若未来要 **更强 grounding 检索**，可引入 `text-embedding-v3`（DashScope）做向量召回 + 重排，但那是二期。
4. 工程纪律：所有外部工具均**降级友好**（MinerU 失败→pymupdf；LLM 失败→词面检索），主链路永远可用——符合项目「Evidentiary first / 可降级」根基。
