// 安全边界封装（§3.4 / §3.6）：
// - DOMPurify 严格白名单：禁止脚本/事件/iframe/SVG/外链图片/任意样式/危险 URL；
//   保留 table 的 rowspan/colspan/text。清理破坏结构时退回原件（返回空字符串），
//   不退回截断矩阵冒充原件。
// - KaTeX 提取渲染：trust=false、禁危险宏；渲染失败返回空，由调用方显示"可转原件"。

import DOMPurify, { type Config } from 'dompurify';
import katex from 'katex';

/** 允许的标签：表格结构 + 基础文本格式。禁止 svg/math/iframe/script/style/表单/媒体。 */
const ALLOWED_TAGS = [
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
  'p', 'span', 'br', 'b', 'strong', 'i', 'em', 'u', 's', 'sub', 'sup', 'small',
  'code', 'pre', 'div', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'a', 'blockquote', 'hr',
];

/** 允许的属性：仅结构性/可访问性属性，不含 style、事件、id 之外的任意样式。 */
const ALLOWED_ATTR = [
  'rowspan', 'colspan', 'scope', 'align', 'valign', 'headers',
  'title', 'lang', 'dir', 'href', 'start', 'reversed',
];

/** 危险 URL 协议（额外加固，DOMPurify 默认已拒绝大部分）。 */
const SAFE_URI_REGEXP = /^(?:(?:https?|mailto|tel):|[^a-z]|[a-z+.-]+(?:[^a-z+.:-]|$))/i;

const PURIFY_CONFIG: Config = {
  ALLOWED_TAGS,
  ALLOWED_ATTR,
  ALLOW_UNKNOWN_PROTOCOLS: false,
  ALLOWED_URI_REGEXP: SAFE_URI_REGEXP,
  FORBID_TAGS: [
    'script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'button',
    'textarea', 'select', 'option', 'link', 'meta', 'base', 'svg', 'math',
    'video', 'audio', 'source', 'canvas', 'template', 'slot', 'applet', 'frame',
  ],
  FORBID_ATTR: ['style', 'srcdoc'],
  ALLOW_DATA_ATTR: false,
  RETURN_TRUSTED_TYPE: false,
  // 禁止任何 style 注入；表格样式交由外层 .rl-table 约束容器
  USE_PROFILES: { html: true },
};

/** 清理提取 HTML（table_html 等不可信内容）。返回清理后的安全 HTML 字符串。 */
export function sanitizeHtml(html: string): string {
  if (!html) return '';
  return DOMPurify.sanitize(html, PURIFY_CONFIG);
}

/** 清理后是否仍保留可用的表格结构（含 rowspan/colspan/text）。 */
export function isTableIntact(clean: string): boolean {
  if (!clean) return false;
  const hasTable = /<table[\s>]/i.test(clean);
  const hasCell = /<t[dh][\s>]/i.test(clean);
  return hasTable && hasCell;
}

/**
 * 清理提取表格 HTML。若清理后表格结构被破坏（无 table/无单元格），
 * 返回空字符串表示"退回原件"，调用方不得退回截断矩阵。
 */
export function sanitizeTableHtml(html: string): string {
  const clean = sanitizeHtml(html);
  return isTableIntact(clean) ? clean : '';
}

/** KaTeX 安全渲染：trust=false（禁 \href/\htmlClass/\includegraphics 等危险宏）。 */
export function renderKatex(latex: string, display: boolean): string {
  if (!latex) return '';
  try {
    return katex.renderToString(latex, {
      displayMode: display,
      throwOnError: false,
      strict: 'warn',
      trust: false,
      output: 'html',
    });
  } catch {
    return '';
  }
}
