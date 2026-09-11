'use client';

// Job 事件流：GET /jobs/{id}/events（SSE），按 event_id 去重。
// 重放到 completed/failed/cancelled 后关闭连接。

import { useCallback, useEffect, useRef, useState } from 'react';
import type { DomainError, JobEvent, JobId, StreamState } from '@/lib/contracts';
import { api, toDomainError } from '@/lib/api';
import { openSSE, parseSSEJson } from '@/lib/sse';

const TERMINAL: JobEvent['type'][] = ['completed', 'failed', 'cancelled'];

export function useJobEvents({ job_id }: { job_id: JobId }): {
  state: StreamState;
  events: JobEvent[];
  error: DomainError | null;
  cancel: () => void;
} {
  const [state, setState] = useState<StreamState>('idle');
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [error, setError] = useState<DomainError | null>(null);
  const acRef = useRef<AbortController | null>(null);
  const seenRef = useRef<Set<number>>(new Set());

  const cancel = useCallback(() => {
    acRef.current?.abort();
    acRef.current = null;
    setState('cancelled');
  }, []);

  useEffect(() => {
    if (!job_id || job_id <= 0) {
      setState('idle');
      setEvents([]);
      return;
    }
    const ac = new AbortController();
    acRef.current = ac;
    seenRef.current = new Set();
    setState('connecting');
    setError(null);
    setEvents([]);

    openSSE(api.jobEventsUrl(job_id), {
      method: 'GET',
      signal: ac.signal,
      onEvent: (frame) => {
        const ev = parseSSEJson<JobEvent>(frame);
        if (!ev) return;
        if (seenRef.current.has(ev.event_id)) return; // 去重
        seenRef.current.add(ev.event_id);
        setEvents((prev) => [...prev, ev]);
        setState((s) => (s === 'cancelled' ? s : 'streaming'));
        if (TERMINAL.includes(ev.type)) {
          setState((s) => (s === 'cancelled' ? s : 'completed'));
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

    return () => ac.abort();
  }, [job_id]);

  return { state, events, error, cancel };
}
