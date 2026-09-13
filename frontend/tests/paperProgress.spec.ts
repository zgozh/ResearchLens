// R4-M7 导入进度单测（零依赖 runner，见 tests/richtext.spec.ts 注释）。
//
// 锁住用户报的现象："点了处理之后直接跳转到成果那里，但一开始什么都没解析出，
// 所以是一片空白，我还要等一会然后手动刷新才能看到解析出的东西。"
// 运行：npm run test:progress

import assert from 'assert';
import {
  POLL_BUDGET_MS,
  deriveProgress,
  derivedTargetsFor,
  exhibitsStatusFor,
  isProgressVisible,
  newlyReadyDomains,
  nextLoadStatus,
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

// ------------------------------------- R4-M7b：实时进度（消除闪烁 + 内容自动上屏）

check('**silent 刷新不许重置加载状态**（闪烁的根因就在这）', () => {
  // 实测：refresh() 每次开头把 status 置 'loading'，而进度卡可见性又绑了它
  // → 每个轮询 tick 必然走一遍「出现 → 消失」。
  assert.strictEqual(nextLoadStatus('ready', true), 'ready', 'silent 时必须保持原状态');
  assert.strictEqual(nextLoadStatus('pending', true), 'pending');
  assert.strictEqual(nextLoadStatus('error', true), 'error', 'silent 刷新也不该把错误态刷成加载中');
  // 非 silent（首帧）：确实还没有数据，置 loading 是对的
  assert.strictEqual(nextLoadStatus('idle', false), 'loading');
  assert.strictEqual(nextLoadStatus('ready', false), 'loading');
});

check('进度卡可见性**只看 phase**（不看会被轮询重置的加载状态）', () => {
  assert.strictEqual(isProgressVisible('extracting'), true);
  assert.strictEqual(isProgressVisible('timeout'), true);
  assert.strictEqual(isProgressVisible('failed'), true);
  assert.strictEqual(isProgressVisible('unavailable'), true);
  assert.strictEqual(isProgressVisible('ready'), false);
});

check('跃迁：从非 ready 变 ready 才算"刚就绪"', () => {
  const prev = [cap('claims', 'pending'), cap('graph', 'pending'), cap('media', 'ready')];
  const next = [cap('claims', 'ready'), cap('graph', 'pending'), cap('media', 'ready')];
  assert.deepStrictEqual(newlyReadyDomains(prev as never, next as never), ['claims']);
});

check('跃迁：首次拿到快照（prev 为 null）**不算**跃迁（首帧本来就会全量加载）', () => {
  const next = [cap('claims', 'ready'), cap('graph', 'ready')];
  assert.deepStrictEqual(newlyReadyDomains(null, next as never), []);
  assert.deepStrictEqual(newlyReadyDomains(undefined, next as never), []);
});

check('跃迁：已 ready 且仍 ready → 不重复（幂等，不反复拉重端点）', () => {
  const caps = [cap('claims', 'ready')];
  assert.deepStrictEqual(newlyReadyDomains(caps as never, caps as never), []);
});

check('跃迁：上一轮没有的域不误判为"刚就绪"', () => {
  const prev = [cap('claims', 'pending')];
  const next = [cap('claims', 'pending'), cap('brand_new', 'ready')];
  assert.deepStrictEqual(newlyReadyDomains(prev as never, next as never), []);
});

check('跃迁：一轮里多个域同时就绪 → 全部返回（顺序跟随 next）', () => {
  const prev = [cap('claims', 'pending'), cap('graph', 'pending'), cap('presentation', 'pending')];
  const next = [cap('claims', 'ready'), cap('graph', 'ready'), cap('presentation', 'ready')];
  assert.deepStrictEqual(
    newlyReadyDomains(prev as never, next as never),
    ['claims', 'graph', 'presentation'],
  );
});

check('域 → 派生数据映射：claims/media/text 都吃 detail', () => {
  assert.deepStrictEqual(derivedTargetsFor(['claims']), ['detail']);
  assert.deepStrictEqual(derivedTargetsFor(['media']), ['detail']);
  assert.deepStrictEqual(derivedTargetsFor(['graph']), ['graph']);
  assert.deepStrictEqual(derivedTargetsFor(['presentation']), ['presentation']);
  assert.deepStrictEqual(derivedTargetsFor(['evaluation']), ['evaluation']);
});

check('域 → 派生数据映射：多域去重、未知域不产生目标', () => {
  const t = derivedTargetsFor(['claims', 'media', 'graph', 'graph', 'qa' as never]);
  assert.deepStrictEqual([...t].sort(), ['detail', 'graph']);
  assert.deepStrictEqual(derivedTargetsFor([]), []);
});

check('进度卡的可见性不再依赖 exhibits 加载状态（源码级回归）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'app/paper/[slug]/page.tsx');
  const source = fs.readFileSync(file, 'utf8');
  const m = /const notReady = ([^;]+);/.exec(source);
  assert.ok(m, '找不到 notReady 的定义');
  assert.ok(
    !/exhibits\.status|status === 'loading'|status === 'pending'/.test(m[1]!),
    `notReady 不许再看加载状态（那会被轮询重置 → 闪烁）：${m[1]}`,
  );
  assert.ok(/progress\.phase/.test(m[1]!), `notReady 应当只看进度真相：${m[1]}`);
});

check('轮询调用 refresh 时必须带 silent（源码级回归）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'app/paper/[slug]/page.tsx');
  const source = fs.readFileSync(file, 'utf8');
  assert.ok(
    /workspace\.refresh\(\s*\{\s*silent:\s*true\s*\}\s*\)/.test(source),
    '轮询必须用 silent 刷新，否则每个 tick 都会把状态刷成 loading → 闪',
  );
});

check('切视图必须保留 job_id（源码级回归：丢了就断流）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'app/paper/[slug]/page.tsx');
  const source = fs.readFileSync(file, 'utf8');
  const m = /const changeView = useCallback\([\s\S]*?\n  \);/.exec(source);
  assert.ok(m, '找不到 changeView');
  assert.ok(
    /params\.set\(\s*'job_id'/.test(m[0]),
    'changeView 必须把 job_id 写回 URL —— 否则切一次视图就断掉进度流',
  );
  assert.ok(
    /\[slug, resolvedPaperId, router, jobId\]/.test(m[0]),
    'jobId 必须进依赖数组，否则闭包里拿到的是旧值',
  );
});

check('分域跃迁会触发派生数据刷新（源码级回归：内容要自动上屏）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'app/paper/[slug]/page.tsx');
  const source = fs.readFileSync(file, 'utf8');
  assert.ok(
    /newlyReadyDomains\(capsRef\.current, caps\)/.test(source),
    '必须用状态跃迁判断（不是每 tick 全量重取）',
  );
  assert.ok(
    /refreshDerived\(derivedTargetsFor\(justReady\)\)/.test(source),
    '跃迁后要真的去拉对应的派生数据',
  );
  for (const t of ['paperDetail', 'api.graph', 'api.presentation', 'api.evaluation']) {
    assert.ok(source.includes(t), `派生数据刷新覆盖 ${t}`);
  }
});

check('派生数据刷新失败必须保留旧数据（silent 语义）', () => {
  const fs = require('fs') as typeof import('fs');
  const path = require('path') as typeof import('path');
  const file = path.resolve(process.cwd(), 'app/paper/[slug]/page.tsx');
  const source = fs.readFileSync(file, 'utf8');
  const m = /const refreshDerived = useCallback\([\s\S]*?\n  \}, \[resolvedPaperId\]\);/.exec(source);
  assert.ok(m, '找不到 refreshDerived');
  assert.ok(!/setDetail\(undefined\)|setGraph\(\{\}\)|setLoading\(true\)/.test(m[0]),
    'silent 刷新不许把数据清空或触发骨架屏');
  assert.ok(/catch/.test(m[0]), '必须有 catch：失败保留旧数据');
});

check('**真实导入快照**驱动：跃迁序列与派生数据拉取顺序（回归锁）', () => {
  // 这三帧是 2026-09-13 从真实导入的轮询里抓下来的 capabilities 快照（paper 18, 软件学报）。
  // 用真数据而不是合成数据，锁住"内容依次自动上屏"的时序。
  const S1 = [cap('pdf', 'ready'), cap('text', 'ready'), cap('media', 'ready'),
              cap('claims', 'pending'), cap('graph', 'pending'), cap('presentation', 'pending')];
  const S2 = [cap('pdf', 'ready'), cap('text', 'ready'), cap('media', 'ready'),
              cap('claims', 'ready'), cap('graph', 'pending'), cap('presentation', 'pending')];
  const S3 = [cap('pdf', 'ready'), cap('text', 'ready'), cap('media', 'ready'),
              cap('claims', 'ready'), cap('graph', 'ready'), cap('presentation', 'ready')];

  // 首帧：prev=null → 不算跃迁（loadLegacy 已经在挂载时全量拉过）
  assert.deepStrictEqual(newlyReadyDomains(null, S1 as never), []);
  // 第二帧：claims 刚就绪 → 只需重取 detail（地图/方法/证据链右栏/阅读都吃它）
  const d2 = newlyReadyDomains(S1 as never, S2 as never);
  assert.deepStrictEqual(d2, ['claims']);
  assert.deepStrictEqual(derivedTargetsFor(d2), ['detail']);
  // 第三帧：graph + presentation 同时就绪 → 各拉一次
  const d3 = newlyReadyDomains(S2 as never, S3 as never);
  assert.deepStrictEqual(d3, ['graph', 'presentation']);
  assert.deepStrictEqual([...derivedTargetsFor(d3)].sort(), ['graph', 'presentation']);
  // 第四帧：全部仍 ready → 不再拉（幂等，不打断正在看的内容）
  assert.deepStrictEqual(newlyReadyDomains(S3 as never, S3 as never), []);
});

console.log(`\npaperProgress: ${passed} 项全部通过`);
