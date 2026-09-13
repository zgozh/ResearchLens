// 导入进度推导（R4-M7，需求 F）—— 零依赖纯函数，便于在 node 里单测。
//
// 为什么要有这个模块：上传/点处理之后跳到工作台，页面**一片空白**，用户要等一会再
// 手动刷新才看到内容。根因是四条独立缺陷叠加（逐条读代码确认）：
//
//   1. `usePaperWorkspace.refresh()` 在没有 revision 时 `return`，`exhibits` 永远停在
//      idle 且**不重试**；
//   2. `page.tsx` 的"实时模式"门禁要求 `exhibits` 非空 → 恒为 null → 那段 40×2.5s
//      轮询**根本不会启动**；
//   3. `upload/page.tsx` 跳转时**不传 job_id** → SSE 永不连接；
//   4. **页面已经有现成的进度真相却没人用**：`manifest.capabilities`
//      （`{name, state, reason}`）与 `manifest.active_job`。
//
// 本模块把第 4 条变成唯一的进度真相，并给出三终态与退避策略的**确定判据**。

import type { Capability, JobRecord } from './contracts';

/** 分域的中文名（界面按流水线顺序展示）。 */
export const DOMAIN_LABELS: Record<Capability['name'], string> = {
  pdf: '原文',
  text: '正文解析',
  media: '图表媒体',
  claims: '断言抽取',
  graph: '研究图谱',
  presentation: '讲解分镜',
  qa: '问答底座',
  evaluation: '自动评测',
};

/** 流水线展示顺序（与 STAGE_ORDER 的业务含义一致，不含 acquire/publish 这类内部阶段）。 */
export const DOMAIN_ORDER: Capability['name'][] = [
  'pdf', 'text', 'media', 'claims', 'graph', 'presentation', 'qa', 'evaluation',
];

export interface DomainProgress {
  name: Capability['name'];
  label: string;
  state: Capability['state'];
  /** 后端给的原因（如"尚未解析"），没有就空串。 */
  reason: string;
  done: boolean;
}

export type ProgressPhase =
  | 'extracting'   // 仍在解析（有 pending，或 job 活跃）
  | 'ready'        // 全部就绪（或有 partial 但没有 pending）
  | 'unavailable'  // 源文件不可用等硬失败（pdf=unavailable）
  | 'failed'       // 作业失败
  | 'timeout';     // 超过预算仍在 pending

export interface ProgressView {
  phase: ProgressPhase;
  domains: DomainProgress[];
  pending: DomainProgress[];
  /** 首个 pending 域的可读原因（用于一句话状态）。 */
  currentReason: string;
  /** 完成度 0..1（按域计数，仅用于进度条）。 */
  ratio: number;
  /** 作业失败时的可读信息。 */
  failureMessage: string;
  /** 是否应该继续轮询。 */
  shouldPoll: boolean;
}

/** 轮询预算：导入预算约 6 分钟，留余量到 8 分钟（与规划一致）。 */
export const POLL_BUDGET_MS = 8 * 60 * 1000;

/**
 * **阻塞性域**：它们没就绪时，工作台确实没有内容可看，必须继续等。
 *
 * 为什么要把域分成两类（实测发现）：真实库里 paper 11 的 `qa` 域**长期**是
 * `pending`（问答底库按需构建）。如果"有 pending 就轮询"，那么每打开一篇已完成的论文
 * 都会空转 8 分钟 —— 那是轮询风暴，不是可观测性。
 *
 * 非阻塞域（graph / presentation / qa / evaluation）各自有独立入口与空态，
 * 就绪与否不影响"能不能看到内容"；它们的 pending 照常显示，但不驱动轮询。
 */
export const BLOCKING_DOMAINS: Capability['name'][] = ['pdf', 'text', 'media', 'claims'];

/** 指数退避：1s → 2s → 5s 封顶；作业活跃时固定 2s（要跟得上阶段变化）。 */
export function nextPollDelay(elapsedMs: number, jobActive: boolean): number {
  if (jobActive) return 2000;
  if (elapsedMs < 30_000) return 1000;
  if (elapsedMs < 120_000) return 2000;
  return 5000;
}

/**
 * 由 `manifest.capabilities` + `active_job` 推导进度视图（**唯一进度真相**）。
 *
 * 判据优先级（自上而下，先命中先返回）：
 *   `failed`（作业失败）> `unavailable`（源不可用）> `timeout`（超预算仍缺阻塞域）
 *   > `extracting`（阻塞域缺失或作业活跃）> `ready`。
 *
 * `shouldPoll` 只在**有活跃作业**或**阻塞域未就绪**时为真 —— 避免"每打开一篇
 * 已完成论文就空转 8 分钟"的轮询风暴（见 `BLOCKING_DOMAINS` 的说明）。
 */
export function deriveProgress(opts: {
  capabilities: Capability[] | null | undefined;
  activeJob: JobRecord | null | undefined;
  elapsedMs?: number;
}): ProgressView {
  const caps = opts.capabilities ?? [];
  const job = opts.activeJob ?? null;
  const elapsed = opts.elapsedMs ?? 0;

  const byName = new Map(caps.map((c) => [c.name, c]));
  const domains: DomainProgress[] = DOMAIN_ORDER
    // 后端可能还没给出某个域 → 按 pending/unknown 处理（不假装它已就绪）
    .map((name) => {
      const cap = byName.get(name);
      const state = (cap?.state ?? 'pending') as Capability['state'];
      return {
        name,
        label: DOMAIN_LABELS[name],
        state,
        reason: (cap?.reason ?? '').trim(),
        done: state === 'ready',
      };
    });

  const pending = domains.filter((d) => d.state === 'pending' || d.state === 'partial');
  const blockingPending = pending.filter((d) => BLOCKING_DOMAINS.includes(d.name));
  const jobActive = !!job && (job.state === 'queued' || job.state === 'running'
    || job.state === 'retry_wait');
  const jobFailed = !!job && (job.state === 'failed' || job.state === 'cancelled');
  const sourceUnavailable = domains.some(
    (d) => d.name === 'pdf' && d.state === 'unavailable',
  );

  const ratio = domains.length === 0
    ? 0
    : domains.filter((d) => d.state === 'ready').length / domains.length;

  const base = {
    domains,
    pending,
    ratio,
    // 一句话状态优先报**阻塞域**的原因（那才是"还要等什么"）
    currentReason: (blockingPending.find((d) => d.reason) ?? pending.find((d) => d.reason))
      ?.reason ?? '',
    failureMessage: jobFailed
      ? (job?.error?.message || '后台处理失败')
      : '',
  };

  if (jobFailed) {
    return { ...base, phase: 'failed', shouldPoll: false };
  }
  if (sourceUnavailable) {
    return { ...base, phase: 'unavailable', shouldPoll: false };
  }
  if (blockingPending.length === 0 && !jobActive) {
    // 阻塞域全部就绪：内容可看。非阻塞域的 pending 照常显示，但不驱动轮询。
    return { ...base, phase: 'ready', shouldPoll: false };
  }
  if (blockingPending.length > 0 && elapsed >= POLL_BUDGET_MS) {
    // 超时不等于放弃：降频继续后台轮询（用户不必手动刷新）
    return { ...base, phase: 'timeout', shouldPoll: true };
  }
  return { ...base, phase: 'extracting', shouldPoll: true };
}

/**
 * `exhibits` 在"还没有 revision"时应该是什么状态。
 *
 * 旧行为是 `return`（保持 idle + data null）→ 调用方拿不到任何信号，
 * 页面就是空白。新行为是显式的 `pending`，让 UI 能说"正在解析"。
 */
export function exhibitsStatusFor(hasRevision: boolean): 'pending' | 'loading' {
  return hasRevision ? 'loading' : 'pending';
}

/**
 * 跳转到工作台时应该带上的查询串。
 *
 * R4-M7 关键修复：上传/URL 两条路径以前都**只带 paper_id、丢掉 job_id**，
 * 于是 SSE 永不连接（`useJobEvents` 对 `job_id <= 0` 直接 idle），
 * 页面既没有进度也没有阶段细粒度。
 */
export function workspaceQuery(paperId: number, jobId?: number | null): string {
  const base = `paper_id=${paperId}`;
  return jobId && jobId > 0 ? `${base}&job_id=${jobId}` : base;
}
