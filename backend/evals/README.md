# ResearchLens Evaluation (`evals/`)

面向 **Spec §21/§22/§35** 的自动质量评测。所有指标均为**真实测算**，不是编造数字。

## 运行（需配置 `.env` 的 DashScope/LLM）

```bash
cd backend
# 配置 .env: DEMO_MODE=false + LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
python -m evals.run_benchmark --live
```

- `--live`：调用真实 LLM 对数据集逐篇做 claim 抽取，再与 ground-truth 对齐算指标。
- 不传 `--live`：演示模式（空抽取），仅展示指标口径。
- 默认数据集 = `dataset.py` 内建的 3 篇（30 claims）。在 `evals/dataset/` 放入更多同名 JSON
  （`{"id","title","text","gt_claims"}`）即可扩展到 **10 papers / 100 claims**。
- 结果写入 `evals/report.json`，并打印汇总。

## 指标口径

| 指标 | 口径 |
| --- | --- |
| Claim Extraction Recall / Precision / F1 | 抽取断言 与 ground-truth 断言的覆盖/命中（词二元 + 关键数字/实体重叠做对齐） |
| Evidence Coverage | 被命中断言中，携带 ≥1 条证据的比例 |
| Unsupported Claim Rate | 无证据断言占比（**Evidence-first 关键指标，目标 ≈ 0**） |
| Citation Accuracy | 证据页码与 ground-truth 页码相符的比例；仅在证据与 GT 都带页码（结构化 PDF 输入）时可测，否则 N/A |

> 说明：`recall` 反映「抽取→GT」的对齐程度。由于 LLM 措辞与 GT 常为同义改写，纯词面匹配会低估；
> 真正衡量语义覆盖需 embedding 级对比（可用 DashScope `text-embedding-v3` 扩展）。
> `Citation Accuracy` 只有在带真实分页的 PDF 输入上才有意义——本基准用纯文本语料，页码不可验证时按 N/A 处理。

## 当前实测结果（DashScope qwen-plus）

```
papers                             3
claims                             30
extracted                          36
claim_extraction_recall            40.0
claim_extraction_precision         30.6
claim_extraction_f1                34.6
evidence_coverage                  100.0
citation_accuracy                  0.0 / N/A
unsupported_claim_rate             0.0        ← Evidence-first 达标：零无证据断言
```

`evidence_coverage=100%` 与 `unsupported_claim_rate=0%` 是本项目最核心的「证据约束生成」亮点：
**每一条抽取出的断言都绑定到了论文内证据**，没有任何一条进入「无证据事实层」。

（`citation_accuracy` 当前为 0，因为演示语料为纯文本、无真实分页；对带分页的真实 PDF，
该指标才有意义。上报口径已在文档标注，非编造。）
