'use client';

// 流式 QA：POST /papers/{id}/qa/stream（SSE），先 citation 后 verified sentence，最后唯一 final/error。

import { useCallback, useRef, useState } from 'react';
import type { DomainError, QARequest, QAStreamEvent, Scope, StreamState } from '@/lib/contracts';
import { api, toDomainError } from '@/lib/api';
import { openSSE, parseSSEJson } from '@/lib/sse';

export function useQAStream({ scope, request }: { scope: Scope; request: QARequest }): {
  state: StreamState;
  events: QAStreamEvent[];
  error: DomainError | null;
  cancel: () => void;
  start: (request?: QARequest) => void;
} {
  const [state, setState] = useState<StreamState>('idle');
  const [events, setEvents] = useState<QAStreamEvent[]>([]);
  const [error, setError] = useState<DomainError | null>(null);
  const acRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    acRef.current?.abort();
    acRef.current = null;
    setState('cancelled');
  }, []);

  const start = useCallback(
    (req?: QARequest) => {
      const r = req ?? request;
      acRef.current?.abort();
      const ac = new AbortController();
      acRef.current = ac;
      setState('connecting');
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
          if (!ev) return;
          setEvents((prev) => [...prev, ev]);
          if (ev.type === 'final') {
            setState((s) => (s === 'cancelled' ? s : 'completed'));
          } else if (ev.type === 'error') {
            setState((s) => (s === 'cancelled' ? s : 'failed'));
          } else {
            setState((s) => (s === 'cancelled' ? s : 'streaming'));
          }
        },
        onComplete: () => setState((s) => (s === 'cancelled' ? s : 'completed')),
      }).catch((e) => {
        if (ac.signal.aborted) {
          setState('cancelled');
          return;
        }
        setError(toDomainError(e));
        setState('failed');
      });
    },
    [scope, request],
  );

  return { state, events, error, cancel, start };
}
