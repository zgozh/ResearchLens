'use client';

// 在**已经消毒过的 HTML 片段**里渲染 LaTeX（ADR-0068）。
//
// 为什么需要：表格与公式的展示走的是 `table_html` / KaTeX 字符串（MinerU 解析产物），
// 里面**夹着 LaTeX**（实测 paper 7 的表 2：`$1.0 \cdot 10^{20}$`、`$O(n^{2} \cdot d)$`）。
// 这些 HTML 以前被 `dangerouslySetInnerHTML` 直接塞进页面 → 用户看到的就是**未渲染的
// LaTeX 源码**（"像一堆乱码"）。这里把 `$...$` / `$$...$$` 就地替换成 KaTeX 的 HTML。
//
// 安全性：KaTeX 的输出是自包含的 `<span>`（不产生脚本），且本函数只做**纯字符串替换**，
// 不引入新的标签结构；调用方仍必须先过 `sanitizeTableHtml`。

import katex from 'katex';

function renderOne(tex: string, display: boolean): string | null {
  const body = (tex || '').trim();
  if (!body) return null;
  try {
    return katex.renderToString(body, {
      displayMode: display,
      throwOnError: false,
      strict: false,
      output: 'html',
    });
  } catch {
    return null; // 渲染不了就保留原样，不制造半截 HTML
  }
}

/**
 * 把 HTML 里的 `$$...$$` 与 `$...$` 换成 KaTeX HTML。
 * 不匹配/渲染失败时**原样保留**，绝不吞掉内容。
 */
export function renderMathInHtml(html: string): string {
  if (!html || !html.includes('$')) return html;
  // 先保护 `\$`（字面美元），避免与公式定界符配对
  const PH = '\u0001';
  const guarded = html.replace(/\\\$/g, PH);
  const out = guarded
    .replace(/\$\$([\s\S]+?)\$\$/g, (m, tex) => renderOne(tex, true) ?? m)
    .replace(/\$([^$\n]+?)\$/g, (m, tex) => renderOne(tex, false) ?? m);
  return out.split(PH).join('$');
}

/**
 * 纯文本里的 LaTeX 清理（不产生公式 DOM 的场景，如表格 caption）。
 * 只做无害的符号替换，避免把 `\cdot` 这类命令原样显示。
 */
export function cleanLatexInline(text: string): string {
  if (!text) return text;
  return text
    .replace(/\\(?:times|cdot)\b/g, '·')
    .replace(/\\%/g, '%')
    .replace(/\\_/g, '_')
    .replace(/\\&/g, '&')
    .replace(/\\#/g, '#');
}
