// M4 媒体策略单测（零依赖 runner，见 tests/richtext.spec.ts 注释）。
//
// 用户实测（问题③）："原件媒体里很多『不可用的标签 / 未找到任何可展示原件资产』，
// 下面介绍还是 `$$ \operatorname{Attention}…\tag{1} $$` 未转义。"
//
// 实测数据（paper 7 的 14 条 media）：5 条公式的 `extracted.latex` **是 null**，
// 但公式本体**就在 `caption` 里**（`$$…\tag{1}$$`）。旧策略只看
// `extracted.table_html/latex`，于是这 5 条被判 unavailable —— 而正文又会把
// caption 当普通题注渲染，于是用户同时看到"不可用"和"未转义的 LaTeX"。
//
// 锁住的口径：caption 里**确实是公式**时，它本身就是一份"再排版/提取"表示；
// caption 是普通文字时**不许**当成公式（不得无中生有）。
//
// 运行：npm run test:policy

import assert from 'assert';
import { latexFromCaption, resolveMediaPolicy } from '../lib/sourcePolicy';
import type { Media } from '../lib/contracts';

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

const FORMULA_CAPTION = '$$\n\\operatorname{Attention} (Q, K, V) = \\operatorname{softmax} (\\frac {Q K ^ {T}}{\\sqrt {d _ {k}}}) V\\tag{1}\n$$';

const BASE_PROVENANCE = {
  source_document_id: 'sd1',
  representation: 'extracted',
  verification: 'unverified',
  source_sha256: 'x',
  raw_asset_id: null,
  transform: '',
  renderer_version: '',
};

type MediaOver = Partial<Omit<Media, 'provenance'>> & { provenance?: Partial<Media['provenance']> };

function media(over: MediaOver): Media {
  const base = {
    id: 'm1',
    paper_id: 7,
    revision_id: 'r1',
    kind: 'equation',
    caption: '',
    anchor_ids: [],
    original_asset_ids: [],
    extracted: { table_html: null, latex: null } as Media['extracted'],
  };
  // provenance 允许局部覆盖（否则调用方要写全 7 个字段）
  return {
    ...base,
    ...over,
    provenance: { ...BASE_PROVENANCE, ...((over.provenance as object) || {}) },
  } as unknown as Media;
}

console.log('sourcePolicy 测试');

check('1. 公式 caption 里带 LaTeX → 识别为可渲染表示', () => {
  assert.strictEqual(latexFromCaption(FORMULA_CAPTION).length > 0, true);
  assert.strictEqual(latexFromCaption('Table 2: Our results on WMT 2014.'), '');
  assert.strictEqual(latexFromCaption(''), '');
  assert.strictEqual(latexFromCaption(null), '');
});

check('2. extracted.latex 为空但 caption 是公式 → 不再判"不可用"', () => {
  const policy = resolveMediaPolicy(media({ caption: FORMULA_CAPTION }), []);
  assert.strictEqual(policy.default_mode, 'extracted', JSON.stringify(policy));
  assert.strictEqual(policy.label.includes('不可用'), false, policy.label);
});

check('3. caption 是普通文字且无资产 → 仍然如实"不可用"（不许无中生有）', () => {
  const policy = resolveMediaPolicy(media({ caption: 'Figure 1: The Transformer architecture.' }), []);
  assert.strictEqual(policy.default_mode, 'unavailable');
  assert.ok(policy.warnings.length > 0);
});

check('4. 表格 title_html 提取表示不受影响（回归）', () => {
  const policy = resolveMediaPolicy(
    media({ kind: 'table', caption: '', extracted: { table_html: '<table><tr><td>1</td></tr></table>' } as Media['extracted'] }),
    [],
  );
  assert.strictEqual(policy.default_mode, 'extracted');
});

check('5. 真实 source 上的 synthetic 仍然拒绝展示（回归）', () => {
  const policy = resolveMediaPolicy(
    media({
      provenance: { source_document_id: 'sd1', representation: 'synthetic', verification: 'synthetic' },
      caption: FORMULA_CAPTION,
    }),
    [],
  );
  assert.strictEqual(policy.default_mode, 'unavailable', JSON.stringify(policy));
});

check('6. 有原件资产时仍优先原件（回归）', () => {
  const policy = resolveMediaPolicy(
    media({
      kind: 'figure',
      caption: FORMULA_CAPTION,
      original_asset_ids: ['a1'],
      provenance: { source_document_id: 'sd1', representation: 'pdf_crop', verification: 'source_bound' },
    }),
    [{ id: 'a1' } as never],
  );
  assert.strictEqual(policy.default_mode, 'original');
  assert.deepStrictEqual(policy.original_asset_ids, ['a1']);
});

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
