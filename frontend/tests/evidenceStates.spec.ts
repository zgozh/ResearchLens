// R4-M1 证据状态单测（零依赖 runner，见 tests/richtext.spec.ts 注释）。
//
// 锁住两件事：
//   1. 逐条降级 —— 一条失败**不许**清空已经取回的证据（旧 bug：全清 → 显示"暂无证据"）；
//   2. 空态三分 —— 尚未抽取 / 确无关联证据 / 拉取失败，文案不同、用户能据此行动。
// 运行：npm run test:evidence

import assert from 'assert';
import {
  explainEmptyEvidence,
  failureCount,
  settleEvidence,
  unreviewedDetail,
  unreviewedLabel,
  type EvidenceSlot,
} from '../lib/evidenceStates';

let passed = 0;
function check(name: string, fn: () => void) {
  try {
    fn();
    passed++;
    console.log(`  ok  ${name}`);
  } catch (e) {
    console.error(`  FAIL ${name}`);
    throw e;
  }
}

const ev = (id: string) => ({ evidence: { id } as never, validation: null });

console.log('evidenceStates');

// ------------------------------------------------------------- 逐条降级

check('全部成功 → 三条都在，无错误', () => {
  const slots = settleEvidence(['a', 'b', 'c'], [
    { status: 'fulfilled', value: ev('a') },
    { status: 'fulfilled', value: ev('b') },
    { status: 'fulfilled', value: ev('c') },
  ]);
  assert.strictEqual(slots.length, 3);
  assert.strictEqual(failureCount(slots), 0);
  assert.ok(slots.every((s) => s.evidence !== null && s.error === null));
});

check('**中间一条失败 → 另外两条照常显示**（旧实现在这里清空全部）', () => {
  const slots = settleEvidence(['a', 'b', 'c'], [
    { status: 'fulfilled', value: ev('a') },
    { status: 'rejected', reason: new Error('500') },
    { status: 'fulfilled', value: ev('c') },
  ]);
  assert.strictEqual(slots.length, 3, '失败的条目必须留在列表里，不能消失');
  assert.strictEqual(slots[0]!.evidence !== null, true);
  assert.strictEqual(slots[1]!.evidence, null);
  assert.strictEqual(slots[1]!.error, '500');
  assert.strictEqual(slots[2]!.evidence !== null, true);
  assert.strictEqual(failureCount(slots), 1);
});

check('失败原因不是 Error 时也给可读文案（不留空）', () => {
  const slots = settleEvidence(['a'], [{ status: 'rejected', reason: 'oops' }]);
  assert.ok(slots[0]!.error);
  assert.strictEqual(typeof slots[0]!.error, 'string');
});

check('结果数量少于 id 数量时，缺的那条按失败处理（不静默丢）', () => {
  const slots = settleEvidence(['a', 'b'], [{ status: 'fulfilled', value: ev('a') }]);
  assert.strictEqual(slots.length, 2);
  assert.strictEqual(slots[1]!.evidence, null);
  assert.ok(slots[1]!.error);
});

// ------------------------------------------------------------- 空态三分

check('拉取失败 → "证据拉取失败"（可重试），绝不说"暂无证据"', () => {
  const e = explainEmptyEvidence({ hasIds: true, fetchFailed: true, claimsState: 'ready' });
  assert.strictEqual(e.cause, 'fetch_failed');
  assert.ok(e.title.includes('拉取失败'));
  assert.ok(e.detail.includes('重试'));
});

check('无关联 id + claims 仍在抽取 → "正在抽取证据…"', () => {
  for (const state of ['pending', 'unknown'] as const) {
    const e = explainEmptyEvidence({ hasIds: false, fetchFailed: false, claimsState: state });
    assert.strictEqual(e.cause, 'not_extracted_yet', state);
    assert.ok(e.title.includes('正在抽取'), e.title);
  }
});

check('无关联 id + claims 已就绪 → "该断言暂无关联证据"', () => {
  const e = explainEmptyEvidence({ hasIds: false, fetchFailed: false, claimsState: 'ready' });
  assert.strictEqual(e.cause, 'no_linked_evidence');
  assert.ok(e.title.includes('暂无关联证据'), e.title);
});

check('优先级：拉取失败压过"尚未抽取"（别让用户白等）', () => {
  const e = explainEmptyEvidence({ hasIds: false, fetchFailed: true, claimsState: 'pending' });
  assert.strictEqual(e.cause, 'fetch_failed');
});

check('三种成因的文案两两不同（否则等于没区分）', () => {
  const a = explainEmptyEvidence({ hasIds: false, fetchFailed: false, claimsState: 'pending' });
  const b = explainEmptyEvidence({ hasIds: false, fetchFailed: false, claimsState: 'ready' });
  const c = explainEmptyEvidence({ hasIds: true, fetchFailed: true });
  const titles = new Set([a.title, b.title, c.title]);
  assert.strictEqual(titles.size, 3, `${a.title} / ${b.title} / ${c.title}`);
});

// --------------------------------------------------------- 未判定成因细分

check('未配置模型 → 提示"未配置"，而不是笼统的"未判定"', () => {
  const msg = unreviewedDetail([{ code: 'semantic_unavailable', message: '未配置 LLM' }]);
  assert.ok((msg as string).includes('未配置'), msg);
});

check('超时 → 提示可重试', () => {
  const msg = unreviewedDetail([{ code: 'semantic_timeout', message: '超时' }]);
  assert.ok((msg as string).includes('超时'), msg);
  assert.ok((msg as string).includes('重试'), msg);
});

check('调用失败/输出非法 → 如实说明', () => {
  const msg = unreviewedDetail([{ code: 'semantic_failed', message: '输出非法' }]);
  assert.ok((msg as string).includes('失败') || msg.includes('非法'), msg);
});

check('旧数据（认不出的码）→ 不编造原因，指向理由列表', () => {
  const msg = unreviewedDetail([{ code: 'external_unavailable', message: '语义未判定' }]);
  assert.ok((msg as string).includes('未细分'), msg);
  const empty = unreviewedDetail([]);
  assert.ok((empty as string).includes('未细分'), empty);
});

check('unreviewedLabel 只在 semantic_status=unreviewed 时给文案', () => {
  assert.strictEqual(unreviewedLabel(null), null);
  assert.strictEqual(unreviewedLabel({ semantic_status: 'supports' }), null);
  const label = unreviewedLabel({
    semantic_status: 'unreviewed',
    reasons: [{ code: 'semantic_timeout', message: '超时' }],
  });
  assert.ok(label && label.includes('超时'), label ?? '');
});

check('unreviewedLabel 兼容裸字符串形态的 reasons（与 VerdictBadge 同源解析）', () => {
  const label = unreviewedLabel({
    semantic_status: 'unreviewed',
    reasons: ['semantic_unavailable：未配置 LLM，语义未判定'],
  });
  assert.ok(label && label.includes('未配置'), label ?? '');
});

// ------------------------------------------------- M2：sticky 跟随滚动

check('R4-M2：桌面 rail 必须 sticky 且自身限高滚动（否则内容贴在超高盒子顶部）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'components/evidence/EvidenceDrawer.tsx');
  const source = fs.readFileSync(file, 'utf8');
  // 旧写法 `h-full ... overflow-y-auto` 会让面板高度等于左列那根很高的行高，
  // 内容永远贴顶，页面往下滚就看不见 —— 用户描述的正是这个现象。
  assert.ok(source.includes('lg:sticky'), '桌面 rail 必须 sticky');
  assert.ok(source.includes('lg:self-start'), '必须解除 grid 的 stretch（否则 sticky 无效）');
  assert.ok(source.includes('maxHeight'), '必须限高，否则面板被拉成整列高度');
  assert.ok(source.includes('overflow-y-auto'), '内容滚动要在面板内部');
  assert.ok(
    !/hidden h-full w-80 shrink-0 overflow-y-auto/.test(source),
    '旧的全高写法必须已被替换',
  );
});

check('R4-M2：移动抽屉分支不含 sticky（lg 以下行为不变）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'components/evidence/EvidenceDrawer.tsx');
  const source = fs.readFileSync(file, 'utf8');
  const fixed = source.indexOf('fixed inset-0 z-50 lg:hidden');
  assert.ok(fixed > 0, '移动抽屉应仍用 fixed 覆盖层');
  const mobileBlock = source.slice(fixed, fixed + 900);
  assert.ok(!mobileBlock.includes('sticky'), '移动分支不应引入 sticky');
});

check('R4-M1：抽屉用 allSettled（不允许 Promise.all + 清空）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'components/evidence/EvidenceDrawer.tsx');
  const source = fs.readFileSync(file, 'utf8');
  assert.ok(source.includes('Promise.allSettled'), '必须逐条降级');
  assert.ok(
    !/Promise\.all\(evidence_ids/.test(source),
    '旧的全清写法必须已被替换（一条失败会清空全部证据）',
  );
  assert.ok(source.includes('VerdictBadge'), '抽屉要挂与列表同源的四分类徽标');
});

check('R4-M9：GraphView 证据节点挂四分类徽标（此前只有 support_status 一个词）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'components/views/GraphView.tsx');
  const source = fs.readFileSync(file, 'utf8');
  assert.ok(source.includes('VerdictBadge'), '图谱证据节点要挂徽标');
  assert.ok(
    /VerdictBadge validation=\{selected\.props\?\.validation\}/.test(source),
    '徽标数据必须取节点 props.validation（后端 R4-M9 新增的三件套）',
  );
  assert.ok(
    source.includes("from '@/components/evidence/VerdictBadge'"),
    '徽标组件要与证据链/抽屉**同源**，不许另造一套',
  );
});

console.log(`\nevidenceStates: ${passed} 项全部通过`);
