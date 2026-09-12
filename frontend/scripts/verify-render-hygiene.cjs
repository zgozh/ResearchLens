// M11 文本卫生门禁（**真实语料**版）：把线上 API 返回的论文文本整批喂给渲染内核，
// 断言"渲染后不留未转义残留"。
//
// 与纯函数门禁的关系：
//   - `npm run test:rich` 用**固定语料**跑（离线、无依赖、CI 常绿）；
//   - 本脚本用**线上真实论文**跑（需要 backend 在跑），用来发现"语料里还没有的新脏模式"。
//
// 用法：先 `npm run test:rich`（生成 .tmp/richtext-test），再
//   node scripts/verify-render-hygiene.cjs [paper_id ...]
const path = require('node:path');

const KERNEL = path.resolve(__dirname, '../.tmp/richtext-test/lib/richtext.js');
const { renderRichHtml } = require(KERNEL);

const BASE = process.env.RL_API || 'http://localhost:8002';
const PAPERS = process.argv.slice(2).map(Number).filter(Boolean);
const TARGETS = PAPERS.length > 0 ? PAPERS : [7, 10];

const WATCH_KEYS = new Set([
  'text', 'body', 'summary', 'caption', 'abstract', 'latex', 'quote',
  'statement', 'answer', 'note', 'title', 'subtitle', 'table_html',
]);

function walk(value, pathParts, out) {
  if (typeof value === 'string') {
    if (WATCH_KEYS.has(pathParts[pathParts.length - 1]) && value.trim()) {
      out.push({ path: pathParts.join('.'), text: value });
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((v, i) => walk(v, [...pathParts, String(i)], out));
    return;
  }
  if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) walk(v, [...pathParts, k], out);
  }
}

async function scanPaper(paperId) {
  const found = [];
  for (const ep of ['', '/claims', '/statements', '/presentation', '/graph']) {
    const url = `${BASE}/api/papers/${paperId}${ep}`;
    try {
      const res = await fetch(url);
      if (!res.ok) continue;
      walk(await res.json(), [ep || '/'], found);
    } catch {
      /* 端点不可用就跳过（不影响卫生扫描的主结论） */
    }
  }
  const seen = new Set();
  let dollar = 0;
  let escapedTag = 0;
  let tagCmd = 0;
  let katex = 0;
  const offenders = [];
  for (const s of found) {
    if (seen.has(s.text)) continue;
    seen.add(s.text);
    const { html } = renderRichHtml(s.text, { kind: 'body' });
    const literalDollars = (s.text.match(/\\\$/g) || []).length;
    const renderedDollars = (html.match(/\$/g) || []).length;
    const over = Math.max(0, renderedDollars - literalDollars);
    const esc = (html.match(/&lt;\/?(sup|sub|i|b|br)&gt;/gi) || []).length;
    const tag = (html.match(/\\tag/g) || []).length;
    dollar += over;
    escapedTag += esc;
    tagCmd += tag;
    katex += (html.match(/class="katex/g) || []).length;
    if ((over || esc || tag) && offenders.length < 8) {
      offenders.push({ path: s.path, over, esc, tag, sample: html.slice(0, 140) });
    }
  }
  console.log(
    `paper ${paperId}：文本段 ${seen.size}｜多余 $ ${dollar}｜被转义标签 ${escapedTag}｜` +
      `残留 \\tag ${tagCmd}｜渲染 KaTeX ${katex}`,
  );
  for (const o of offenders) {
    console.log(`   - ${o.path} ($=${o.over} tag=${o.esc} \\tag=${o.tag}) ${o.sample.replace(/\n/g, ' ')}`);
  }
  return dollar + escapedTag + tagCmd;
}

async function main() {
  let bad = 0;
  for (const p of TARGETS) bad += await scanPaper(p);
  if (bad > 0) {
    console.log(`结论：仍有 ${bad} 处未转义残留 ❌`);
    process.exit(1);
  }
  console.log('结论：真实语料渲染后无未转义残留 ✅');
}

main().catch((e) => {
  console.error('门禁执行失败：', e);
  process.exit(2);
});
