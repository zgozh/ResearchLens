'use client';

import { motion } from 'framer-motion';
import { ShieldCheck, ShieldAlert, FileText, Quote, Scan } from 'lucide-react';
import type { ClaimOut, PaperDetail } from '@/lib/types';
import { Badge, GlassCard, Kicker } from '@/components/ui';
import { cn } from '@/lib/cn';

export function EvidenceRail({
  claim,
  detail,
  accent,
}: {
  claim?: ClaimOut;
  detail: PaperDetail;
  accent: string;
}) {
  if (!claim) {
    return (
      <div className="hidden lg:block">
        <GlassCard className="sticky top-4 p-5">
          <Kicker className="mb-3">证据 · EVIDENCE</Kicker>
          <div className="grid h-40 place-items-center text-center">
            <div>
              <Scan className="mx-auto mb-3 h-8 w-8 text-slate-700" />
              <p className="text-[13px] text-slate-500">在中间区域选择一个断言 / 结果，<br />这里会展示它的 Claim → Evidence → Page。</p>
            </div>
          </div>
        </GlassCard>
      </div>
    );
  }

  const supported = claim.status === 'SUPPORTED';
  return (
    <div className="hidden lg:block">
      <GlassCard className="sticky top-4 max-h-[calc(100vh-6rem)] overflow-y-auto p-5">
        <div className="mb-4 flex items-center justify-between">
          <Kicker>证据 · EVIDENCE</Kicker>
          <span className="font-mono text-[10px] text-slate-500">{claim.claim_id}</span>
        </div>

        {/* claim */}
        <div className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-4">
          <div className="mb-2 flex items-center gap-2">
            <span className="font-mono text-[11px] text-slate-500">{claim.type}</span>
            {supported ? (
              <Badge tone="emerald"><ShieldCheck className="h-3 w-3" /> 已支持</Badge>
            ) : (
              <Badge tone="amber"><ShieldAlert className="h-3 w-3" /> 未支持</Badge>
            )}
          </div>
          <p className="text-sm leading-relaxed text-slate-100">{claim.statement}</p>
          <div className="mt-3 font-mono text-[11px] text-slate-500">置信度 · {claim.confidence.toFixed(2)}</div>
        </div>

        {/* evidence list */}
        <div className="mt-4 space-y-2.5">
          <Kicker>来源 · SOURCES</Kicker>
          {(claim.evidence || []).map((e, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-3"
            >
              <div className="flex items-center gap-2 text-[11px]">
                <FileText className="h-3.5 w-3.5" style={{ color: accent }} />
                <span className="font-mono text-slate-300">p.{e.page}</span>
                <span className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  {e.region}
                </span>
                <span className="ml-auto font-mono text-[10px] text-slate-600">{e.region_type}</span>
              </div>
              {e.quote && (
                <div className="mt-2 rounded-md border-l-2 pl-2.5 text-[12px] italic text-slate-400" style={{ borderColor: accent }}>
                  “{e.quote}”
                </div>
              )}
              <p className="mt-1.5 text-[12px] leading-snug text-slate-400">{e.text}</p>
            </motion.div>
          ))}

          {claim.evidence?.length === 0 && (
            <div className="rounded-xl border border-dashed border-amber-500/30 p-4 text-center text-[12px] text-amber-300/90">
              该断言未绑定证据 —— 按 Evidence Gate，仅标记为 AI 解释，不作为事实。
            </div>
          )}
        </div>

        {/* original figure referenced by evidence */}
        {(() => {
          const evRegion = claim.evidence?.[0]?.region || '';
          const fig = detail.figures.find(
            (f) => evRegion.includes(`fig_${f.fig_no}`) || `${f.fig_no}` === evRegion.replace('fig_', ''),
          );
          if (!fig) return null;
          return (
            <div className="mt-4">
              <Kicker className="mb-2">原图 · ORIGINAL FIGURE</Kicker>
              <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[#0F172A] p-1">
                <div className="[&_svg]:w-full [&_svg]:h-auto" dangerouslySetInnerHTML={{ __html: fig.glyph_svg }} />
              </div>
              <p className="mt-2 text-[11px] text-slate-500">图 {fig.fig_no} · p.{fig.page}</p>
            </div>
          );
        })()}
      </GlassCard>
    </div>
  );
}
