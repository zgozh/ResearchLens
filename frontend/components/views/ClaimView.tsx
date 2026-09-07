'use client';

import { motion } from 'framer-motion';
import { FileText, ShieldCheck, ShieldAlert, Table2, Quote, Expand } from 'lucide-react';
import type { ClaimSummary, PaperDetail } from '@/lib/types';
import { Badge, GlassCard, Kicker } from '@/components/ui';
import { MediaModal, type MediaItem } from '@/components/MediaModal';
import { cn } from '@/lib/cn';
import { useState } from 'react';

const TYPE_TONE: Record<string, 'accent'|'emerald'|'amber'|'rose'|'cyan'|'violet'> = {
  RESULT: 'emerald', METHOD: 'accent', LIMITATION: 'rose', CONTEXT: 'cyan', EXPERIMENT: 'violet',
};
const TYPE_ORDER = ['RESULT', 'METHOD', 'EXPERIMENT', 'LIMITATION', 'CONTEXT'];
const TYPE_LABEL: Record<string, string> = {
  RESULT: '结果', METHOD: '方法', EXPERIMENT: '实验', LIMITATION: '局限', CONTEXT: '背景',
};

export function ClaimView({ detail, claims, selectedClaimId, onSelect }: {
  detail: PaperDetail; claims: ClaimSummary[]; selectedClaimId?: string; onSelect: (id: string) => void;
}) {
  const [media, setMedia] = useState<MediaItem | null>(null);
  const grouped = TYPE_ORDER.map((t) => ({ type: t, list: claims.filter((c) => c.type === t) }))
    .filter((g) => g.list.length > 0);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
      {/* 断言（分组） */}
      <div className="lg:col-span-3">
        <Kicker className="mb-3">可验证断言 · CLAIMS（共 {claims.length} 条）</Kicker>
        <div className="space-y-5">
          {grouped.map((g) => (
            <div key={g.type}>
              <div className="mb-2 flex items-center gap-2">
                <Badge tone={TYPE_TONE[g.type] || 'slate'}>{TYPE_LABEL[g.type] || g.type}</Badge>
                <span className="font-mono text-[11px] text-slate-500">{g.type} · {g.list.length} 条</span>
              </div>
              <div className="space-y-2">
                {g.list.map((c, i) => {
                  const selected = c.claim_id === selectedClaimId;
                  return (
                    <motion.div key={c.claim_id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                      <button onClick={() => onSelect(c.claim_id)}
                        className={cn('w-full rounded-2xl border p-4 text-left transition-all',
                          selected ? 'border-white/25 bg-white/[0.06] shadow-lg' : 'border-[var(--line)] bg-white/[0.02] hover:bg-white/[0.04]')}>
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[11px] text-slate-500">{c.claim_id}</span>
                            {c.status === 'SUPPORTED'
                              ? <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400"><ShieldCheck className="h-3.5 w-3.5" /> 已支持</span>
                              : <span className="inline-flex items-center gap-1 text-[11px] text-amber-400"><ShieldAlert className="h-3.5 w-3.5" /> 未支持</span>}
                          </div>
                          <span className="font-mono text-[11px] text-slate-500">置信 {c.confidence.toFixed(2)}</span>
                        </div>
                        <p className="mt-2.5 text-sm leading-relaxed text-slate-100">{c.statement}</p>
                        <div className="mt-2.5 flex items-center gap-3 text-[11px] text-slate-500">
                          <span className="inline-flex items-center gap-1"><FileText className="h-3 w-3" /> {c.evidence_count} 条证据</span>
                        </div>
                      </button>
                    </motion.div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 结果图表 + 关键结论 */}
      <div className="space-y-4 lg:col-span-2">
        <Kicker className="mb-3">结果图表 · RESULTS</Kicker>
        {(detail.tables || []).map((t) => (
          <GlassCard key={t.table_no} onClick={() => setMedia({ type: 'table', table: t })}
            className="group cursor-pointer overflow-hidden p-4 transition-all hover:border-white/20">
            <div className="mb-2 flex items-center gap-2">
              <Table2 className="h-3.5 w-3.5 text-slate-400" />
              <span className="text-xs font-semibold text-slate-200">表 {t.table_no}</span>
              <span className="ml-auto font-mono text-[10px] text-slate-500">p.{t.page}</span>
              <span className="inline-flex items-center gap-1 rounded-md bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-slate-500 transition group-hover:text-indigo-300">
                <Expand className="h-3 w-3" /> 查看
              </span>
            </div>
            <p className="mb-2.5 text-[11px] text-slate-500">{t.caption}</p>
            <div className="overflow-hidden rounded-lg border border-[var(--line)]">
              <table className="w-full text-left text-[12px]">
                <thead>
                  <tr className="bg-white/[0.04]">
                    {(t.content[0] || []).map((h, i) => <th key={i} className="px-2.5 py-1.5 font-medium text-slate-300">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {t.content.slice(1).map((row, ri) => (
                    <tr key={ri} className="border-t border-[var(--line)]">
                      {row.map((cell, ci) => (
                        <td key={ci} className={cn('px-2.5 py-1.5 text-slate-400', ci === 0 && 'text-slate-200')}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {t.key_finding && (
              <div className="mt-2.5 rounded-lg border-l-2 border-emerald-400 bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-100/90">
                关键结论：{t.key_finding}
              </div>
            )}
          </GlassCard>
        ))}
        <div className="grid grid-cols-1 gap-4">
          {detail.figures.map((f) => (
            <GlassCard key={f.fig_no} onClick={() => setMedia({ type: 'figure', figure: f })}
              className="group cursor-pointer p-4 transition-all hover:border-white/20">
              <div className="mb-2 flex items-center gap-2">
                <Quote className="h-3.5 w-3.5 text-slate-400" />
                <span className="text-xs font-semibold text-slate-200">图 {f.fig_no}</span>
                <span className="ml-auto font-mono text-[10px] text-slate-500">p.{f.page}</span>
                <span className="inline-flex items-center gap-1 rounded-md bg-white/[0.04] px-1.5 py-0.5 text-[10px] text-slate-500 transition group-hover:text-indigo-300">
                  <Expand className="h-3 w-3" /> 查看
                </span>
              </div>
              <div className="overflow-hidden rounded-lg border border-[var(--line)] bg-[#0F172A] p-1">
                <div className="[&_svg]:w-full [&_svg]:h-auto" dangerouslySetInnerHTML={{ __html: f.glyph_svg }} />
              </div>
              <p className="mt-2 text-[11px] text-slate-500">{f.caption}</p>
              {f.description && <p className="mt-1 text-[11px] text-slate-600">{f.description}</p>}
            </GlassCard>
          ))}
        </div>
      </div>

      <MediaModal item={media} accent={detail.accent || '#6366F1'} onClose={() => setMedia(null)} />
    </div>
  );
}
