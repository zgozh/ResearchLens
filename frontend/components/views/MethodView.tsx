'use client';

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, RotateCcw, ChevronRight } from 'lucide-react';
import type { PaperDetail, MethodStep } from '@/lib/types';
import { Btn, GlassCard, Kicker } from '@/components/ui';

export function MethodView({ detail, accent }: { detail: PaperDetail; accent: string }) {
  const steps: MethodStep[] = detail.method_steps || [];
  const [active, setActive] = useState(0); // number of revealed steps
  const [playing, setPlaying] = useState(false);
  const total = steps.length;

  useEffect(() => {
    if (!playing) return;
    if (active >= total) {
      setPlaying(false);
      return;
    }
    const id = setTimeout(() => setActive((a) => Math.min(total, a + 1)), 700);
    return () => clearTimeout(id);
  }, [playing, active, total]);

  const play = () => {
    setActive(0);
    setPlaying(true);
  };

  return (
    <div className="space-y-6">
      <GlassCard className="p-6">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <Kicker>METHOD · 算法流程动画</Kicker>
            <p className="mt-1 text-sm text-slate-400">核心方法自动动画化 —— Input → Backbone → Module → Prediction</p>
          </div>
          <div className="flex items-center gap-2">
            <Btn variant="outline" onClick={play} className="text-xs">
              {active < total ? <Play className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
              {active < total ? 'Play' : 'Replay'}
            </Btn>
          </div>
        </div>

        {/* animated pipeline */}
        <div className="min-h-[180px]">
          <div className="flex items-stretch gap-2">
            {steps.map((s, i) => {
              const revealed = i < active;
              const isCurrent = i === active - 1;
              return (
                <div key={s.id} className="flex flex-1 items-center gap-2">
                  <AnimatePresence mode="wait">
                    {revealed ? (
                      <motion.div
                        key={s.id}
                        initial={{ opacity: 0, scale: 0.85, y: 8 }}
                        animate={{ opacity: 1, scale: 1, y: 0 }}
                        transition={{ duration: 0.35, ease: 'easeOut' }}
                        className="w-full"
                      >
                        <div
                          className="relative flex h-full min-h-[130px] flex-col justify-between rounded-2xl border p-3"
                          style={{
                            borderColor: isCurrent ? s.color || accent : 'transparent',
                            background: `linear-gradient(180deg, ${(s.color || accent)}1e, ${(s.color || accent)}0a)`,
                            boxShadow: isCurrent ? `0 12px 40px -12px ${(s.color || accent)}66` : 'none',
                          }}
                        >
                          <div
                            className="grid h-7 w-7 place-items-center rounded-lg font-mono text-[11px] font-bold"
                            style={{ background: s.color || accent, color: '#0B1220' }}
                          >
                            {i + 1}
                          </div>
                          <div>
                            <div className="text-sm font-semibold text-white">{s.label}</div>
                            {s.detail && (
                              <div className="mt-1 text-[11px] leading-snug text-slate-400">{s.detail}</div>
                            )}
                          </div>
                        </div>
                      </motion.div>
                    ) : (
                      <motion.div
                        key={`${s.id}-wait`}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="w-full"
                      >
                        <div className="grid h-full min-h-[130px] place-items-center rounded-2xl border border-dashed border-white/[0.06] text-[11px] text-slate-600">
                          ·
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                  {i < total - 1 && (
                    <ChevronRight className="h-4 w-4 shrink-0 text-slate-600" />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* auto-advance pill */}
        {active > 0 && (
          <div className="mt-4 flex items-center gap-2 font-mono text-[11px] text-slate-500">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: steps[active - 1]?.color || accent }} />
            Step {active}/{total} · {steps[active - 1]?.label}
          </div>
        )}
      </GlassCard>

      {/* original method figure */}
      {detail.figures?.find((f) => f.importance === 'high') && (
        <GlassCard className="p-6">
          <Kicker>ORIGINAL FIGURE · 论文原图</Kicker>
          <p className="mt-1 mb-4 text-sm text-slate-400">
            {detail.figures.find((f) => f.importance === 'high')?.caption}
          </p>
          <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[#0F172A] p-2">
            <div
              className="mx-auto max-w-3xl [&_svg]:w-full [&_svg]:h-auto"
              dangerouslySetInnerHTML={{
                __html: detail.figures.find((f) => f.importance === 'high')?.glyph_svg || '',
              }}
            />
          </div>
        </GlassCard>
      )}

      {/* auto playback drive */}
      {playing && active < total && (
        <div className="pointer-events-none fixed inset-x-0 top-0 flex justify-center">
          <div className="mt-3 rounded-full bg-black/40 px-3 py-1 font-mono text-[11px] text-slate-200 backdrop-blur">
            animating…
          </div>
        </div>
      )}
    </div>
  );
}
