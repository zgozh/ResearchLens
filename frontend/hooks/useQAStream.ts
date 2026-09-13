'use client';

// 流式 QA：POST /papers/{id}/qa/stream（SSE），先 citation 后 verified sentence，最后唯一 final/error。
//
// R4-M4：生命周期判定全部委托给**纯状态机** `lib/qaStreamState`（可单测），本文件只管
// 传输与 React 状态。关键修正：
//   · 没有 final 的"流读完"是 `recovering`，**不是** `completed`（旧实现把两者混为一谈，
//     调用方于是把"没有结果"渲染成「回答被中断 · 置信度 Low」）；
//   · 解析失败的帧**计数并告警**，不再静默丢弃（final 消失时以前零线索）。

import { useCallback, useRef, useState } from 'react';
import type { DomainError, QARequest, QAStreamEvent, Scope, StreamState } from '@/lib/contracts';
import { api, toDomainError } from '@/lib/api';
import { openSSE, parseSSEJson } from '@/lib/sse';
import {
  applyCancelled,
  applyFrame,
  applyTransportEnd,
  applyTransportFailure,
  initProgress,
  noteDroppedFrame,
  type StreamProgress,
} from '@/lib/qaStreamState';

export function useQAStream({ scope, request }: { scope: Scope; request: QARequest }): {
  state: StreamState;
  events: QAStreamEvent[];
  /** 解析失败被丢弃的帧数（>0 说明传输层有问题，用于对账）。 */
  droppedFrames: number;
  error: DomainError | null;
  cancel: () => void;
  start: (request?: QARequest) => void;
} {
  const [progress, setProgress] = useState<StreamProgress>(() => ({ ...initProgress(), state: 'idle' }));
  const [events, setEvents] = useState<QAStreamEvent[]>([]);
  const [error, setError] = useState<DomainError | null>(null);
  const acRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    acRef.current?.abort();
    acRef.current = null;
    setProgress((p) => applyCancelled(p));
  }, []);

  const start = useCallback(
    (req?: QARequest) => {
      const r = req ?? request;
      acRef.current?.abort();
      const ac = new AbortController();
      acRef.current = ac;
      setProgress(initProgress());
      setError(null);
      setEvents([]);

      openSSE(api.qaStreamUrl(scope.paper_id), {
        method: 'POST',
        body: {
          question: r.question,
          top_k: r.top_k,
          revision_id: r.revision_id ?? scope.revision_id,
        },
        signal: ac.signal,
        onEvent: (frame) => {
          const ev = parseSSEJson<QAStreamEvent>(frame);
          if (!ev) {
            // 以前这里直接 `return` → final 若是这一帧就永远消失且**无任何痕迹**。
            setProgress((p) => noteDroppedFrame(p, frame.data));
            return;
          }
          setEvents((prev) => [...prev, ev]);
          setProgress((p) => applyFrame(p, { type: ev.type, data: ev.data }));
        },
        onComplete: () => setProgress((p) => applyTransportEnd(p)),
      }).catch((e) => {
        if (ac.signal.aborted) {
          setProgress((p) => applyCancelled(p));
          return;
        }
        setError(toDomainError(e));
        setProgress((p) => applyTransportFailure(p));
      });
    },
    [scope, request],
  );

  return {
    state: progress.state,
    events,
    droppedFrames: progress.droppedFrames,
    error,
    cancel,
    start,
  };
}
