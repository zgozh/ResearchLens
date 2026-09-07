'use client';

import {
  LayoutGrid, Workflow, FileSearch, Share2, Mic, MessageCircle, Gauge,
} from 'lucide-react';
import type { ViewMode } from '@/lib/types';
import { cn } from '@/lib/cn';

const ITEMS: { view: ViewMode; label: string; icon: any; key: string }[] = [
  { view: 'paper', label: 'Paper', icon: FileSearch, key: 'paper' },
  { view: 'map', label: 'Problem · Map', icon: LayoutGrid, key: 'map' },
  { view: 'method', label: 'Method', icon: Workflow, key: 'method' },
  { view: 'claim', label: 'Experiment · Result', icon: FileSearch, key: 'claim' },
  { view: 'graph', label: 'Research Graph', icon: Share2, key: 'graph' },
  { view: 'presenter', label: 'Presenter', icon: Mic, key: 'presenter' },
  { view: 'qa', label: 'Q&A', icon: MessageCircle, key: 'qa' },
  { view: 'eval', label: 'Evaluation', icon: Gauge, key: 'eval' },
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
