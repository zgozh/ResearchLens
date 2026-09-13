// QA SSE 生命周期状态机（R4-M4，零依赖纯函数 —— 便于在 node 里单测）。
//
// 为什么要有这个模块：线上现象是用户看到「回答被中断 · 置信度 Low」，而实测后端
// 三条默认问题**都发了 final**。根因在这一层：
//
//   1. `lib/sse.ts` 的 `parseSSEJson` 解析失败会**静默返回 null**，`useQAStream` 直接丢帧
//      → final 消失 → 调用方看到"流读完了但没有结果"，且**零日志**、无法对账；
//   2. `onComplete` 无条件置 `completed` —— 它把"流读完"与"拿到结果"混为一谈，
//      于是"没有 final"被呈现成一个**看起来像正常业务结论**的状态；
//   3. 调用方用一次性锁（`streamDoneRef`）把首次判定永久固定，"被中断"就留在界面上。
//
// 本模块只做一件事：把「已收到的帧 + 丢帧计数 + 传输层是否结束」映射成
// **唯一的下一状态**，并明确区分「拿到结果」`completed` 与「流读完但没有结果」`recovering`。
// 它不碰 DOM、不碰 React、不发请求 —— 恢复链（取回 / 非流式兜底）由调用方执行。

import type { StreamState } from './contracts';

/** 传输层读到的原始帧（已 JSON 解析成功）。 */
export interface RawFrame {
  type: string;
  data: unknown;
}

export interface StreamProgress {
  state: StreamState;
  /** 是否已收到 `final`（**唯一**的"拿到结果"标志）。 */
  gotFinal: boolean;
  /** 是否已收到 `error`。 */
  gotError: boolean;
  /**
   * 解析失败被丢弃的帧数。
   *
   * 为什么必须计数：final 因任何原因（超大 data 被代理截断、编码异常、
   * 后端漏发）无法解析时，以前是**静默**的 —— 界面只会说"被中断"，
   * 没有任何可对账的信号。现在这个数字会进控制台与消息 note。
   */
  droppedFrames: number;
  /** 本次回答的 answer_id（来自 meta），恢复链的钥匙。 */
  answerId: string | null;
}

export function initProgress(): StreamProgress {
  return {
    state: 'connecting',
    gotFinal: false,
    gotError: false,
    droppedFrames: 0,
    answerId: null,
  };
}

/** 一帧解析失败：只累加计数与告警，**绝不改变已确定的终态**。 */
export function noteDroppedFrame(p: StreamProgress, frameSample: string): StreamProgress {
  // eslint-disable-next-line no-console
  console.warn(
    `[qa-stream] 丢弃无法解析的 SSE 帧 #${p.droppedFrames + 1}：${frameSample.slice(0, 120)}`,
  );
  return { ...p, droppedFrames: p.droppedFrames + 1 };
}

/** 收到一帧（已解析成功）→ 下一状态。 */
export function applyFrame(p: StreamProgress, frame: RawFrame): StreamProgress {
  const data = (frame.data ?? {}) as Record<string, unknown>;
  if (frame.type === 'meta') {
    const id = typeof data.answer_id === 'string' ? data.answer_id : null;
    return { ...p, answerId: id ?? p.answerId };
  }
  if (frame.type === 'final') {
    // final 是**唯一**的完成信号；error 之后再收到 final 也以 final 为准
    // （服务端契约是"恰好一个"，但网络重放/代理重试时可能都到）。
    return { ...p, gotFinal: true, gotError: false, state: 'completed' };
  }
  if (frame.type === 'error') {
    if (p.gotFinal) return p; // 已有结果，迟到的 error 不改写
    return { ...p, gotError: true, state: 'failed' };
  }
  if (p.state === 'connecting' || p.state === 'recovering') {
    return { ...p, state: 'streaming' };
  }
  return p;
}

/**
 * 传输层结束（读到 done）→ 下一状态。
 *
 * **关键修正**：没有 `final` 时不再置 `completed`，而是 `recovering`
 * —— "流读完了"不等于"拿到结果"。调用方据此执行恢复链。
 */
export function applyTransportEnd(p: StreamProgress): StreamProgress {
  if (p.gotFinal) return { ...p, state: 'completed' };
  if (p.gotError) return { ...p, state: 'failed' };
  return { ...p, state: 'recovering' };
}

/** 传输层失败（异常/非 2xx）→ 下一状态；已拿到 final 则不改写。 */
export function applyTransportFailure(p: StreamProgress): StreamProgress {
  if (p.gotFinal) return { ...p, state: 'completed' };
  return { ...p, state: 'failed' };
}

/** 恢复链成功（取回服务端已落库的结果，或非流式兜底）→ `completed`。 */
export function applyRecovered(p: StreamProgress): StreamProgress {
  return { ...p, state: 'completed' };
}

/** 恢复链也失败 → `failed`（**不是**一个"回答"）。 */
export function applyRecoveryFailed(p: StreamProgress): StreamProgress {
  return { ...p, state: 'failed' };
}

/** 用户取消。 */
export function applyCancelled(p: StreamProgress): StreamProgress {
  return { ...p, state: 'cancelled' };
}

/**
 * 迟到的 final 是否可以采纳。
 *
 * 为什么需要：旧实现用一次性锁把首次判定永久固定 —— 恢复期间 final 到了也不认，
 * 于是"被中断"永远留在界面上（用户说的"一直"）。
 * 采纳条件：**answer_id 一致**（同一问）且当前尚未拿到 final。
 */
export function shouldAcceptLateFinal(
  p: StreamProgress,
  incomingAnswerId: string | null,
): boolean {
  if (p.gotFinal) return false;
  if (!p.answerId || !incomingAnswerId) return true; // 无从比对时以最新为准
  return p.answerId === incomingAnswerId;
}

/** 是否处于"已经拿到结果"的终态（UI 据此渲染回答而非提示）。 */
export function isSettled(p: StreamProgress): boolean {
  return p.state === 'completed';
}

/** 是否仍在进行（连接/流式/恢复中）—— 用于禁用输入与显示 spinner。 */
export function isBusy(p: StreamProgress): boolean {
  return p.state === 'connecting' || p.state === 'streaming' || p.state === 'recovering';
}
