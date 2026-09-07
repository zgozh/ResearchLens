'use client';

import { motion } from 'framer-motion';
import { ArrowDown } from 'lucide-react';
import type { PaperDetail, SectionOut } from '@/lib/types';
import { Badge, GlassCard, Kicker } from '@/components/ui';

const KIND_LABEL: Record<string, string> = {
  intro: 'Introduction',
  method: 'Method',
  experiment: 'Experiment',
  result: 'Result',
  discussion: 'Discussion & Limitation',
  conclusion: 'Conclusion',
  references: 'References',
};

const TONE: Record<string, 'accent' | 'cyan' | 'emerald' | 'amber' | 'rose' | 'violet' | 'slate'> = {
  intro: 'violet',
  method: 'accent',
  experiment: 'cyan',
  result: 'emerald',
  discussion: 'rose',
  conclusion: 'slate',
};

export function MapView({ detail, accent, onOpenSection }: {
  detail: PaperDetail;
  accent: string;
  onOpenSection?: (s: SectionOut) => void;
}) {
  const map = detail.map_summary || {};
  const boxes = [
    { key: 'problem', label: 'Problem', c: '#F43F5E' },
    { key: 'method', label: 'Method', c: '#6366F1' },
    { key: 'dataset', label: 'Dataset', c: '#22D3EE' },
    { key: 'experiment', label: 'Experiment', c: '#38BDF8' },
    { key: 'result', label: 'Result', c: '#34D399' },
    { key: 'limitation', label: 'Limitation', c: '#F59E0B' },
  ];

  return (
    <div className="space-y-6">
      {/* abstract */}
      <GlassCard className="p-6">
        <Kicker>ABSTRACT</Kicker>
        <p className="mt-3 text-[15px] leading-relaxed text-slate-300">{detail.abstract}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {(detail.tags || []).map((t) => (
            <Badge key={t} tone="slate">{t}</Badge>
          ))}
        </div>
        <div className="mt-5 flex flex-wrap gap-6 border-t border-[var(--line)] pt-4 font-mono text-[11px] text-slate-500">
          <span>AUTHORS · {detail.authors.join(', ')}</span>
          <span>YEAR · {detail.year}</span>
          <span>DOMAIN · {detail.domain}</span>
        </div>
      </GlassCard>

      {/* Paper map */}
      <div>
        <Kicker className="mb-3">PAPER MAP · 论文地图</Kicker>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {boxes.map((b, i) => (
            <motion.div
              key={b.key}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06 }}
            >
              <GlassCard className="group h-full p-5" style={{ borderTopColor: b.c, borderTopWidth: 2 }}>
                <div className="flex items-center gap-2.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: b.c }} />
                  <span className="font-mono text-[11px] uppercase tracking-[0.2em]" style={{ color: b.c }}>
                    {b.label}
                  </span>
                </div>
                <p className="mt-3 min-h-[3.2em] text-sm leading-relaxed text-slate-300">
                  {map[b.key] || '—'}
                </p>
              </GlassCard>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Sections */}
      <div>
        <Kicker className="mb-3">STRUCTURE · 章节结构</Kicker>
        <GlassCard className="divide-y divide-[var(--line)] overflow-hidden">
          {(detail.sections || []).map((s) => (
            <button
              key={s.heading}
              onClick={() => onOpenSection?.(s)}
              className="group flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-white/[0.03]"
            >
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-white/[0.04] font-mono text-[11px] text-slate-400">
                {s.page}
              </span>
              <div className="flex-1">
                <div className="text-sm font-medium text-slate-100">{s.heading}</div>
                <div className="mt-0.5 line-clamp-1 text-[12px] text-slate-500">{s.summary}</div>
              </div>
              <Badge tone={TONE[s.kind] || 'slate'}>{KIND_LABEL[s.kind] || s.kind}</Badge>
              <ArrowDown className="h-3.5 w-3.5 -rotate-90 text-slate-600 transition group-hover:text-slate-300" />
            </button>
          ))}
        </GlassCard>
      </div>
    </div>
  );
}
