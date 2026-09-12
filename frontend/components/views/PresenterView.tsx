'use client';

import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { SkipForward, SkipBack, FileText, Layers, Table2, Quote } from 'lucide-react';
import type { ClaimSummary, PaperDetail, PresentationOut, SceneOut } from '@/lib/types';
import { Badge, Btn, GlassCard, Kicker } from '@/components/ui';
import { cn } from '@/lib/cn';
import { FigureImage } from '@/components/FigureImage';
import { TableRender } from '@/components/TableRender';
import { LongText } from '@/components/LongText';

/** 讲解里出现的长句断言/步骤，单行展示前必须截断。 */
function shortText(text: string | undefined, max: number): string {
  const raw = (text || '').trim();
  if (raw.length <= max) return raw;
  return `${raw.slice(0, max)}…`;
}

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

/** 后端 step id 形如 ``s:<rev>:<i>:<hash>:step:<n>``——它是**内部标识**，不是给人看的标签。
 *  旧实现把它直接当 label 渲染，于是讲解里出现一串 "s:5ef436e7:0:5510:step:0"。 */
const STEP_ID_RE = /^s:[^:]*:\d+:[^:]*:step:(\d+)$/;

/** 把场景步骤解析为可读 ``{label, detail}``；解析不出来就**丢掉**，绝不渲染裸 ID。 */
function resolveSteps(
  raw: any[], methodSteps: { label: string; detail?: string; text?: string }[],
): { label: string; detail: string }[] {
  const out: { label: string; detail: string }[] = [];
  for (const st of raw || []) {
    if (st && typeof st === 'object') {
      const label = String(st.label ?? '');
      const detail = String(st.detail ?? '');
      if (label || detail) out.push({ label, detail });
      continue;
    }
    const text = String(st ?? '');
    const m = STEP_ID_RE.exec(text);
    if (m) {
      const step = methodSteps[Number(m[1])];
      if (step) out.push({ label: step.label, detail: step.detail || step.text || '' });
      continue; // 索引越界 → 丢弃（宁缺勿显示内部 ID）
    }
    if (text) out.push({ label: text, detail: '' });
  }
  return out;
}

export function PresenterView({ presentation, accent, detail, claims, statements }: {
  presentation: PresentationOut;
  accent: string;
  detail: PaperDetail;
  claims: ClaimSummary[];
  /** ``statement_id → 正文``；讲解的 evidence_refs 实际是 statement id，必须回填正文。 */
  statements?: { id: string; text: string }[];
}) {
  const scenes = presentation.scenes || [];
  const [idx, setIdx] = useState(0);
  const [sel, setSel] = useState<Sel | null>(null);
  const scene: SceneOut | undefined = scenes[idx];
  const narr = scene?.narration || {};
  const color = KIND_TONE[scene?.kind || ''] || accent;

  useEffect(() => { setSel(null); }, [idx]);

  const goto = (i: number) => { setIdx(Math.max(0, Math.min(scenes.length - 1, i))); };

  const statementText = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of statements ?? []) if (s?.id && (s.text || '').trim()) map.set(s.id, s.text);
    return map;
  }, [statements]);

  // 汇总本场景可点击内容：图 / 表 / 证据文本
  const figs = (scene?.figure_refs || []).map((r) => detail.figures.find((f) => f.fig_no === Number(r))).filter((x): x is NonNullable<typeof x> => !!x);
  const tables = (scene?.table_refs || []).map((r) => detail.tables.find((t) => t.table_no === Number(r))).filter((x): x is NonNullable<typeof x> => !!x);
  const linkedTexts = (scene?.linked || []).filter((l: any) => l?.type === 'text');
  // D29 修复：此前把 evidence_refs（实为 ``stmt-*`` 断言 id）当"原文定位"渲染，
  // 用户看到的是"论文原文定位：stmt-01f2b3533bf7921f6ef9b4f8"。现在按 id 回填陈述正文。
  const statementRefs: { id: string; text: string }[] = linkedTexts.length
    ? []
    : (scene?.evidence_refs || [])
        .map((r) => (typeof r === 'string' ? r : String(r?.statement_id ?? r?.id ?? '')))
        .map((id) => ({ id, text: statementText.get(id) || '' }))
        .filter((x) => x.id && x.text);
  const unresolvedRefs = linkedTexts.length
    ? 0
    : (scene?.evidence_refs || []).length - statementRefs.length;

  const steps = resolveSteps(scene?.steps || [], detail.method_steps || []);

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
              {steps.map((st, i) => (
                <div key={i} className="flex items-start gap-3 rounded-xl border border-[var(--line)] bg-white/[0.02] p-3">
                  <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md font-mono text-[10px] font-bold" style={{ background: `${color}22`, color }}>{i + 1}</span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-slate-100">{shortText(st.label, 60)}</div>
                    {st.detail && <div className="mt-0.5 line-clamp-3 text-[12px] text-slate-500">{st.detail}</div>}
                  </div>
                </div>
              ))}
            </div>

            <div className="rounded-2xl border border-[var(--line)] bg-white/[0.03] p-5">
              <div className="mb-2 flex items-center gap-2 text-[11px] text-slate-500"><FileText className="h-3.5 w-3.5" style={{ color }} /> 讲解词 · 内容</div>
              <LongText
                text={narr.script}
                paragraphClassName="text-[16px] leading-8 text-slate-100"
              />
            </div>

            {/* 涉及内容（可点击 → 右侧证据） */}
            {(figs.length > 0 || tables.length > 0 || statementRefs.length > 0 || unresolvedRefs > 0) && (
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
                  {statementRefs.map((r) => (
                    <button key={r.id}
                      onClick={() => setSel({ type: 'text', label: '已验证断言', text: r.text, quote: r.text })}
                      className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-2.5 py-1 text-[12px] text-slate-300 transition hover:border-white/25 hover:text-white">
                      <Quote className="h-3.5 w-3.5 shrink-0" style={{ color }} />
                      <span className="truncate">{shortText(r.text, 34)}</span>
                    </button>
                  ))}
                  {unresolvedRefs > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-[var(--line)] px-2.5 py-1 text-[11px] text-slate-600">
                      另有 {unresolvedRefs} 条证据引用暂无法解析为正文
                    </span>
                  )}
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
                      <FigureImage image_url={f.image_url} image_b64={f.image_b64} glyph_svg={f.glyph_svg} caption={f.caption} />
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
                    <div className="overflow-hidden rounded-xl border border-[var(--line)] p-1">
                      <TableRender table={t} className="rl-table text-[12px]" />
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
