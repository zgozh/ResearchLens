// 统一富文本渲染内核（REFACTOR_PLAN M2/M3）。
//
// 为什么需要：MinerU 解析出的正文里混着三类"未转义字符"，此前**四条渲染路径各写各的**，
// 于是同一段文本在不同面板里表现不一致（实测用户报障）：
//   ① 行内 HTML 标签原样显示：`Ashish Vaswani<sup>∗</sup> Google Brain avaswani@google.com`
//   ② 公式定界符残留：`$P _ { d r o p } = 0 . 1$`（MathText 走 KaTeX，但表格/媒体介绍没走）
//   ③ 跨行块级公式被按行切断：`$$\n...\tag{1}\n$$` 被 `split(/\n/)` 拆散 → 永远配不成公式
//
// 本模块是**唯一**的解析 + 渲染实现：
//   parseRichText()  —— 纯函数，无 DOM、无 React，可在 Node 里直接单测
//   renderRichHtml() —— 解析 + KaTeX 渲染成 HTML 字符串（四处消费方共用）
//   splitParagraphs()—— 数学感知的切段（不把 `$$…$$` 切开）
//
// 安全边界：文本一律 escapeHtml；行内标签只放行 sup/sub/i/b/em/strong/code/br 白名单；
// KaTeX 以 `trust:false` 渲染（禁 \href/\htmlClass 等危险宏）；KaTeX 失败降级为
// **去掉定界符**的等宽文本，绝不让 `$`/`$$`/`\tag` 字面量出现在 DOM 里。

import katex from 'katex';

export type Tone = 'dark' | 'light';

export type RichNodeType =
  | 'text'
  | 'sup'
  | 'sub'
  | 'i'
  | 'b'
  | 'code'
  | 'br'
  | 'math_inline'
  | 'math_block';

export interface RichNode {
  type: RichNodeType;
  /** 叶子节点内容；math 节点为**不含定界符**的纯 LaTeX。 */
  text?: string;
  /** 容器节点（sup/sub/i/b/code）的子节点。 */
  children?: RichNode[];
  href?: string;
  /** 仅 math_block：`\tag{N}` 的编号。 */
  tag_no?: string;
}

export type IssueCode =
  | 'UNPAIRED_DOLLAR'
  | 'BLOCK_DELIMITER_RESIDUE'
  | 'UNKNOWN_TAG'
  | 'CONTROL_CHAR'
  | 'MIXED_WIDTH'
  | 'LATEX_SUSPECT';

export interface TextIssue {
  code: IssueCode;
  severity: 'info' | 'warn';
  excerpt: string;
  offset?: number | null;
}

export interface NormalizedText {
  plain: string;
  rich: RichNode[];
  issues: TextIssue[];
}

export interface RenderOptions {
  kind?: 'body' | 'caption' | 'header';
  /** 深色面板（默认，论文阅读）或浅色面板（原件媒体/表格卡片）。 */
  tone?: Tone;
  /** 是否允许块级公式居中展示（默认 true）。 */
  blockMath?: boolean;
}

export interface RenderResult {
  html: string;
  plain: string;
  issues: TextIssue[];
}

/**
 * `\$` 的字面美元占位符：还原成 `$` 之后不再参与公式配对。
 * 必须落在**私用区**（U+E000/U+E001）而不是 U+0001 之类：控制符会被 CONTROL_CHARS 当脏字符删掉，
 * 那样 `rf\$importance` 里的美元符号会被静默吞掉（实测 bug）。
 */
const LITERAL_DOLLAR = '\uE000';
/** 受保护的文本类命令占位符（`\text{...}` 内部空格不许被压缩）。 */
const VAULT_OPEN = '\uE001';

const TEXT_TAGS: Record<string, RichNodeType> = {
  sup: 'sup',
  sub: 'sub',
  i: 'i',
  em: 'i',
  b: 'b',
  strong: 'b',
  code: 'code',
};

/** 有这些字符基本可以断定是 LaTeX（而不是被误配对的美元金额）。 */
const LATEX_HINT = /[\\=_{}^]/;
/** 文本类命令：花括号内部是**自然语言**，空格必须原样保留。 */
const TEXT_COMMANDS =
  /\\(?:text|textrm|textit|textbf|textsf|texttt|textnormal|mathrm|mathbf|mathit|mathsf|mathtt|operatorname|mathbb|mathcal|mathfrak|mbox|hbox)\s*\{([^{}]*)\}/g;

const SCAN_SOURCE = [
  String.raw`\$\$(?<bd>[\s\S]+?)\$\$`,
  String.raw`\\\[(?<bb>[\s\S]+?)\\\]`,
  String.raw`\\\((?<ip>[\s\S]+?)\\\)`,
  String.raw`<(?<ctag>sup|sub|i|b|strong|em|code)>(?<cinner>[\s\S]*?)<\/\k<ctag>>`,
  String.raw`<br\s*\/?>`,
  String.raw`\$(?<id>[^$\n]+?)\$`,
  String.raw`<\/?(?<tname>[a-zA-Z][\w:-]*)[^>]*>`,
].join('|');

/** 控制符（保留 \n 与 \t）。test 用非全局版、replace 用全局版，避免 lastIndex 陷阱。 */
const CONTROL_CHARS = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/;
const CONTROL_CHARS_ALL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/g;

function clip(s: string, n = 80): string {
  const t = (s || '').replace(/\s+/g, ' ').trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

/**
 * 压缩 MinerU 常见的 token 断裂（`P _ { d r o p } = 0 . 1` → `P_{drop}=0.1`）。
 * 只作用于**公式体**，正文一个字符都不许动。
 */
export function compactLatex(input: string): { body: string; tagNo: string | null } {
  let body = (input ?? '').trim();
  // 外层定界符（调用方可能把带定界符的整串丢进来，如 media.extracted.latex）
  body = body
    .replace(/^\$\$/, '')
    .replace(/\$\$$/, '')
    .replace(/^\$/, '')
    .replace(/\$$/, '')
    .replace(/^\\\[/, '')
    .replace(/\\\]$/, '')
    .replace(/^\\\(/, '')
    .replace(/\\\)$/, '')
    .trim();

  let tagNo: string | null = null;
  body = body.replace(/\\tag\*?\s*\{([^{}]*)\}/g, (_s, n: string) => {
    if (tagNo === null) tagNo = String(n).trim();
    return '';
  });

  const vault: string[] = [];
  body = body.replace(TEXT_COMMANDS, (s) => {
    vault.push(s);
    return `${VAULT_OPEN}${vault.length - 1}${VAULT_OPEN}`;
  });

  body = body
    .replace(/(\d)\s*\.\s*(\d)/g, '$1.$2') // 0 . 1 → 0.1
    .replace(/\s*([_^])\s*/g, '$1') // d _ { k } → d_{k}
    .replace(/\s*([{}])\s*/g, '$1') // \sqrt { x } → \sqrt{x}
    .replace(/\s*([=+\-*/<>])\s*/g, '$1')
    // MinerU 会把单词按字距拆开：`{ d r o p }` → `{drop}`。只在"单字符 + 单空格"序列上动手，
    // 普通短语（`{hello world}`）保持不变。
    .replace(/\{([^{}]*)\}/g, (_s, inner: string) =>
      /^(?:\S\s)+\S$/.test(inner) ? `{${inner.replace(/\s+/g, '')}}` : `{${inner}}`,
    )
    .replace(/\s+/g, ' ')
    .trim();

  body = body.replace(new RegExp(`${VAULT_OPEN}(\\d+)${VAULT_OPEN}`, 'g'), (_s, i: string) => vault[Number(i)] ?? '');
  return { body, tagNo };
}

/** 判断一段 `$…$` 内容是真的公式，还是被误配对的美元金额/普通词。 */
export function isMathLike(tex: string): boolean {
  const t = (tex ?? '').trim();
  if (!t) return false;
  if (LATEX_HINT.test(t)) return true;
  return !/\s/.test(t) && t.length <= 12 && /[A-Za-z]/.test(t);
}

function mathNode(raw: string, display: boolean, out: TextIssue[], offset: number): RichNode {
  const { body, tagNo } = compactLatex(raw);
  if (tagNo && !display) {
    out.push({
      code: 'LATEX_SUSPECT',
      severity: 'info',
      excerpt: clip(`\\tag 出现在行内公式：${raw}`),
      offset,
    });
  }
  return { type: display ? 'math_block' : 'math_inline', text: body, tag_no: tagNo ?? undefined };
}

/**
 * 解析为富文本 AST。纯函数：无 DOM、无 React、无网络，可在 Node 中直接单测。
 * `plain` 与 `rich` 的叶子文本**逐字一致**（这是渲染一致性的基线）。
 */
export function parseRichText(input: string, opts: { kind?: 'body' | 'caption' | 'header' } = {}): NormalizedText {
  const raw = (input ?? '').replace(/\r\n/g, '\n');
  const nodes: RichNode[] = [];
  const issues: TextIssue[] = [];
  const src = raw.replace(/\\\$/g, LITERAL_DOLLAR);

  const pushText = (chunk: string, at: number) => {
    if (!chunk) return;
    let t = chunk;
    if (t.includes('$$')) {
      issues.push({
        code: 'BLOCK_DELIMITER_RESIDUE',
        severity: 'warn',
        excerpt: clip(t),
        offset: at,
      });
      t = t.replace(/\$\$/g, '');
    }
    if (t.includes('$')) {
      issues.push({ code: 'UNPAIRED_DOLLAR', severity: 'warn', excerpt: clip(t), offset: at });
      t = t.replace(/\$/g, '');
    }
    if (CONTROL_CHARS.test(t)) {
      issues.push({ code: 'CONTROL_CHAR', severity: 'warn', excerpt: clip(t), offset: at });
      t = t.replace(CONTROL_CHARS_ALL, '');
    }
    t = t.split(LITERAL_DOLLAR).join('$');
    if (t) nodes.push({ type: 'text', text: t });
  };

  let last = 0;
  let m: RegExpExecArray | null;
  // 每次调用**新建**正则实例：容器节点会递归调用本函数，若共用带 g 的正则会互相
  // 覆盖 lastIndex（实测直接死循环吃满 4GB 堆）。这是本内核唯一允许的"性能开销"。
  const scan = new RegExp(SCAN_SOURCE, 'gi');
  while ((m = scan.exec(src)) !== null) {
    if (m.index > last) pushText(src.slice(last, m.index), last);
    const g = (m.groups ?? {}) as Record<string, string | undefined>;
    if (g.bd !== undefined) {
      nodes.push(mathNode(g.bd, true, issues, m.index));
    } else if (g.bb !== undefined) {
      nodes.push(mathNode(g.bb, true, issues, m.index));
    } else if (g.ip !== undefined) {
      nodes.push(mathNode(g.ip, false, issues, m.index));
    } else if (g.ctag !== undefined) {
      const tag = TEXT_TAGS[g.ctag.toLowerCase()] ?? 'text';
      const inner = parseRichText(g.cinner ?? '', { kind: 'body' });
      issues.push(...inner.issues);
      nodes.push({
        type: tag,
        children: inner.rich.length > 0 ? inner.rich : [{ type: 'text', text: '' }],
      });
    } else if (/^<br/i.test(m[0])) {
      nodes.push({ type: 'br' });
    } else if (g.id !== undefined) {
      const { body } = compactLatex(g.id);
      if (isMathLike(body)) {
        nodes.push({ type: 'math_inline', text: body });
      } else {
        // 不是公式（多为美元金额/被误配对的普通词）：丢掉定界符，保留内容
        issues.push({ code: 'LATEX_SUSPECT', severity: 'info', excerpt: clip(m[0]), offset: m.index });
        pushText(g.id, m.index);
      }
    } else {
      issues.push({ code: 'UNKNOWN_TAG', severity: 'warn', excerpt: clip(m[0]), offset: m.index });
      pushText(m[0], m.index);
    }
    last = m.index + m[0].length;
  }
  if (last < src.length) pushText(src.slice(last), last);

  return { plain: plainOf(nodes), rich: nodes, issues };
}

/** 把 AST 的叶子文本按顺序拼回纯文本。 */
export function plainOf(nodes: RichNode[]): string {
  let out = '';
  for (const n of nodes) {
    if (n.type === 'br') {
      out += '\n';
      continue;
    }
    if (n.children) out += plainOf(n.children);
    if (typeof n.text === 'string' && !n.children) out += n.text;
  }
  return out;
}

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** KaTeX 渲染；失败或产出 error 标记时返回 null（由调用方降级）。 */
export function katexToHtml(tex: string, display: boolean): string | null {
  const body = (tex ?? '').trim();
  if (!body) return null;
  try {
    const html = katex.renderToString(body, {
      displayMode: display,
      throwOnError: false,
      strict: false,
      trust: false,
      output: 'html',
    });
    if (!html || html.includes('katex-error')) return null;
    return html;
  } catch {
    return null;
  }
}

/** 公式渲染失败时的可读降级：等宽显示去定界符的 LaTeX，绝不出现 `$`。 */
function fallbackHtml(tex: string, display: boolean): string {
  const cls = display ? 'rl-math-block rl-tex-fallback' : 'rl-inline-math rl-tex-fallback';
  return `<span class="${cls}">${escapeHtml(tex)}</span>`;
}

const TONE_CLASS: Record<Tone, string> = { dark: '', light: 'rl-tone-light' };

function nodesToHtml(nodes: RichNode[], tone: Tone, blockMath: boolean, issues: TextIssue[]): string {
  let out = '';
  for (const n of nodes) {
    switch (n.type) {
      case 'text':
        out += escapeHtml(n.text ?? '');
        break;
      case 'br':
        out += '<br/>';
        break;
      case 'code':
        out += `<code class="rl-inline-code">${escapeHtml(plainOf(n.children ?? []))}</code>`;
        break;
      case 'sup':
      case 'sub':
      case 'i':
      case 'b':
        out += `<${n.type}>${nodesToHtml(n.children ?? [], tone, false, issues)}</${n.type}>`;
        break;
      case 'math_inline':
      case 'math_block': {
        const display = n.type === 'math_block' && blockMath;
        const html = katexToHtml(n.text ?? '', display);
        const toneCls = TONE_CLASS[tone];
        if (!html) {
          issues.push({
            code: 'LATEX_SUSPECT',
            severity: 'info',
            excerpt: clip(n.text ?? ''),
          });
          out += fallbackHtml(n.text ?? '', display);
          break;
        }
        const cls = `${display ? 'rl-math-block' : 'rl-inline-math'}${toneCls ? ` ${toneCls}` : ''}`;
        const no = display && n.tag_no ? `<span class="rl-eq-no">(${escapeHtml(n.tag_no)})</span>` : '';
        out += `<span class="${cls}">${html}${no}</span>`;
        break;
      }
      default:
        break;
    }
  }
  return out;
}

/**
 * 解析 + 渲染成 HTML 字符串。**四处消费方（正文 / 表格 / 证据引文 / 媒体介绍）必须都调它**，
 * 否则又会出现"同一段文本在不同面板表现不一致"。
 */
export function renderRichHtml(text: string, opts: RenderOptions = {}): RenderResult {
  const parsed = parseRichText(text ?? '', { kind: opts.kind });
  const issues = [...parsed.issues];
  const html = nodesToHtml(parsed.rich, opts.tone ?? 'dark', opts.blockMath !== false, issues);
  return { html, plain: parsed.plain, issues };
}

/** 只取可读纯文本（不需要公式 DOM 的场景，如缩略标题/tooltip/纯文本导出）。 */
export function toDisplayText(text: string): string {
  return parseRichText(text ?? '').plain;
}

/** 数学感知的切段：绝不在 `$$…$$` / `\[…\]` 内部断开。 */
export function splitParagraphs(text: string): string[] {
  const src = (text ?? '').replace(/\r\n/g, '\n');
  const out: string[] = [];
  const pushSplit = (chunk: string) => {
    for (const p of chunk.split(/\n{2,}|\n/)) {
      if (p.trim().length > 0) out.push(p.trim());
    }
  };
  const re = /\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) pushSplit(src.slice(last, m.index));
    out.push(m[0].trim());
    last = m.index + m[0].length;
  }
  if (last < src.length) pushSplit(src.slice(last));
  return out;
}

/** 就地渲染已经消毒过的 HTML 片段里的 `$$…$$` / `$…$`（表格 HTML 用）。 */
export function renderMathInHtmlString(html: string): string {
  if (!html || !html.includes('$')) return html;
  const guarded = html.replace(/\\\$/g, LITERAL_DOLLAR);
  const out = guarded
    .replace(/\$\$([\s\S]+?)\$\$/g, (full, tex: string) => {
      const { body } = compactLatex(tex);
      return katexToHtml(body, true) ?? full;
    })
    .replace(/\$([^$\n]+?)\$/g, (full, tex: string) => {
      const { body } = compactLatex(tex);
      if (!isMathLike(body)) return full;
      return katexToHtml(body, false) ?? full;
    });
  return out.split(LITERAL_DOLLAR).join('$');
}
