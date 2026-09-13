// M8 指标解析单测（零依赖 runner，见 tests/richtext.spec.ts 注释）。
//
// 直接锁住线上那个 bug：canonical `MetricValue` **对象**被当数字用 → 全部渲染成"未评测"。
// 运行：npm run test:eval

import assert from 'assert';
import {
  buildMetricViews,
  parseMetricValue,
  findConflicts,
  parseOverall,
  reasonText,
} from '../lib/evalMetrics';

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

// paper 7 实测（/exhibits 的 canonical 形态：list[MetricEntry]，value 是对象）
const CANONICAL = [
  { name: 'source_asset_coverage', value: { status: 'measured', value: 0.3571, unit: 'ratio' } },
  { name: 'anchor_page_accuracy', value: { status: 'measured', value: 1.0, unit: 'ratio' } },
  { name: 'quote_exact_rate', value: { status: 'measured', value: 1.0, unit: 'ratio' } },
  { name: 'support_precision', value: { status: 'proxy', value: 0.6667, unit: 'ratio' } },
  {
    name: 'anchor_region_hit_rate',
    value: { status: 'not_evaluated', value: null, reason: 'source_pdf_has_no_coordinate_rects' },
  },
  { name: 'input_tokens', value: { status: 'measured', value: 1502, unit: 'tokens' } },
];

const LEGACY = {
  source_asset_coverage: 0.3571,
  anchor_page_accuracy: 1.0,
  quote_exact_rate: 1.0,
  support_precision: 0.6667,
  anchor_region_hit_rate: null,
  // legacy 独有的键：应当被补进来
  recovery_success_rate: 1.0,
  not_evaluated: ['anchor_region_hit_rate'],
  not_evaluated_reasons: { anchor_region_hit_rate: 'source_pdf_has_no_coordinate_rects' },
  overall_score_available: false,
  ai_overall_score: 86.67,
  ai_overall_score_available: true,
  overall_score_basis: 'ai_judge',
};

console.log('evalMetrics 测试');

check('1. 四种输入形态解析出同一个值', () => {
  assert.strictEqual(parseMetricValue(0.3571)!.value, 0.3571);
  assert.strictEqual(parseMetricValue({ status: 'measured', value: 0.3571 })!.value, 0.3571);
  assert.strictEqual(parseMetricValue('0.3571')!.value, 0.3571);
  assert.strictEqual(parseMetricValue(null)!.status, 'not_evaluated');
});

check('2. 回归锁：canonical 对象优先于 legacy 数字（旧 bug 是对象挡住数字）', () => {
  const views = buildMetricViews(CANONICAL, LEGACY);
  const byName = new Map(views.map((v) => [v.name, v]));
  assert.strictEqual(byName.get('source_asset_coverage')!.value, 0.3571);
  assert.strictEqual(byName.get('source_asset_coverage')!.source, 'canonical');
  assert.strictEqual(byName.get('quote_exact_rate')!.value, 1.0);
  // 四个实测值全部真的取到了（而不是 null）
  assert.strictEqual(byName.get('anchor_page_accuracy')!.value, 1.0);
  assert.strictEqual(byName.get('support_precision')!.value, 0.6667);
  assert.strictEqual(byName.get('support_precision')!.status, 'proxy');
});

check('3. canonical 说未评测、legacy 有值 → 显示值（否则面板一片"未评测"）', () => {
  // 实测 paper 7：持久化报告把 10 项标成未评测，而现算结果有真值。
  // 有值优先；同时 findConflicts 会把"两源不一致"显式报出来（不静默挑一个）。
  const views = buildMetricViews(CANONICAL, { ...LEGACY, anchor_region_hit_rate: 0.5 });
  const m = views.find((v) => v.name === 'anchor_region_hit_rate')!;
  assert.strictEqual(m.value, 0.5);
  assert.strictEqual(m.source, 'legacy');
  // 两源都不给值的键仍是未评测
  const none = buildMetricViews(CANONICAL, {}) .find((v) => v.name === 'anchor_region_hit_rate')!;
  assert.strictEqual(none.status, 'not_evaluated');
  assert.strictEqual(none.reason, 'source_pdf_has_no_coordinate_rects');
});

check('3b. canonical 有值 → 不被 legacy 覆盖（权威仍是持久化报告）', () => {
  const views = buildMetricViews(CANONICAL, { ...LEGACY, quote_exact_rate: 0.1 });
  const m = views.find((v) => v.name === 'quote_exact_rate')!;
  assert.strictEqual(m.value, 1.0);
  assert.strictEqual(m.source, 'canonical');
});

check('3c. 两源打架时 findConflicts 必须报出来（不许静默挑一个）', () => {
  // 复刻实测形态：持久化报告说未评测，现算说 1.0
  const conflicts = findConflicts(
    [{ name: 'quote_exact_rate', value: { status: 'not_evaluated', value: null } }],
    { quote_exact_rate: 1.0 },
  );
  const q = conflicts.find((c) => c.name === 'quote_exact_rate');
  assert.ok(q, JSON.stringify(conflicts));
  assert.strictEqual(q!.canonical, null);
  assert.strictEqual(q!.legacy, 1.0);
  // 两源一致时不报冲突
  assert.deepStrictEqual(
    findConflicts([{ name: 'x', value: { status: 'measured', value: 1 } }], { x: 1 }),
    [],
  );
});

check('4. legacy 只补缺：canonical 没有的键被补上', () => {
  const views = buildMetricViews(CANONICAL, LEGACY);
  const m = views.find((v) => v.name === 'recovery_success_rate')!;
  assert.strictEqual(m.value, 1.0);
  assert.strictEqual(m.source, 'legacy');
});

check('5. 元信息键不进指标列表', () => {
  const names = buildMetricViews(CANONICAL, LEGACY).map((v) => v.name);
  for (const meta of ['not_evaluated', 'not_evaluated_reasons', 'proxy', 'golden_id',
    'version', 'warnings', 'overall_score_available', 'ai_overall_score']) {
    assert.ok(!names.includes(meta), `${meta} 不该出现在指标列表里`);
  }
});

check('6. 认不出来的形态标 unparsable，绝不静默当未评测', () => {
  const views = buildMetricViews([{ name: 'weird', value: { foo: 1 } }], {});
  const m = views.find((v) => v.name === 'weird')!;
  assert.strictEqual(m.status, 'unparsable', JSON.stringify(m));
  assert.strictEqual(m.source, 'unparsable');
  assert.strictEqual(m.value, null);
});

check('7. 声称 measured 却没有值 → unparsable（不静默）', () => {
  const views = buildMetricViews([{ name: 'x', value: { status: 'measured' } }], {});
  assert.strictEqual(views[0]!.status, 'unparsable');
});

check('8. 人工口径与 AI 口径分开，互不回退', () => {
  const o = parseOverall(CANONICAL, LEGACY);
  assert.strictEqual(o.human, null, '人工真值未确认时必须为 null');
  assert.strictEqual(o.ai, 86.67);
});

check('9. 原因码翻人话；缺原因时说"原因未记录"而不是留空', () => {
  assert.ok(reasonText('source_pdf_has_no_coordinate_rects').includes('设计上不可测'));
  assert.strictEqual(reasonText(undefined), '原因未记录');
  assert.strictEqual(reasonText('some_new_code'), 'some_new_code');
});

check('10. dict 形态的 canonical 也能解析', () => {
  const views = buildMetricViews(
    { quote_exact_rate: { status: 'measured', value: 0.9 } },
    { quote_exact_rate: 0.1 },
  );
  assert.strictEqual(views.find((v) => v.name === 'quote_exact_rate')!.value, 0.9);
});

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
