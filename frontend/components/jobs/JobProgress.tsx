'use client';

// 任务阶段进度（§5.13 / §5.8）：从 JobEvent[] 推导当前阶段与进度，渲染有序阶段列表。

import { Check, Loader2 } from 'lucide-react';
import type { JobEvent, Stage } from '@/lib/contracts';
import { cn } from '@/lib/cn';

const STAGES: { key: Stage; label: string }[] = [
  { key: 'acquire', label: '获取源' },
  { key: 'parse', label: '解析' },
  { key: 'normalize', label: '规范化' },
  { key: 'media', label: '媒体' },
  { key: 'index', label: '索引' },
  { key: 'claims', label: '断言' },
  { key: 'verify', label: '校验' },
  { key: 'exhibits', label: '展项' },
  { key: 'qa_bank', label: '题库' },
  { key: 'evaluate', label: '评测' },
  { key: 'publish', label: '发布' },
];

const TERMINAL: JobEvent['type'][] = ['completed', 'failed', 'cancelled'];

export function JobProgress({ events }: { events: JobEvent[] }) {
  const latest = events[events.length - 1];
  const currentStage = latest?.data.stage ?? null;
  const progress = latest?.data.progress ?? 0;
  const done = latest ? TERMINAL.includes(latest.type) : false;

  const currentIndex = currentStage
    ? STAGES.findIndex((s) => s.key === currentStage)
    : -1;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-medium text-slate-700">处理进度</span>
        <span className="font-mono text-xs text-slate-500">{Math.round(progress * 100)}%</span>
      </div>
      <div className="mb-4 h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn('h-full rounded-full transition-all', done ? 'bg-emerald-500' : 'bg-indigo-500')}
          style={{ width: `${Math.min(100, Math.round(progress * 100))}%` }}
        />
      </div>
      <ol className="space-y-1">
        {STAGES.map((s, i) => {
          const isActive = i === currentIndex && !done;
          const isDone = i < currentIndex || (i === currentIndex && done);
          return (
            <li
              key={s.key}
              className={cn(
                'flex items-center gap-2 rounded-md px-2 py-1 text-xs',
                isActive ? 'bg-indigo-50 text-indigo-700' : isDone ? 'text-slate-500' : 'text-slate-400',
              )}
            >
              {isActive ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : isDone ? (
                <Check className="h-3.5 w-3.5 text-emerald-500" />
              ) : (
                <span className="h-3.5 w-3.5 rounded-full border border-slate-200" />
              )}
              {s.label}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
