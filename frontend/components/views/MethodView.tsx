'use client';

import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, RotateCcw, ChevronRight, Info, FileText, Layers, Table2 } from 'lucide-react';
import type { PaperDetail, MethodStep } from '@/lib/types';
import { Badge, Btn, GlassCard, Kicker } from '@/components/ui';
import { MediaModal, type MediaItem } from '@/components/MediaModal';
import { RichText } from '@/components/RichText';
import { FigureImage } from '@/components/FigureImage';
import { cn } from '@/lib/cn';

const PHASE_LABEL: Record<string, string> = {
  input: '输入', encoder: '编码', module: '核心模块', decoder: '解码', output: '输出',
};

export function MethodView({ detail, accent }: { detail: PaperDetail; accent: string }) {
  const steps: MethodStep[] = detail.method_steps || [];
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [explored, setExplored] = useState<number | undefined>(0);
  const [media, setMedia] = useState<MediaItem | null>(null);
  const heroRef = useRef<HTMLDivElement>(null);
  const total = steps.length;
  const stepFigure = detail.figures.find((f) => f.fig_no === steps[explored ?? -1]?.figure_ref);
  const relatedTables = detail.tables.filter((t) =>
    steps[explored ?? -1]?.text?.includes(`表${t.table_no}`) || steps[explored ?? -1]?.detail?.includes(`表${t.table_no}`),
  );

  useEffect(() => {
    if (!playing) return;
    if (active >= total) { setPlaying(false); return; }
    const id = setTimeout(() => setActive((a) => Math.min(total, a + 1)), 700);
    return () => clearTimeout(id);
  }, [playing, active, total]);

  const play = () => { setActive(0); setPlaying(true); };
  const hero = detail.figures?.find((f) => f.importance === 'high');

  return (
    <div className="space-y-6">
      <GlassCard className="p-6">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <Kicker>方法动画 · METHOD</Kicker>
            <p className="mt-1 text-sm text-slate-400">点击任意步骤可探索其作用 → 输入 → 骨干 → 模块 → 预测</p>
          </div>
          <div className="flex items-center gap-2">
            <Btn variant="outline" onClick={play} className="text-xs">
              {active < total ? <Play className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
              {active < total ? '播放' : '重播'}
            </Btn>
          </div>
        </div>

        {/* 动画流水线 */}
        <div className="flex items-stretch gap-2">
          {steps.map((s, i) => {
            const revealed = i < active;
            const current = i === active - 1;
            const exploredHere = explored === i;
            return (
              <div key={s.id} className="flex flex-1 items-center gap-2">
                <button
                  onClick={() => { setActive(Math.max(i + 1, active)); setExplored(i); }}
                  className="block w-full text-left"
                >
                  <AnimatePresence mode="wait">
                    {revealed ? (
                      <motion.div key={s.id} initial={{ opacity: 0, scale: 0.85, y: 8 }} animate={{ opacity: 1, scale: 1, y: 0 }}
                        transition={{ duration: 0.35, ease: 'easeOut' }}>
                        <div
                          className={cn('relative flex h-full min-h-[130px] flex-col justify-between rounded-2xl border p-3 transition',
                            exploredHere && 'ring-2 ring-white/30')}
                          style={{ borderColor: current ? s.color || accent : 'transparent',
                            background: `linear-gradient(180deg, ${(s.color || accent)}1e, ${(s.color || accent)}0a)`,
                            boxShadow: current ? `0 12px 40px -12px ${(s.color || accent)}66` : 'none' }}>
                          <div className="grid h-7 w-7 place-items-center rounded-lg font-mono text-[11px] font-bold"
                            style={{ background: s.color || accent, color: '#0B1220' }}>{i + 1}</div>
                          <div>
                            <div className="text-sm font-semibold text-white">{s.label}</div>
                            {s.detail && <div className="mt-1 text-[11px] leading-snug text-slate-400">{s.detail}</div>}
                          </div>
                        </div>
                      </motion.div>
                    ) : (
                      <motion.div key={`${s.id}-wait`} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                        <div className="grid h-full min-h-[130px] place-items-center rounded-2xl border border-dashed border-white/[0.06] text-[11px] text-slate-600">·</div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </button>
                {i < total - 1 && <ChevronRight className="h-4 w-4 shrink-0 text-slate-600" />}
              </div>
            );
          })}
        </div>

        {active > 0 && (
          <div className="mt-4 flex items-center gap-2 font-mono text-[11px] text-slate-500">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: steps[active - 1]?.color || accent }} />
            步骤 {active}/{total} · {steps[active - 1]?.label}
          </div>
        )}
      </GlassCard>

      {/* 步骤探索 */}
      {steps[explored ?? -1] && (
        <AnimatePresence mode="wait">
          <motion.div key={explored} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
            <GlassCard className="p-6">
              <div className="flex items-center gap-2">
                <Badge tone="accent">步骤 {String((explored ?? 0) + 1).padStart(2, '0')}</Badge>
                <Badge tone="slate">{PHASE_LABEL[steps[explored!].phase || ''] || steps[explored!].phase}</Badge>
                <h3 className="text-lg font-semibold text-white">{steps[explored!].label}</h3>
              </div>
              <p className="mt-2 flex items-start gap-2 text-[14px] leading-relaxed text-slate-300">
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
                <span className="min-w-0">
                  {(() => {
                    const st = steps[explored!];
                    return st.text ? (
                      <RichText
                        text={st.text}
                        figures={detail.figures}
                        tables={detail.tables}
                        onOpenMedia={setMedia}
                      />
                    ) : (st.detail || '这一环节的作用可结合论文原图理解。');
                  })()}
                </span>
              </p>
              {/* 关联图 + 关联表（可点击放大） */}
              {(stepFigure || relatedTables.length > 0) && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {stepFigure && (
                    <button onClick={() => setMedia({ type: 'figure', figure: stepFigure })}
                      className="inline-flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white/[0.03] px-4 py-2 text-[13px] font-medium text-indigo-300 transition hover:bg-white/[0.06]">
                      <Layers className="h-4 w-4" /> 查看关联图（图 {stepFigure.fig_no}）
                    </button>
                  )}
                  {relatedTables.map((t) => (
                    <button key={`rt${t.table_no}`} onClick={() => setMedia({ type: 'table', table: t })}
                      className="inline-flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white/[0.03] px-4 py-2 text-[13px] font-medium text-indigo-300 transition hover:bg-white/[0.06]">
                      <Table2 className="h-4 w-4" /> 查看关联表（表 {t.table_no}）
                    </button>
                  ))}
                </div>
              )}
              {hero && !stepFigure && relatedTables.length === 0 && (
                <button onClick={() => heroRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                  className="mt-4 inline-flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white/[0.03] px-4 py-2 text-[13px] font-medium text-indigo-300 transition hover:bg-white/[0.06]">
                  <FileText className="h-4 w-4" /> 查看方法原图（图 {hero.fig_no}）
                </button>
              )}
            </GlassCard>
          </motion.div>
        </AnimatePresence>
      )}

      {/* 论文原图 */}
      {hero && (
        <div ref={heroRef}>
          <GlassCard className="p-6">
            <Kicker>论文原图 · ORIGINAL FIGURE</Kicker>
            <p className="mt-1 mb-4 text-sm text-slate-400">{hero.caption}</p>
            <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[#0F172A] p-2">
              <FigureImage image_url={hero.image_url} image_b64={hero.image_b64} glyph_svg={hero.glyph_svg} caption={hero.caption} />
            </div>
            {hero.description && <p className="mt-3 text-[12px] text-slate-500">{hero.description}</p>}
          </GlassCard>
        </div>
      )}
      <MediaModal item={media} accent={accent} onClose={() => setMedia(null)} />
    </div>
  );
}
