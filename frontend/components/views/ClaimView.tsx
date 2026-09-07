'use client';

import { motion } from 'framer-motion';
import { FileText, ShieldCheck, ShieldAlert, Table2, Quote } from 'lucide-react';
import type { ClaimSummary, PaperDetail } from '@/lib/types';
import { Badge, GlassCard, Kicker } from '@/components/ui';
import { cn } from '@/lib/cn';

const TYPE_TONE: Record<string, 'accent' | 'emerald' | 'amber' | 'rose' | 'cyan'> = {
  RESULT: 'emerald',
  METHOD: 'accent',
  LIMITATION: 'rose',
  CONTEXT: 'cyan',
};

export function ClaimView({
  detail,
  claims,
  selectedClaimId,
  onSelect,
}: {
  detail: PaperDetail;
  claims: ClaimSummary[];
  selectedClaimId?: string;
  onSelect: (claimId: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
      {/* Claims list */}
      <div className="lg:col-span-3">
        <Kicker className="mb-3">可验证断言 · CLAIMS</Kicker>
        <div className="space-y-2.5">
          {(claims || []).map((c, i) => {
            const selected = c.claim_id === selectedClaimId;
            return (
              <motion.div key={c.claim_id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
                <button
                  onClick={() => onSelect(c.claim_id)}
                  className={cn(
                    'w-full rounded-2xl border p-4 text-left transition-all',
                    selected
                      ? 'border-white/25 bg-white/[0.06] shadow-lg'
                      : 'border-[var(--line)] bg-white/[0.02] hover:bg-white/[0.04]',
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] text-slate-500">{c.claim_id}</span>
                      <Badge tone={TYPE_TONE[c.type] || 'slate'}>{c.type}</Badge>
                      {c.status === 'SUPPORTED' ? (
                        <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400">
                          <ShieldCheck className="h-3.5 w-3.5" /> 已支持
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[11px] text-amber-400">
                          <ShieldAlert className="h-3.5 w-3.5" /> 未支持
                        </span>
                      )}
                    </div>
                    <span className="font-mono text-[11px] text-slate-500">置信 {c.confidence.toFixed(2)}</span>
                  </div>
                  <p className="mt-2.5 text-sm leading-relaxed text-slate-200">{c.statement}</p>
                  <div className="mt-3 flex items-center gap-3 text-[11px] text-slate-500">
                    <span className="inline-flex items-center gap-1">
                      <FileText className="h-3 w-3" /> {c.evidence_count} 条证据
                    </span>
                  </div>
                </button>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* Tables + figures */}
      <div className="lg:col-span-2">
        <Kicker className="mb-3">结果图表 · RESULTS</Kicker>
        <div className="space-y-4">
          {(detail.tables || []).map((t) => (
            <GlassCard key={t.table_no} className="overflow-hidden p-4">
              <div className="mb-2 flex items-center gap-2">
                <Table2 className="h-3.5 w-3.5 text-slate-400" />
                <span className="text-xs font-semibold text-slate-200">表 {t.table_no}</span>
                <span className="ml-auto font-mono text-[10px] text-slate-500">p.{t.page}</span>
              </div>
              <p className="mb-2.5 text-[11px] text-slate-500">{t.caption}</p>
              <div className="overflow-hidden rounded-lg border border-[var(--line)]">
                <table className="w-full text-left text-[12px]">
                  <thead>
                    <tr className="bg-white/[0.04]">
                      {(t.content[0] || []).map((h, i) => (
                        <th key={i} className="px-2.5 py-1.5 font-medium text-slate-300">{h}</th>
                      ))}
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
            </GlassCard>
          ))}

          {detail.figures.map((f) => (
            <GlassCard key={f.fig_no} className="p-4">
              <div className="mb-2 flex items-center gap-2">
                <Quote className="h-3.5 w-3.5 text-slate-400" />
                <span className="text-xs font-semibold text-slate-200">图 {f.fig_no}</span>
                <span className="ml-auto font-mono text-[10px] text-slate-500">p.{f.page}</span>
              </div>
              <div className="overflow-hidden rounded-lg border border-[var(--line)] bg-[#0F172A] p-1">
                <div className="[&_svg]:w-full [&_svg]:h-auto" dangerouslySetInnerHTML={{ __html: f.glyph_svg }} />
              </div>
              <p className="mt-2 text-[11px] text-slate-500">{f.caption}</p>
            </GlassCard>
          ))}
        </div>
      </div>
    </div>
  );
}
