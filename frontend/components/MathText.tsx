'use client';

import { useMemo } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { cn } from '@/lib/cn';

/** 把 LaTeX/乱码符号清理为可读文本（非公式场景）。 */
function cleanPlain(text: string): string {
  // 去掉围栏里的 raw LaTeX 命令残留
  return text
    .replace(/\\(?:times|cdot|le|ge|neq|approx|pm|times|div|rightarrow|leftarrow|ast|star)\b/g, (m) =>
      ({ times: '×', cdot: '·', le: '≤', ge: '≥', neq: '≠', approx: '≈', pm: '±', div: '÷', rightarrow: '→', leftarrow: '←', ast: '*', star: '★' }[m.replace('\\', '')] || m),
    )
    .replace(/\\(?:text|mathrm|mathbf|mathit|operatorname|mathbb|mathcal|bf|it)\{([^}]*)\}/g, '$1')
    .replace(/\\(?:frac|dfrac)\{([^}]*)\}\{([^}]*)\}/g, '$1/$2')
    .replace(/\\_/g, '_')
    .replace(/\\%/g, '%')
    .replace(/\\&/g, '&')
    .replace(/\\#/g, '#')
    .replace(/\\\{/g, '{')
    .replace(/\\\}/g, '}');
}

function toKatex(tex: string, display: boolean): string {
  try {
    return katex.renderToString(tex, {
      displayMode: display,
      throwOnError: false,
      strict: false,
      output: 'html',
    });
  } catch {
    // 不识别就直接按纯文本放（避免中断整段渲染）
    return cleanPlain(tex);
  }
}

/** 受保护的美元符号占位符：``\$`` 是"字面美元"，不能参与公式定界符匹配。 */
const DOLLAR_PLACEHOLDER = '\u0001';

/**
 * 渲染可能含 LaTeX 公式的文本：
 * - `$...$` / `\(...\)` → 行内公式（KaTeX）
 * - `$$...$$` / `\[...\]` → 块级公式（KaTeX）
 * - 其余文本做 LaTeX 命令清理 + HTML 实体转义，避免显示未转义符号
 *
 * **`\$` 必须先保护再切分**（实测 paper 2 的 `rf\$importance`）：否则这个 `$`
 * 会和后面任意一个 `$` 配成一对，把中间大段正文吞进"公式"里，看起来就是乱码。
 */
export function MathText({ text, className }: { text: string; className?: string }) {
  const parts = useMemo(() => {
    if (!text) return [{ type: 'plain', val: '' }] as { type: 'plain' | 'math'; val: string; display?: boolean }[];
    // 先切块级公式，再切行内公式
    const tokens: { type: 'plain' | 'math'; val: string; display?: boolean }[] = [];
    const rest = text.replace(/\\\$/g, DOLLAR_PLACEHOLDER);
    // 块级：$$...$$ 或 \[...\]
    const blockRe = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]/g;
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = blockRe.exec(rest)) !== null) {
      if (m.index > last) tokens.push({ type: 'plain', val: rest.slice(last, m.index) });
      tokens.push({ type: 'math', val: (m[1] ?? m[2]).trim(), display: true });
      last = m.index + m[0].length;
    }
    if (last < rest.length) tokens.push({ type: 'plain', val: rest.slice(last) });
    // 再把每个 plain 内部的行内公式切开：$...$ 与 \(...\)
    const out: { type: 'plain' | 'math'; val: string; display?: boolean }[] = [];
    for (const t of tokens) {
      if (t.type === 'math') {
        out.push(t);
        continue;
      }
      const inlineRe = /\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)/g;
      let last2 = 0;
      let m2: RegExpExecArray | null;
      while ((m2 = inlineRe.exec(t.val)) !== null) {
        if (m2.index > last2) out.push({ type: 'plain', val: t.val.slice(last2, m2.index) });
        const tex = (m2[1] ?? m2[2]).trim();
        if (tex && !/^\s*[a-zA-Z0-9\s,.\u4e00-\u9fff，。、：；]{0,3}\s*$/.test(tex) && /[\\=_{}^]/.test(tex)) {
          out.push({ type: 'math', val: tex, display: false });
        } else {
          // 太短或无 LaTeX 特征（如 $^1$ 上标、$a$ 单字母）——不当公式，清理文本
          out.push({ type: 'plain', val: m2[0] });
        }
        last2 = m2.index + m2[0].length;
      }
      if (last2 < t.val.length) out.push({ type: 'plain', val: t.val.slice(last2) });
    }
    return out;
  }, [text]);

  return (
    <span className={cn('text-[13.5px] leading-relaxed', className)}>
      {parts.map((p, i) =>
        p.type === 'math' ? (
          <span
            key={i}
            className={p.display ? 'rl-math-block' : 'rl-inline-math'}
            // KaTeX 输出已做转义；用 HTML 渲染公式
            dangerouslySetInnerHTML={{ __html: toKatex(p.val, !!p.display) }}
          />
        ) : (
          <span
            key={i}
            dangerouslySetInnerHTML={{
              __html: escapeHtml(cleanPlain(p.val)).split(DOLLAR_PLACEHOLDER).join('$'),
            }}
          />
        ),
      )}
    </span>
  );
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
