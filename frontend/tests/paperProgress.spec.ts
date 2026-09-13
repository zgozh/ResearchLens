// R4-M7 导入进度单测（零依赖 runner，见 tests/richtext.spec.ts 注释）。
//
// 锁住用户报的现象："点了处理之后直接跳转到成果那里，但一开始什么都没解析出，
// 所以是一片空白，我还要等一会然后手动刷新才能看到解析出的东西。"
// 运行：npm run test:progress

import assert from 'assert';
import {
  POLL_BUDGET_MS,
  deriveProgress,
  exhibitsStatusFor,
  nextPollDelay,
  workspaceQuery,
} from '../lib/paperProgress';

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

type Cap = { name: string; state: string; reason: string | null };
const cap = (name: string, state: string, reason: string | null = null) =>
  ({ name, state, reason }) as never;

const ALL_READY: Cap[] = [
  cap('pdf', 'ready'), cap('text', 'ready'), cap('media', 'ready'),
  cap('claims', 'ready'), cap('graph', 'ready'), cap('presentation', 'ready'),
  cap('qa', 'pending'), cap('evaluation', 'ready'),
];

console.log('paperProgress');

// ------------------------------------------------------- 基本推导

check('只有非阻塞域（qa）pending → ready 且**停止轮询**（避免每篇已完成论文空转 8 分钟）', () => {
  // 实测：真实库里 paper 11 的 qa 域长期 pending（问答底库按需构建）。
  // 若"有 pending 就轮询"，每打开一篇已完成论文都会空转 —— 那是轮询风暴。
  const p = deriveProgress({ capabilities: ALL_READY as never, activeJob: null });
  assert.ok(p.domains.length === 8);
  assert.strictEqual(p.pending.length, 1, 'qa 仍会被显示为 pending');
  assert.strictEqual(p.pending[0]!.name, 'qa');
  assert.strictEqual(p.phase, 'ready');
  assert.strictEqual(p.shouldPoll, false);
});

check('没有活跃作业且阻塞域全就绪 → 停止轮询', () => {
  const caps = ALL_READY.filter((c) => c.name !== 'qa');
  const p = deriveProgress({ capabilities: caps as never, activeJob: null });
  assert.strictEqual(p.phase, 'ready');
  assert.strictEqual(p.shouldPoll, false);
  // ratio 按全部 8 个域计数（缺省的 qa 仍算 pending）→ 7/8
  assert.ok(p.ratio > 0.8, String(p.ratio));
});

check('有活跃作业时即使阻塞域已就绪也轮询（阶段细粒度要跟上）', () => {
  const caps = ALL_READY.filter((c) => c.name !== 'qa');
  const p = deriveProgress({
    capabilities: caps as never,
    activeJob: { state: 'running', stage: 'publish', progress: 0.9 } as never,
  });
  assert.strictEqual(p.shouldPoll, true);
});

check('**刚上传：什么都还没解析 → extracting 且必须轮询**（旧实现这里是白屏）', () => {
  const caps: Cap[] = [
    cap('pdf', 'ready'), cap('text', 'pending', '尚未解析'),
    cap('media', 'pending', '尚未构建媒体'), cap('claims', 'pending', '尚未生成'),
  ];
  const p = deriveProgress({ capabilities: caps as never, activeJob: null });
  assert.strictEqual(p.phase, 'extracting');
  assert.strictEqual(p.shouldPoll, true, '必须自动轮询，用户不该手动刷新');
  assert.ok(p.ratio < 1);
  assert.strictEqual(p.currentReason, '尚未解析', '要能显示后端给的原因');
});

check('capabilities 缺失的域按 pending 处理（不假装已就绪）', () => {
  const p = deriveProgress({ capabilities: [cap('pdf', 'ready')] as never, activeJob: null });
  assert.strictEqual(p.domains.length, 8);
  const text = p.domains.find((d) => d.name === 'text')!;
  assert.strictEqual(text.state, 'pending');
  assert.strictEqual(text.done, false);
  assert.strictEqual(p.phase, 'extracting');
});

check('capabilities 为 null → 不崩，按全 pending 处理', () => {
  const p = deriveProgress({ capabilities: null, activeJob: null });
  assert.strictEqual(p.phase, 'extracting');
  assert.strictEqual(p.ratio, 0);
});

check('分域顺序固定为流水线顺序（界面不会跳来跳去）', () => {
  const p = deriveProgress({ capabilities: ALL_READY as never, activeJob: null });
  assert.deepStrictEqual(
    p.domains.map((d) => d.name),
    ['pdf', 'text', 'media', 'claims', 'graph', 'presentation', 'qa', 'evaluation'],
  );
  assert.strictEqual(p.domains[0]!.label, '原文');
});

// ------------------------------------------------------- 三终态

check('pdf=unavailable（如"无源文件"）→ unavailable 终态，停止轮询', () => {
  const caps: Cap[] = [
    cap('pdf', 'unavailable', '无源文件'),
    cap('text', 'pending', '尚未解析'),
  ];
  const p = deriveProgress({ capabilities: caps as never, activeJob: null });
  assert.strictEqual(p.phase, 'unavailable');
  assert.strictEqual(p.shouldPoll, false, '源不可用是终态，继续轮询只是浪费');
});

check('作业 failed → failed 终态并带出错误信息', () => {
  const job = { state: 'failed', error: { message: 'MinerU 超时' } };
  const p = deriveProgress({ capabilities: [cap('pdf', 'ready')] as never, activeJob: job as never });
  assert.strictEqual(p.phase, 'failed');
  assert.strictEqual(p.failureMessage, 'MinerU 超时');
  assert.strictEqual(p.shouldPoll, false);
});

check('作业 cancelled 也算终态失败（不再空转）', () => {
  const p = deriveProgress({
    capabilities: [cap('pdf', 'ready')] as never,
    activeJob: { state: 'cancelled', error: null } as never,
  });
  assert.strictEqual(p.phase, 'failed');
  assert.ok(p.failureMessage);
});

check('超预算仍 pending → timeout，但**降频继续轮询**（不要求手动刷新）', () => {
  const p = deriveProgress({
    capabilities: [cap('pdf', 'ready'), cap('claims', 'pending', '尚未生成')] as never,
    activeJob: null,
    elapsedMs: POLL_BUDGET_MS + 1,
  });
  assert.strictEqual(p.phase, 'timeout');
  assert.strictEqual(p.shouldPoll, true, '超时也要继续后台轮询');
});

check('优先级：作业 failed 压过 unavailable 与 timeout', () => {
  const p = deriveProgress({
    capabilities: [cap('pdf', 'unavailable', '无源文件')] as never,
    activeJob: { state: 'failed', error: { message: 'x' } } as never,
    elapsedMs: POLL_BUDGET_MS + 1,
  });
  assert.strictEqual(p.phase, 'failed');
});

check('优先级：unavailable 压过 timeout', () => {
  const p = deriveProgress({
    capabilities: [cap('pdf', 'unavailable', '无源文件')] as never,
    activeJob: null,
    elapsedMs: POLL_BUDGET_MS + 1,
  });
  assert.strictEqual(p.phase, 'unavailable');
});

// ------------------------------------------------------- 退避与跳转

check('退避：作业活跃固定 2s；空闲时 1s→2s→5s 封顶', () => {
  assert.strictEqual(nextPollDelay(0, true), 2000);
  assert.strictEqual(nextPollDelay(0, false), 1000);
  assert.strictEqual(nextPollDelay(60_000, false), 2000);
  assert.strictEqual(nextPollDelay(200_000, false), 5000);
  assert.strictEqual(nextPollDelay(10 * 60_000, false), 5000, '必须封顶，避免退避到永不刷新');
});

check('exhibits 无 revision 时是 pending（旧实现停在 idle → 白屏）', () => {
  assert.strictEqual(exhibitsStatusFor(false), 'pending');
  assert.strictEqual(exhibitsStatusFor(true), 'loading');
});

check('**跳转必须带 job_id**（旧实现丢掉它 → SSE 永不连接）', () => {
  assert.strictEqual(workspaceQuery(12, 34), 'paper_id=12&job_id=34');
  assert.strictEqual(workspaceQuery(12), 'paper_id=12');
  assert.strictEqual(workspaceQuery(12, null), 'paper_id=12');
  assert.strictEqual(workspaceQuery(12, 0), 'paper_id=12', 'job_id=0 与缺失等价');
});

check('activeJob 为 running 时有进度语义（阶段细粒度可用）', () => {
  const p = deriveProgress({
    capabilities: [cap('pdf', 'ready'), cap('claims', 'pending')] as never,
    activeJob: { state: 'running', stage: 'claims', progress: 0.5 } as never,
  });
  assert.strictEqual(p.phase, 'extracting');
  assert.ok(p.shouldPoll);
});

console.log(`\npaperProgress: ${passed} 项全部通过`);
