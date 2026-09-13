// M2 证据 verdict 四分类单测（零依赖 runner）。
// 样本全部取自 paper 7 实测形态（含后端 reasons 原文）。运行：npm run test:verdict

import assert from 'assert';
import {
  classifyVerdict,
  isNotApplicable,
  parseReasons,
} from '../lib/evidenceVerdict';

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

// —— paper 7 实测形态 ——
const NON_CLAIM = {
  decision: 'unverified',
  semantic_status: 'insufficient',
  reasons: [
    { code: 'quote_mismatch', message: '模型给出的引用块不含该引用，已按全文逐字重新定位到块 4bd2f641（匹配方式 exact）' },
    { code: 'unsupported_entailment', message: '该句不是研究发现（参考文献/许可声明/页脚），不进入事实层' },
  ],
};
const CONTRADICTION = {
  decision: 'contested',
  semantic_status: 'contradicts',
  reasons: [
    { code: 'contradiction', message: '模型语义判定：原文明确指出 Adam 优化器的 β₁ = 0.9，而陈述声称 β₁ = 0，二者数值直接矛盾。' },
  ],
};
const REJECTED_OTHER = {
  decision: 'rejected',
  semantic_status: 'supports',
  reasons: [{ code: 'numeric_mismatch', message: '陈述含数字但无任何证据' }],
};
const INSUFFICIENT = {
  decision: 'unverified',
  semantic_status: 'insufficient',
  reasons: [{ code: 'unsupported_entailment', message: '无 LLM，无法确认语义支持（规则重合度不足）' }],
};

console.log('evidenceVerdict 测试');

check('1. 非研究发现：参考文献 reasons → non_claim（不得显示"证据不足"）', () => {
  const v = classifyVerdict(NON_CLAIM)!;
  assert.strictEqual(v.category, 'non_claim');
  assert.strictEqual(v.label, '非研究发现');
  assert.ok(!v.label.includes('证据不足'), v.label);
  assert.ok(v.explain.includes('不代表证据不足'), v.explain);
});

check('2. 真矛盾：contradicts → contradiction', () => {
  const v = classifyVerdict(CONTRADICTION)!;
  assert.strictEqual(v.category, 'contradiction');
  assert.strictEqual(v.label, '真矛盾');
  assert.ok(v.reasons[0]!.message.includes('β₁'), '理由要原样保留');
});

check('3. 有支持但未过其他检查：supports + rejected → rejected_other', () => {
  const v = classifyVerdict(REJECTED_OTHER)!;
  assert.strictEqual(v.category, 'rejected_other');
  assert.strictEqual(v.label, '有支持但未通过其他检查');
});

check('4. 普通证据不足 → insufficient', () => {
  const v = classifyVerdict(INSUFFICIENT)!;
  assert.strictEqual(v.category, 'insufficient');
  assert.strictEqual(v.label, '证据不足');
});

check('5. 反向断言：non_claim 的解释文案里不出现"证据不足"作为结论', () => {
  const v = classifyVerdict(NON_CLAIM)!;
  assert.ok(!v.explain.startsWith('现有证据不足'), v.explain);
  assert.notStrictEqual(v.category, 'insufficient');
});

check('6. 未知组合回落 insufficient 且 reasons 一条不丢', () => {
  const weird = {
    decision: 'unverified',
    semantic_status: 'supports',
    reasons: [{ code: 'x', message: 'm1' }, { code: 'y', message: 'm2' }],
  };
  const v = classifyVerdict(weird)!;
  assert.strictEqual(v.category, 'insufficient');
  assert.strictEqual(v.reasons.length, 2);
});

check('7. 裸字符串 reasons 解析"码：文案"，解析不了也不丢', () => {
  const parsed = parseReasons(['quote_mismatch：引用的原文片段在该 block 中找不到', '就是一段没有冒号的说明']);
  assert.deepStrictEqual(parsed[0], { code: 'quote_mismatch', message: '引用的原文片段在该 block 中找不到' });
  assert.strictEqual(parsed[1]!.code, 'UNKNOWN');
  assert.strictEqual(parsed[1]!.message, '就是一段没有冒号的说明');
});

check('8. 已通过的验证不渲染本徽标（返回 null）', () => {
  assert.strictEqual(
    classifyVerdict({ decision: 'verified', semantic_status: 'supports', reasons: [] }),
    null,
  );
});

check('9. 没有 validation / 空对象 → null（调用方不渲染）', () => {
  assert.strictEqual(classifyVerdict(null), null);
  assert.strictEqual(classifyVerdict(undefined), null);
  assert.strictEqual(classifyVerdict({}), null);
  assert.strictEqual(classifyVerdict([]), null);
});

check('10. 无 reasons 的 insufficient 标记为"不适用"（M9 复用）', () => {
  const v = classifyVerdict({ decision: 'unverified', semantic_status: 'insufficient', reasons: [] })!;
  assert.ok(isNotApplicable(v.category, v.reasons));
});

check('11. 展开面板文本与后端 reasons 逐字相等', () => {
  const v = classifyVerdict(NON_CLAIM)!;
  assert.strictEqual(v.reasons[0]!.message, NON_CLAIM.reasons[0]!.message);
  assert.strictEqual(v.reasons[1]!.message, NON_CLAIM.reasons[1]!.message);
});

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
