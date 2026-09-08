'use client';

import { useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { ShieldCheck, ShieldAlert, FileText, Quote, Scan, MapPin } from 'lucide-react';
import type { ClaimOut, PaperDetail } from '@/lib/types';
import { Badge, GlassCard, Kicker } from '@/components/ui';
import { FigureImage } from '@/components/FigureImage';
import { cn } from '@/lib/cn';

export function EvidenceRail({
  claim,
  detail,
  accent,
  onJump,
  targetEvidence,
}: {
  claim?: ClaimOut;
  detail: PaperDetail;
  accent: string;
  onJump?: (page: number, region: string, quote: string) => void;
  targetEvidence?: number;
}) {
  const evRefs = useRef<(HTMLDivElement | null)[]>([]);

  // 从图谱跳转而来时，自动滚动到并在证据卡片上高亮目标证据
  useEffect(() => {
    if (targetEvidence == null || !claim || !claim.evidence?.[targetEvidence]) return;
    const el = evRefs.current[targetEvidence];
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [targetEvidence, claim]);

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

          {claim.evidence && claim.evidence.length > 0 && (
            <div className="mt-4 space-y-2.5">
              <Kicker>来源 · SOURCES</Kicker>
              {claim.evidence.map((e, i) => {
                const isTarget = targetEvidence === i;
                return (
                  <motion.div
                    key={i}
                    ref={(el) => { evRefs.current[i] = el; }}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className={cn('rounded-xl border bg-white/[0.02] p-3 transition-all',
                      isTarget ? 'border-indigo-400/60 bg-indigo-500/10 ring-1 ring-indigo-400/40' : 'border-[var(--line)]')}
                  >
                    {isTarget && <div className="mb-1 text-[10px] font-medium text-indigo-300">● 已定位到该证据</div>}
                    <button
                      onClick={() => onJump?.(e.page, e.region, e.quote || e.text)}
                      className="group flex w-full items-center gap-2 text-left text-[11px]"
                    >
                      <FileText className="h-3.5 w-3.5" style={{ color: accent }} />
                      <span className="font-mono text-slate-300">p.{e.page}</span>
                      <span className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                        {e.region}
                      </span>
                      <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-slate-600 transition group-hover:text-indigo-300">
                        <MapPin className="h-3 w-3" /> 跳转
                      </span>
                    </button>
                    {e.quote && (
                      <div className="mt-2 rounded-md border-l-2 pl-2.5 text-[12px] italic text-slate-400" style={{ borderColor: accent }}>
                        “{e.quote}”
                      </div>
                    )}
                    <p className="mt-1.5 text-[12px] leading-snug text-slate-400">{e.text}</p>
                  </motion.div>
                );
              })}
            </div>
          )}
          {(!claim.evidence || claim.evidence.length === 0) && (
            <div className="mt-4 rounded-xl border border-dashed border-amber-500/30 p-4 text-center text-[12px] text-amber-300/90">
              该断言未绑定证据 —— 按 Evidence Gate，仅标记为 AI 解释，不作为事实。
            </div>
          )}

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
                <FigureImage image_b64={fig.image_b64} glyph_svg={fig.glyph_svg} caption={fig.caption} />
              </div>
              <p className="mt-2 text-[11px] text-slate-500">图 {fig.fig_no} · p.{fig.page}</p>
            </div>
          );
        })()}
      </GlassCard>
    </div>
  );
}
