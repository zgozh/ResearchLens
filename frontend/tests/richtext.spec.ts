// M2/M3 渲染内核单元测试（零测试框架依赖）。
//
// 为什么不用 vitest：这个前端工程此前**没有**单测运行时（只有 Playwright e2e），
// 为一个纯函数内核引入 vitest + jsdom + @testing-library 三件套不划算，也违反
// REFACTOR_PLAN §2.2"不引入重型依赖"。内核本身是纯字符串函数（无 DOM / 无 React），
// 所以用 `tsc` 编译到 `.tmp/` 后直接 `node` 跑即可，失败退出码非 0，可当 CI 门禁。
//
// 运行：npm run test:rich

import assert from 'assert';
import {
  compactLatex,
  parseRichText,
  plainOf,
  renderMathInHtmlString,
  renderRichHtml,
  splitParagraphs,
} from '../lib/richtext';

let passed = 0;
const failures: string[] = [];

function check(name: string, fn: () => void) {
  try {
    fn();
    passed += 1;
    console.log(`  ok  ${name}`);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    failures.push(`${name}: ${msg}`);
    console.log(`FAIL  ${name}\n      ${msg}`);
  }
}

const HEADER_LINE = 'Ashish Vaswani<sup>∗</sup> Google Brain avaswani@google.com';
const INLINE_MATH = 'For the base model, we use a rate of $P _ { d r o p } = 0 . 1$';
const BLOCK_MATH =
  '$$\n \\operatorname{Attention}(Q, K, V) = \\operatorname{softmax}(\\frac{Q K^{T}}{\\sqrt { d _ { k } }})V \\tag{1}\n$$';

console.log('richtext 内核测试');

// ── 1. 行内白名单标签 ───────────────────────────────────────────────
check('1.1 <sup> 转为语义节点，plain 不留标签字面量', () => {
  const r = parseRichText(HEADER_LINE, { kind: 'header' });
  assert.ok(!r.plain.includes('<sup>'), `plain 仍含 <sup>：${r.plain}`);
  assert.ok(!r.plain.includes('</sup>'), `plain 仍含 </sup>：${r.plain}`);
  assert.ok(r.plain.includes('∗'), 'plain 丢了上标字符 ∗');
  const sup = r.rich.find((n) => n.type === 'sup');
  assert.ok(sup, '没有生成 sup 节点');
  assert.strictEqual(plainOf(sup!.children ?? []), '∗');
});

check('1.2 去标签后字符无丢失（逐字比对）', () => {
  const r = parseRichText(HEADER_LINE, { kind: 'header' });
  const expected = HEADER_LINE.replace(/<\/?sup>/g, '');
  assert.strictEqual(r.plain, expected);
});

check('1.3 渲染成 HTML 时 <sup> 是真标签而不是字面量', () => {
  const { html } = renderRichHtml(HEADER_LINE, { kind: 'header' });
  assert.ok(html.includes('<sup>∗</sup>'), html);
  assert.ok(!html.includes('&lt;sup&gt;'), '标签被转义成了字面量');
  assert.ok(html.includes('avaswani@google.com'), '邮箱丢失');
});

// ── 2. 行内公式 ─────────────────────────────────────────────────────
check('2.1 $P _ { d r o p } = 0 . 1$ 压成紧凑 LaTeX 并渲染', () => {
  const r = parseRichText(INLINE_MATH);
  const math = r.rich.find((n) => n.type === 'math_inline');
  assert.ok(math, '没有生成 math_inline 节点');
  assert.strictEqual(math!.text, 'P_{drop}=0.1');
  assert.ok(!math!.text!.includes('$'), 'math 文本里残留 $');
  assert.ok(r.plain.includes('For the base model, we use a rate of'), '正文被打乱');
});

check('2.2 行内公式渲染出 KaTeX 且全文不留 $ 字面量', () => {
  const { html } = renderRichHtml(INLINE_MATH);
  assert.ok(html.includes('katex'), '没有 KaTeX 输出');
  assert.ok(!html.includes('$'), `html 里残留 $：${html}`);
});

check('2.3 美元金额不会被误当公式（成对但非 LaTeX）', () => {
  const r = parseRichText('It costs $10 and $20 in total.');
  assert.strictEqual(r.rich.filter((n) => n.type === 'math_inline').length, 0);
  assert.ok(r.plain.includes('10 and'), r.plain);
  assert.ok(!r.plain.includes('$'), '定界符未清理');
  assert.ok(r.issues.some((i) => i.code === 'LATEX_SUSPECT'), '未记录 LATEX_SUSPECT');
});

// ── 3. 块级公式 ─────────────────────────────────────────────────────
check('3.1 跨行 $$…\\tag{1}$$ 识别为 math_block 并剥离 \\tag', () => {
  const r = parseRichText(BLOCK_MATH);
  const math = r.rich.find((n) => n.type === 'math_block');
  assert.ok(math, `没有 math_block 节点：${JSON.stringify(r.rich)}`);
  assert.strictEqual(math!.tag_no, '1');
  assert.ok(!math!.text!.includes('$$'), 'math 文本残留 $$');
  assert.ok(!math!.text!.includes('\\tag'), 'math 文本残留 \\tag');
  assert.ok(math!.text!.includes('\\operatorname{Attention}'), math!.text!);
  assert.ok(!math!.text!.includes('d _ { k }'), `空格未压缩：${math!.text!}`);
});

check('3.2 块级公式渲染后带编号角标，无 $ 残留', () => {
  const { html } = renderRichHtml(BLOCK_MATH);
  assert.ok(html.includes('rl-math-block'), html.slice(0, 200));
  assert.ok(html.includes('rl-eq-no'), '没有编号角标');
  assert.ok(!html.includes('$$'), 'html 残留 $$');
  assert.ok(!html.includes('\\tag'), 'html 残留 \\tag');
});

check('3.3 splitParagraphs 不把跨行块级公式切开', () => {
  const parts = splitParagraphs(`引言段\n${BLOCK_MATH}\n收尾段`);
  assert.strictEqual(parts.length, 3, JSON.stringify(parts));
  assert.strictEqual(parts[1], BLOCK_MATH.trim());
});

check('3.4 compactLatex 直接吃带定界符的 media.extracted.latex', () => {
  const { body, tagNo } = compactLatex('$$ E = m c^{2} \\tag{7} $$');
  assert.strictEqual(tagNo, '7');
  assert.strictEqual(body.replace(/\s+/g, ''), 'E=mc^{2}');
});

// ── 4. 未配对 / 转义美元 ────────────────────────────────────────────
check('4.1 落单 $ 记 UNPAIRED_DOLLAR 且不在 DOM 里残留', () => {
  const r = parseRichText('The model costs $10 only.');
  assert.ok(r.issues.some((i) => i.code === 'UNPAIRED_DOLLAR'), '未记录 UNPAIRED_DOLLAR');
  assert.ok(!r.plain.includes('$'), r.plain);
  assert.ok(!renderRichHtml('The model costs $10 only.').html.includes('$'));
});

check('4.2 \\$ 是字面美元，不参与配对，也不报错', () => {
  const r = parseRichText('the rf\\$importance is high');
  assert.ok(r.plain.includes('rf$importance'), r.plain);
  assert.ok(!r.issues.some((i) => i.code === 'UNPAIRED_DOLLAR'), '误报未配对');
  assert.strictEqual(r.rich.filter((n) => n.type === 'math_inline').length, 0);
});

check('4.3 落单 $$ 记 BLOCK_DELIMITER_RESIDUE', () => {
  const r = parseRichText('前言 $$ 后记');
  assert.ok(r.issues.some((i) => i.code === 'BLOCK_DELIMITER_RESIDUE'), '未记录定界符残留');
  assert.ok(!r.plain.includes('$'), r.plain);
});

// ── 5. 非白名单标签 / 安全 ──────────────────────────────────────────
check('5.1 <unk> / <table> 记 UNKNOWN_TAG 且按字面保留', () => {
  const r = parseRichText('<unk> and <table>');
  assert.ok(r.issues.filter((i) => i.code === 'UNKNOWN_TAG').length >= 1);
  assert.ok(r.plain.includes('<unk>'), r.plain);
});

check('5.2 <script> 在 HTML 里被转义，不产生可执行节点', () => {
  const { html } = renderRichHtml('<script>alert(1)</script>');
  assert.ok(!/<script/i.test(html), html);
  assert.ok(html.includes('&lt;script&gt;'), html);
});

check('5.3 <img onerror> 被转义', () => {
  const { html } = renderRichHtml('<img src=x onerror=alert(1)>');
  assert.ok(!/<img/i.test(html), html);
});

// ── 6. 控制符 / 幂等 / 一致性 ───────────────────────────────────────
check('6.1 控制符被剥离并记录', () => {
  const r = parseRichText('abc\u0000def\u0007');
  assert.strictEqual(r.plain, 'abcdef');
  assert.ok(r.issues.some((i) => i.code === 'CONTROL_CHAR'));
});

check('6.2 幂等：二次解析不再产生**新的** issue 种类', () => {
  for (const sample of [HEADER_LINE, INLINE_MATH, BLOCK_MATH, '<unk> and <table>']) {
    const once = parseRichText(sample);
    const twice = parseRichText(once.plain);
    assert.strictEqual(twice.plain, once.plain, `plain 不稳定：${sample}`);
    // 二次扫描不允许出现首轮没有的 issue 种类（`<unk>` 这类**字面量标签**会稳定复现，属正常）
    const before = new Set(once.issues.map((i) => i.code));
    const added = twice.issues.filter((i) => !before.has(i.code)).map((i) => i.code);
    assert.strictEqual(added.length, 0, `二次解析出现新 issue：${JSON.stringify(added)}`);
  }
});

check('6.4 公式压缩后二次解析稳定（不再产生 UNPAIRED_DOLLAR）', () => {
  for (const sample of [INLINE_MATH, BLOCK_MATH]) {
    const once = parseRichText(sample);
    const twice = parseRichText(once.plain);
    assert.ok(
      !twice.issues.some((i) => ['UNPAIRED_DOLLAR', 'BLOCK_DELIMITER_RESIDUE'].includes(i.code)),
      `二次解析仍有定界符问题：${JSON.stringify(twice.issues)}`,
    );
  }
});

check('6.3 plain 与 rich 叶子文本逐字一致', () => {
  for (const sample of [HEADER_LINE, INLINE_MATH, BLOCK_MATH, 'a < b > c', 'nested <b>x<i>y</i></b>']) {
    const r = parseRichText(sample);
    assert.strictEqual(plainOf(r.rich), r.plain, `不一致：${sample}`);
  }
});

// ── 7. KaTeX 失败降级 ───────────────────────────────────────────────
check('7.1 无法渲染的 LaTeX 降级为等宽文本且不含 $', () => {
  const { html } = renderRichHtml('bad: $\\badcmd{$');
  assert.ok(!html.includes('$'), html);
});

check('7.2 表格 HTML 里的 LaTeX 就地渲染', () => {
  const html = renderMathInHtmlString('<td>$1.0 \\cdot 10^{20}$</td>');
  assert.ok(html.includes('katex'), html);
  assert.ok(!html.includes('$'), html);
});

check('7.3 表格 HTML 无 $ 时原样返回（零开销）', () => {
  const src = '<td>plain</td>';
  assert.strictEqual(renderMathInHtmlString(src), src);
});

// ── 结果 ────────────────────────────────────────────────────────────
console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
