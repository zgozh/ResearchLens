'use client';

import { useEffect, useRef } from 'react';
import { FileText, Table2 } from 'lucide-react';
import type { PaperDetail } from '@/lib/types';
import { GlassCard, Kicker } from '@/components/ui';

function highlightText(text: string, quote?: string) {
  if (!quote || !text) return <>{text}</>;
  const idx = text.indexOf(quote);
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded bg-indigo-500/30 px-0.5 text-white">{quote}</mark>
      {text.slice(idx + quote.length)}
    </>
  );
}

export function PaperView({ detail, target }: { detail: PaperDetail; target?: { kind?: string; page?: number; quote?: string } }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!target?.quote) return;
    const id = `sec-${target.kind || 'x'}`;
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [target]);

  const targetIndex = detail.sections.findIndex((s) => s.kind === target?.kind);

  return (
    <div ref={containerRef} className="mx-auto max-w-3xl">
      {target?.quote && (
        <div className="mb-4 rounded-xl border border-indigo-500/40 bg-indigo-500/10 px-4 py-2.5 text-[13px] text-indigo-200">
          已在论文中定位并高亮：<span className="font-mono">“{target.quote}”</span> {target.page ? `· p.${target.page}` : ''}
        </div>
      )}

      <GlassCard className="p-8">
        <Kicker className="mb-3">论文阅读 · PAPER</Kicker>
        <h1 className="text-2xl font-semibold leading-tight text-white">{detail.title}</h1>
        <p className="mt-1 font-mono text-[12px] text-slate-500">{detail.subtitle}</p>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px] text-slate-500">
          <span>{detail.authors.join(', ')}</span>
          <span>{detail.year}</span>
          <span>{detail.domain}</span>
        </div>
        <div className="mt-5 border-t border-[var(--line)] pt-5">
          <Kicker>摘要</Kicker>
          <p className="mt-2 text-[15px] leading-relaxed text-slate-300">{detail.abstract}</p>
        </div>
      </GlassCard>

      <div className="mt-6 space-y-6">
        {detail.sections.map((sec, si) => {
          const isTarget = targetIndex === si || sec.kind === target?.kind;
          const targetId = isTarget ? `sec-${sec.kind}` : undefined;
          return (
            <GlassCard key={sec.heading} id={targetId} className={`p-6 ${isTarget ? 'ring-2 ring-indigo-500/40' : ''}`}>
              <div className="mb-2 flex items-center gap-2">
                <FileText className="h-4 w-4 text-slate-500" />
                <h2 className="text-lg font-semibold text-white">{sec.heading}</h2>
                <span className="ml-auto rounded-md bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] text-slate-500">p.{sec.page}</span>
              </div>
              {sec.body ? (
                <p className="text-[14px] leading-relaxed text-slate-400">{highlightText(sec.body, isTarget ? target?.quote : undefined)}</p>
              ) : (
                <p className="text-[14px] leading-relaxed text-slate-400">{sec.summary}</p>
              )}
              {(sec.key_points?.length ?? 0) > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {sec.key_points.map((kp, j) => (
                    <li key={j} className="flex items-start gap-2 text-[12px] text-slate-500">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-400" />{kp}
                    </li>
                  ))}
                </ul>
              )}
            </GlassCard>
          );
        })}

        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          {detail.figures.map((f) => (
            <GlassCard key={`fig-${f.fig_no}`} className="p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-200">图 {f.fig_no}</span>
                <span className="font-mono text-[10px] text-slate-500">p.{f.page}</span>
              </div>
              <div className="overflow-hidden rounded-lg border border-[var(--line)] bg-[#0F172A] p-1">
                <div className="[&_svg]:w-full [&_svg]:h-auto" dangerouslySetInnerHTML={{ __html: f.glyph_svg }} />
              </div>
              <p className="mt-2 text-[11px] text-slate-500">{f.caption}</p>
            </GlassCard>
          ))}
        </div>

        <div className="space-y-6">
          {detail.tables.map((t) => (
            <GlassCard key={`tbl-${t.table_no}`} className="p-6">
              <div className="mb-2 flex items-center gap-2">
                <Table2 className="h-4 w-4 text-slate-500" />
                <span className="text-sm font-semibold text-slate-200">表 {t.table_no}</span>
                <span className="ml-auto font-mono text-[10px] text-slate-500">p.{t.page}</span>
              </div>
              <p className="mb-3 text-[12px] text-slate-500">{t.caption}</p>
              <div className="overflow-hidden rounded-lg border border-[var(--line)]">
                <table className="w-full text-left text-[13px]">
                  <thead>
                    <tr className="bg-white/[0.04]">
                      {(t.content[0] || []).map((h, i) => <th key={i} className="px-3 py-2 font-medium text-slate-200">{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {t.content.slice(1).map((row, ri) => (
                      <tr key={ri} className="border-t border-[var(--line)]">
                        {row.map((cell, ci) => <td key={ci} className="px-3 py-2 text-slate-400">{cell}</td>)}
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
        </div>
      </div>
    </div>
  );
}
