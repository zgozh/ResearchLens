// 在**已经消毒过的 HTML 片段**里渲染 LaTeX。
//
// 历史（ADR-0068）：表格与公式展示走的是 `table_html`（MinerU 产物），里面夹着 LaTeX
// （实测 paper 7 的表 2：`$1.0 \cdot 10^{20}$`、`$O(n^{2} \cdot d)$`），此前被
// `dangerouslySetInnerHTML` 直接塞进页面 → 用户看到的是未渲染的 LaTeX 源码。
//
// 现在**不再自己实现**：解析与 KaTeX 渲染统一委托给 `lib/richtext.ts`（M2/M3 单内核），
// 本文件只保留历史导出名，避免改动所有 import 点。

import { compactLatex, renderMathInHtmlString } from '@/lib/richtext';

export { renderMathInHtmlString as renderMathInHtml };

/** 纯文本里的 LaTeX 清理（不产生公式 DOM 的场景，如表格 caption）。 */
export function cleanLatexInline(text: string): string {
  if (!text) return text;
  return compactLatex(text).body;
}
