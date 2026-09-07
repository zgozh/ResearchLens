'use client';

import {
  LayoutGrid, Workflow, FileSearch, Share2, Mic, MessageCircle, Gauge,
} from 'lucide-react';
import type { ViewMode } from '@/lib/types';
import { cn } from '@/lib/cn';

const ITEMS: { view: ViewMode; label: string; icon: any; key: string }[] = [
  { view: 'paper', label: '论文', icon: FileSearch, key: 'paper' },
  { view: 'map', label: '问题 · 地图', icon: LayoutGrid, key: 'map' },
  { view: 'method', label: '方法', icon: Workflow, key: 'method' },
  { view: 'claim', label: '实验 · 结果', icon: FileSearch, key: 'claim' },
  { view: 'graph', label: '研究图谱', icon: Share2, key: 'graph' },
  { view: 'presenter', label: '讲解员', icon: Mic, key: 'presenter' },
  { view: 'qa', label: '问答', icon: MessageCircle, key: 'qa' },
  { view: 'eval', label: '评测', icon: Gauge, key: 'eval' },
];

export function Timeline({
  current,
  onSelect,
  accent,
}: {
  current: ViewMode;
  onSelect: (v: ViewMode) => void;
  accent: string;
}) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto pb-1 no-scrollbar">
      {ITEMS.map((it, i) => {
        const active = current === it.view;
        return (
          <div key={it.view} className="flex shrink-0 items-center">
            <button
              onClick={() => onSelect(it.view)}
              className={cn(
                'group flex items-center gap-2 rounded-xl px-3 py-2 text-[12px] font-medium transition-all',
                active ? 'text-white' : 'text-slate-500 hover:text-slate-200',
              )}
              style={active ? { background: `${accent}1c`, border: `1px solid ${accent}44` } : { border: '1px solid transparent' }}
            >
              <it.icon className="h-3.5 w-3.5" style={{ color: active ? accent : undefined }} />
              {it.label}
            </button>
            {i < ITEMS.length - 1 && (
              <span className={cn('mx-1 h-px w-3', active ? 'bg-white/30' : 'bg-white/10')} />
            )}
          </div>
        );
      })}
    </div>
  );
}
