'use client';

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SkipForward, SkipBack, FileText, Layers, Table2, Quote } from 'lucide-react';
import type { ClaimSummary, PaperDetail, PresentationOut, SceneOut } from '@/lib/types';
import { Badge, Btn, GlassCard, Kicker } from '@/components/ui';
import { cn } from '@/lib/cn';
import { FigureImage } from '@/components/FigureImage';

const KIND_TONE: Record<string, string> = {
  intro: '#8B5CF6', problem: '#F43F5E', method: '#6366F1', experiment: '#38BDF8',
  result: '#34D399', limitation: '#F59E0B',
};

type Sel =
  | { type: 'figure'; fig_no: number }
  | { type: 'table'; table_no: number }
  | { type: 'text'; label: string; page?: number; region?: string; quote?: string; text?: string };

function parseEv(label: string): { page?: number; region?: string } {
  const pm = label.match(/p\.?(\d+)/i);
  return { page: pm ? Number(pm[1]) : undefined, region: label };
}

export function PresenterView({ presentation, accent, detail, claims }: {
  presentation: PresentationOut; accent: string; detail: PaperDetail; claims: ClaimSummary[];
}) {
  const scenes = presentation.scenes || [];
  const [idx, setIdx] = useState(0);
  const [sel, setSel] = useState<Sel | null>(null);
  const scene: SceneOut | undefined = scenes[idx];
  const narr = scene?.narration || {};
  const color = KIND_TONE[scene?.kind || ''] || accent;

  useEffect(() => { setSel(null); }, [idx]);

  const goto = (i: number) => { setIdx(Math.max(0, Math.min(scenes.length - 1, i))); };

  // 汇总本场景可点击内容：图 / 表 / 证据文本（figure_refs/table_refs 已由后端按论文真实图/表解析）
  const figs = (scene?.figure_refs || []).map((r) => detail.figures.find((f) => f.fig_no === Number(r))).filter((x): x is NonNullable<typeof x> => !!x);
  const tables = (scene?.table_refs || []).map((r) => detail.tables.find((t) => t.table_no === Number(r))).filter((x): x is NonNullable<typeof x> => !!x);
  const linkedTexts = (scene?.linked || []).filter((l: any) => l?.type === 'text');
  const texts: any[] = linkedTexts.length
    ? linkedTexts
    : (scene?.evidence_refs || []).filter((r) => typeof r === 'string' && !/^(图|表|figure|table)/i.test(r));

  const openText = (label: string) => {
    const { page, region } = parseEv(label);
    // 在断言证据里找匹配
    let quote = '', text = '';
    for (const c of claims) {
      // find full claim detail via evidence not available in summary; approximate via label
      void c;
    }
    setSel({ type: 'text', label, page, quote: label, text: `论文原文定位：${label}` });
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px,1fr,320px]">
      {/* 分镜列表 */}
      <div className="space-y-2">
        <Kicker className="mb-3">分镜 · STORYBOARD</Kicker>
        <div className="space-y-2">
          {scenes.map((s, i) => (
            <button key={i} onClick={() => goto(i)}
              className={cn('flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-all',
                i === idx ? 'border-white/25 bg-white/[0.06]' : 'border-[var(--line)] bg-white/[0.02] hover:bg-white/[0.04]')}>
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg font-mono text-[11px] font-bold"
                style={{ background: `${KIND_TONE[s.kind] || accent}22`, color: KIND_TONE[s.kind] || accent }}>
                {String(i + 1).padStart(2, '0')}</span>
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium text-slate-100">{s.title}</div>
                <div className="truncate text-[11px] text-slate-500">{s.kind}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 讲解内容 */}
      <GlassCard className="flex flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-[var(--line)] px-5 py-3">
          <Kicker>讲解 · TOUR</Kicker>
          <div className="flex items-center gap-1.5">
            <Btn variant="ghost" className="h-8 w-8 p-0" onClick={() => goto(idx - 1)}><SkipBack className="h-4 w-4" /></Btn>
            <Btn variant="ghost" className="h-8 w-8 p-0" onClick={() => goto(idx + 1)}><SkipForward className="h-4 w-4" /></Btn>
          </div>
        </div>

        <AnimatePresence mode="wait">
          <motion.div key={idx} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3 }} className="flex flex-1 flex-col gap-5 p-6">
            <div>
              <div className="flex items-center gap-2">
                <span className="rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wide" style={{ background: `${color}22`, color }}>{scene?.kind}</span>
                <h2 className="text-xl font-semibold text-white">{scene?.title}</h2>
              </div>
              <p className="mt-2 text-[15px] leading-relaxed text-slate-300">{scene?.summary}</p>
            </div>

            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {(scene?.steps || []).map((st, i) => {
                const label = typeof st === 'string' ? st : st?.label; const detail = typeof st === 'string' ? '' : st?.detail;
                return (
                  <div key={i} className="flex items-start gap-3 rounded-xl border border-[var(--line)] bg-white/[0.02] p-3">
                    <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md font-mono text-[10px] font-bold" style={{ background: `${color}22`, color }}>{i + 1}</span>
                    <div className="min-w-0"><div className="text-[13px] font-medium text-slate-100">{label}</div>{detail && <div className="mt-0.5 text-[12px] text-slate-500">{detail}</div>}</div>
                  </div>
                );
              })}
            </div>

            <div className="rounded-2xl border border-[var(--line)] bg-white/[0.03] p-5">
              <div className="mb-2 flex items-center gap-2 text-[11px] text-slate-500"><FileText className="h-3.5 w-3.5" style={{ color }} /> 讲解词 · 内容</div>
              <p className="text-[17px] leading-relaxed text-slate-100">{narr.script}</p>
            </div>

            {/* 涉及内容（可点击 → 右侧证据） */}
            {(figs.length > 0 || tables.length > 0 || texts.length > 0) && (
              <div>
                <div className="mb-2 text-[11px] text-slate-500">涉及内容 · 点击查看证据</div>
                <div className="flex flex-wrap gap-2">
                  {figs.map((f) => (
                    <button key={`f${f.fig_no}`} onClick={() => setSel({ type: 'figure', fig_no: f.fig_no })}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-2.5 py-1 text-[12px] text-slate-300 transition hover:border-white/25 hover:text-white">
                      <Layers className="h-3.5 w-3.5" style={{ color }} /> 图 {f.fig_no}
                    </button>
                  ))}
                  {tables.map((t) => (
                    <button key={`t${t.table_no}`} onClick={() => setSel({ type: 'table', table_no: t.table_no })}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-2.5 py-1 text-[12px] text-slate-300 transition hover:border-white/25 hover:text-white">
                      <Table2 className="h-3.5 w-3.5" style={{ color }} /> 表 {t.table_no}
                    </button>
                  ))}
                  {texts.map((r, i) => {
                    const label = typeof r === 'string' ? r : `p.${r.page} · ${r.region || '原文'}`;
                    return (
                      <button key={`t${i}`}
                        onClick={() => typeof r === 'string'
                          ? setSel({ type: 'text', label, quote: label, text: label })
                          : setSel({ type: 'text', page: r.page, region: r.region, quote: r.quote, text: r.text, label })}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-2.5 py-1 text-[12px] text-slate-300 transition hover:border-white/25 hover:text-white">
                        <Quote className="h-3.5 w-3.5" style={{ color }} /> {label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        <div className="flex items-center gap-1 px-6 pb-5">
          {scenes.map((s, i) => (
            <button key={i} onClick={() => goto(i)}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
              <div className="h-full rounded-full transition-all" style={{ width: i <= idx ? '100%' : '0%', background: i <= idx ? color : 'transparent' }} />
            </button>
          ))}
        </div>
      </GlassCard>

      {/* 右侧证据面板 */}
      <div className="lg:block hidden">
        <GlassCard className="sticky top-4 max-h-[calc(100vh-6rem)] overflow-y-auto p-5">
          <Kicker className="mb-3">证据 · EVIDENCE</Kicker>
          <AnimatePresence mode="wait">
            <motion.div key={sel ? JSON.stringify(sel) : 'empty'} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {!sel && (
                <div className="rounded-2xl border border-dashed border-[var(--line)] p-6 text-center">
                  <Quote className="mx-auto mb-3 h-7 w-7 text-slate-600" />
                  <p className="text-[13px] text-slate-500">点击左侧「涉及内容」的<b className="text-slate-300">图 / 表 / 原文</b></p>
                  <p className="mt-1 text-[12px] text-slate-600">这里会展示捆绑该分镜的真实证据。</p>
                </div>
              )}
              {sel?.type === 'figure' && (() => {
                const f = detail.figures.find((x) => x.fig_no === sel.fig_no);
                return f ? (
                  <div>
                    <div className="mb-2 flex items-center gap-2">
                      <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: `${color}22`, color }}><Layers className="h-3.5 w-3.5" /></span>
                      <span className="text-sm font-semibold text-white">图 {f.fig_no}</span>
                      <span className="ml-auto font-mono text-[10px] text-slate-500">p.{f.page}</span>
                    </div>
                    <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[#0F172A] p-2">
                      <FigureImage image_b64={f.image_b64} glyph_svg={f.glyph_svg} caption={f.caption} />
                    </div>
                    <p className="mt-2 text-[13px] text-slate-300">{f.caption}</p>
                    {f.description && <p className="mt-1 text-[12px] text-slate-500">{f.description}</p>}
                  </div>
                ) : <p className="text-[13px] text-slate-500">未找到该图。</p>;
              })()}
              {sel?.type === 'table' && (() => {
                const t = detail.tables.find((x) => x.table_no === sel.table_no);
                if (!t) return <p className="text-[13px] text-slate-500">未找到该表。</p>;
                return (
                  <div>
                    <div className="mb-2 flex items-center gap-2">
                      <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: `${color}22`, color }}><Table2 className="h-3.5 w-3.5" /></span>
                      <span className="text-sm font-semibold text-white">表 {t.table_no}</span>
                      <span className="ml-auto font-mono text-[10px] text-slate-500">p.{t.page}</span>
                    </div>
                    <div className="overflow-hidden rounded-xl border border-[var(--line)]">
                      <table className="w-full text-left text-[12px]">
                        <thead><tr className="bg-white/[0.04]">{(t.content[0] || []).map((h, i) => <th key={i} className="px-2.5 py-1.5 font-medium text-slate-200">{h}</th>)}</tr></thead>
                        <tbody>{t.content.slice(1).map((row, ri) => <tr key={ri} className="border-t border-[var(--line)]">{row.map((cell, ci) => <td key={ci} className="px-2.5 py-1.5 text-slate-300">{cell}</td>)}</tr>)}</tbody>
                      </table>
                    </div>
                  </div>
                );
              })()}
              {sel?.type === 'text' && (
                <div className="rounded-xl border-l-2 bg-white/[0.02] p-3 text-[13px] leading-relaxed text-slate-300" style={{ borderColor: color }}>
                  <div className="mb-1.5 flex items-center gap-1.5 font-mono text-[11px] text-slate-500">
                    <Quote className="h-3 w-3" style={{ color }} />
                    {sel.label}{sel.page ? ` · p.${sel.page}` : ''}
                  </div>
                  {sel.quote && <p className="text-slate-200">“{sel.quote}”</p>}
                  {sel.text && sel.text !== sel.quote && <p className="mt-1.5 text-slate-400">{sel.text}</p>}
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </GlassCard>
      </div>
    </div>
  );
}
