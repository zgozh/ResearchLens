'use client';

// Agent 工具调用时间线（§5.13 / §5.8）：只展示工具名 + 简短可展示理由，
// 不展示隐式思维链。

import { Wrench } from 'lucide-react';
import type { JobEvent } from '@/lib/contracts';
import { cn } from '@/lib/cn';

const TOOL_LABELS: Record<string, string> = {
  retrieve_blocks: '检索原文块',
  get_blocks: '读取块',
  get_media: '读取媒体',
  validate_statement: '校验陈述',
  submit_candidate: '提交候选',
};

export function AgentTrace({ events }: { events: JobEvent[] }) {
  const toolEvents = events.filter(
    (e) => e.type === 'tool_started' || e.type === 'tool_finished',
  );

  if (toolEvents.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-400">
        暂无 Agent 工具调用记录。
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        <Wrench className="h-4 w-4 text-slate-400" />
        <span className="text-sm font-medium text-slate-700">Agent 工具调用</span>
      </div>
      <ol className="space-y-1 border-l border-slate-200 pl-3">
        {toolEvents.map((e) => {
          const started = e.type === 'tool_started';
          const tool = e.data.tool ?? '—';
          return (
            <li key={e.event_id} className="relative py-0.5 text-xs">
              <span
                className={cn(
                  'absolute -left-[15px] top-2 h-2 w-2 rounded-full',
                  started ? 'bg-indigo-400' : 'bg-emerald-400',
                )}
              />
              <div className="flex items-center gap-2">
                <span className={cn('font-mono', started ? 'text-indigo-600' : 'text-emerald-600')}>
                  {TOOL_LABELS[tool] ?? tool}
                </span>
                <span className="text-slate-400">{started ? '开始' : '完成'}</span>
                {e.data.elapsed_ms != null && (
                  <span className="font-mono text-slate-400">{e.data.elapsed_ms}ms</span>
                )}
              </div>
              {e.data.message && <p className="mt-0.5 text-slate-500">{e.data.message}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
