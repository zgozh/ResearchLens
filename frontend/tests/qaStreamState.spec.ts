// R4-M4 QA SSE 生命周期单测（零依赖 runner，见 tests/richtext.spec.ts 注释）。
//
// 锁住线上现象：「回答被中断 · 置信度 Low」到底是怎么来的、修完之后还会不会来。
// 三条必须成立：
//   1. 没有 final 的"流正常结束"**不再**等于 completed，而是 recovering；
//   2. final 帧解析失败必须**可观测**（droppedFrames + warn），不许静默；
//   3. 恢复期间迟到的 final 仍可采纳（answer_id 一致），不再被一次性锁死。
// 运行：npm run test:qa

import assert from 'assert';
import {
  applyCancelled,
  applyFrame,
  applyRecovered,
  applyRecoveryFailed,
  applyTransportEnd,
  applyTransportFailure,
  initProgress,
  isBusy,
  isSettled,
  noteDroppedFrame,
  shouldAcceptLateFinal,
} from '../lib/qaStreamState';

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

console.log('qaStreamState');

// --------------------------------------------------------------- 状态机

check('初始态是 connecting 且无结果', () => {
  const p = initProgress();
  assert.strictEqual(p.state, 'connecting');
  assert.strictEqual(p.gotFinal, false);
  assert.strictEqual(p.droppedFrames, 0);
  assert.strictEqual(p.answerId, null);
});

check('meta 帧带出 answer_id（恢复链的钥匙）', () => {
  const p = applyFrame(initProgress(), {
    type: 'meta',
    data: { scope: { paper_id: 1 }, answer_id: 'ans-1' },
  });
  assert.strictEqual(p.answerId, 'ans-1');
});

check('普通帧把 connecting 推进到 streaming', () => {
  const p = applyFrame(initProgress(), { type: 'status', data: {} });
  assert.strictEqual(p.state, 'streaming');
});

check('final 帧 → completed 且 gotFinal=true', () => {
  let p = initProgress();
  p = applyFrame(p, { type: 'status', data: {} });
  p = applyFrame(p, { type: 'final', data: { answer: {} } });
  assert.strictEqual(p.state, 'completed');
  assert.strictEqual(p.gotFinal, true);
  assert.ok(isSettled(p));
  assert.ok(!isBusy(p));
});

check('**流读完但没有 final → recovering，不是 completed**（本次修复的核心）', () => {
  let p = initProgress();
  p = applyFrame(p, { type: 'meta', data: { answer_id: 'a1' } });
  p = applyFrame(p, { type: 'sentence', data: {} });
  p = applyTransportEnd(p);
  assert.strictEqual(p.state, 'recovering', '没有结果就不能说"完成"');
  assert.strictEqual(p.gotFinal, false);
  assert.ok(isBusy(p), '恢复中仍算进行中（输入要禁用）');
  assert.ok(!isSettled(p));
});

check('有 final 时流结束仍是 completed', () => {
  let p = initProgress();
  p = applyFrame(p, { type: 'final', data: {} });
  p = applyTransportEnd(p);
  assert.strictEqual(p.state, 'completed');
});

check('error 帧 → failed', () => {
  const p = applyFrame(initProgress(), { type: 'error', data: { message: 'boom' } });
  assert.strictEqual(p.state, 'failed');
  assert.strictEqual(p.gotError, true);
});

check('已有 final 时迟到的 error 不改写结果', () => {
  let p = initProgress();
  p = applyFrame(p, { type: 'final', data: {} });
  p = applyFrame(p, { type: 'error', data: {} });
  assert.strictEqual(p.state, 'completed');
  assert.strictEqual(p.gotError, false);
});

check('error 之后到达的 final 以 final 为准', () => {
  let p = initProgress();
  p = applyFrame(p, { type: 'error', data: {} });
  assert.strictEqual(p.state, 'failed');
  p = applyFrame(p, { type: 'final', data: {} });
  assert.strictEqual(p.state, 'completed');
});

check('传输异常在无 final 时 → failed', () => {
  const p = applyTransportFailure(applyFrame(initProgress(), { type: 'status', data: {} }));
  assert.strictEqual(p.state, 'failed');
});

check('传输异常但已有 final → 保持 completed', () => {
  let p = applyFrame(initProgress(), { type: 'final', data: {} });
  p = applyTransportFailure(p);
  assert.strictEqual(p.state, 'completed');
});

// --------------------------------------------------------- 丢帧可观测

check('**解析失败的帧必须计数并告警**（以前是静默丢弃 → 无法对账）', () => {
  let warned = 0;
  const original = console.warn;
  console.warn = () => { warned++; };
  try {
    let p = initProgress();
    assert.strictEqual(p.droppedFrames, 0);
    p = noteDroppedFrame(p, '{"answer": {"text": "被截断');
    assert.strictEqual(p.droppedFrames, 1);
    p = noteDroppedFrame(p, '{"x":');
    assert.strictEqual(p.droppedFrames, 2);
    assert.strictEqual(warned, 2, '每一次丢弃都必须留痕');
  } finally {
    console.warn = original;
  }
});

check('丢帧计数不改变已确定的终态', () => {
  let p = applyFrame(initProgress(), { type: 'final', data: {} });
  p = noteDroppedFrame(p, 'garbage');
  assert.strictEqual(p.state, 'completed');
  assert.strictEqual(p.droppedFrames, 1);
});

check('final 帧解析失败 → 走 recovering（配合调用方的恢复链）', () => {
  // 模拟：final 那一帧 JSON 坏了 → 调用方只调用 noteDroppedFrame 而不 applyFrame
  let p = initProgress();
  p = applyFrame(p, { type: 'meta', data: { answer_id: 'a1' } });
  p = applyFrame(p, { type: 'sentence', data: {} });
  p = noteDroppedFrame(p, '{"answer": {"text": "截断');
  p = applyTransportEnd(p);
  assert.strictEqual(p.state, 'recovering');
  assert.strictEqual(p.droppedFrames, 1);
  assert.strictEqual(p.answerId, 'a1', 'answer_id 仍可用于取回');
});

// --------------------------------------------------------- 恢复链

check('恢复成功 → completed', () => {
  let p = applyTransportEnd(applyFrame(initProgress(), { type: 'status', data: {} }));
  assert.strictEqual(p.state, 'recovering');
  p = applyRecovered(p);
  assert.strictEqual(p.state, 'completed');
  assert.ok(isSettled(p));
});

check('恢复失败 → failed（不是一个"回答"）', () => {
  let p = applyTransportEnd(applyFrame(initProgress(), { type: 'status', data: {} }));
  p = applyRecoveryFailed(p);
  assert.strictEqual(p.state, 'failed');
  assert.ok(!isSettled(p), '失败绝不能被当成结果');
});

// --------------------------------------------------------- 迟到 final

check('**恢复期间迟到的 final 仍可采纳**（answer_id 一致）', () => {
  let p = initProgress();
  p = applyFrame(p, { type: 'meta', data: { answer_id: 'a1' } });
  p = applyTransportEnd(p);
  assert.strictEqual(p.state, 'recovering');
  assert.strictEqual(shouldAcceptLateFinal(p, 'a1'), true, '旧实现被一次性锁挡掉 → 永远"被中断"');
});

check('answer_id 不一致的迟到 final 不采纳（避免串台）', () => {
  let p = initProgress();
  p = applyFrame(p, { type: 'meta', data: { answer_id: 'a1' } });
  p = applyTransportEnd(p);
  assert.strictEqual(shouldAcceptLateFinal(p, 'a2'), false);
});

check('已拿到 final 后不再接受任何 final', () => {
  let p = applyFrame(initProgress(), { type: 'final', data: {} });
  assert.strictEqual(shouldAcceptLateFinal(p, 'a1'), false);
});

check('无从比对 answer_id 时以最新为准（不因缺字段卡死）', () => {
  const p = applyTransportEnd(initProgress()); // 连 meta 都没到
  assert.strictEqual(p.answerId, null);
  assert.strictEqual(shouldAcceptLateFinal(p, 'a9'), true);
});

check('取消是终态，且不算 busy 也不算 settled', () => {
  const p = applyCancelled(applyFrame(initProgress(), { type: 'status', data: {} }));
  assert.strictEqual(p.state, 'cancelled');
  assert.ok(!isBusy(p));
  assert.ok(!isSettled(p));
});

// ------------------------------------------------- 文案纪律（源码扫描）

check('QAView 不再出现拒答/中断类文案（R4-M4 文案纪律）', () => {
  // 这些字符串是**用户可见文案**，不是注释：注释里出现"拒答"是允许的（说明历史），
  // 所以先剥掉注释行再断言。
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  // npm 脚本的 cwd 就是 frontend/（编译产物在 .tmp/ 下，用 __dirname 会算错层级）。
  const file = path.resolve(process.cwd(), 'components/views/QAView.tsx');
  const source = fs.readFileSync(file, 'utf8');
  const code = source
    .split('\n')
    .filter((line: string) => {
      const t = line.trim();
      return !t.startsWith('//') && !t.startsWith('*') && !t.startsWith('/*');
    })
    .join('\n');
  for (const banned of ['拒绝编造', '已拒答', '被中断', '没有生成内容']) {
    assert.ok(
      !code.includes(banned),
      `QAView 用户可见文案不得再出现「${banned}」（决策 1：没有拒答，也不把连接异常写成回答）`,
    );
  }
  assert.ok(code.includes('每个问题都会得到回答'), '空态要说明"每个问题都有回答 + 置信度"');
});

check('QAView 不再产出 mode=interrupted 的假回答', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  // npm 脚本的 cwd 就是 frontend/（编译产物在 .tmp/ 下，用 __dirname 会算错层级）。
  const file = path.resolve(process.cwd(), 'components/views/QAView.tsx');
  const source = fs.readFileSync(file, 'utf8');
  assert.ok(!source.includes("mode: 'interrupted'"), '该 mode 不是契约里的取值，且会把连接异常伪装成回答');
  assert.ok(source.includes('transportError'), '连接异常要用独立字段如实呈现');
});

console.log(`\nqaStreamState: ${passed} 项全部通过`);
