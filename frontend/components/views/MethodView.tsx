'use client';

import { useState, useEffect, useMemo, useRef } from 'react';
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

/** 步骤 label 实测是一整句断言（最长 164 字），流水线/状态行必须截断。 */
function shortLabel(label: string | undefined, max = 26): string {
  if (!label) return '';
  const head = label.split(/[。；;!?！？\n]/)[0] || label;
  return head.length > max ? `${head.slice(0, max)}…` : head;
}

export function MethodView({ detail, accent }: { detail: PaperDetail; accent: string }) {
  const steps: MethodStep[] = detail.method_steps || [];
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [explored, setExplored] = useState<number | undefined>(0);
  const [media, setMedia] = useState<MediaItem | null>(null);
  const heroRef = useRef<HTMLDivElement>(null);
  const total = steps.length;
  const current = steps[explored ?? -1];
  // 每个步骤的图表**按该步骤自己的证据**取（后端 figure_refs/table_refs，
  // 由该断言的 statement→media 绑定得出）；旧的单一 figure_ref 仅作兼容。
  const stepFigures = useMemo(() => {
    const refs = current?.figure_refs?.length
      ? current.figure_refs
      : current?.figure_ref != null
        ? [current.figure_ref]
        : [];
    return refs
      .map((no) => detail.figures.find((f) => f.fig_no === Number(no)))
      .filter((f): f is NonNullable<typeof f> => !!f);
  }, [current, detail.figures]);
  const relatedTables = useMemo(() => {
    const refs = current?.table_refs ?? [];
    return refs
      .map((no) => detail.tables.find((t) => t.table_no === Number(no)))
      .filter((t): t is NonNullable<typeof t> => !!t);
  }, [current, detail.tables]);

  useEffect(() => {
    if (!playing) return;
    if (active >= total) { setPlaying(false); return; }
    const id = setTimeout(() => setActive((a) => Math.min(total, a + 1)), 700);
    return () => clearTimeout(id);
  }, [playing, active, total]);

  const play = () => { setActive(0); setPlaying(true); };
  // D29 修复：importance 实测 24/24 全是 'medium'，此前写死 `=== 'high'`
  // 导致"论文原图"永不渲染。改为"优先 high，否则取第一张"。
  const hero = detail.figures?.find((f) => f.importance === 'high') ?? detail.figures?.[0];

  return (
    <div className="space-y-6">
      <GlassCard className="p-6">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <Kicker>方法动画 · METHOD</Kicker>
            {/* 这行此前写死"作用 → 输入 → 骨干 → 模块 → 预测"，与实现不符（会误导）：
                实际是"方法/实验章里按原文顺序排列的已验证断言，每条一步"。 */}
            <p className="mt-1 text-sm text-slate-400">
              每个步骤 = 方法/实验章节里的一条**已验证断言**，按原文顺序排列；点击可查看该步骤的
              原文依据与关联图表。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Btn variant="outline" onClick={play} className="text-xs">
              {active < total ? <Play className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
              {active < total ? '播放' : '重播'}
            </Btn>
          </div>
        </div>

        {/* 动画流水线 */}
        {total === 0 ? (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-[13px] text-amber-200">
            本篇论文尚未抽取到方法步骤（需要已通过证据校验的 METHOD 类断言）。
            下方仍展示论文原图与关联图表。
          </div>
        ) : (
        <>
        <div className="flex items-stretch gap-2">
          {steps.map((s, i) => {
            const revealed = i < active;
            const isCurrent = i === active - 1;
            const exploredHere = explored === i;
            // 阶段只在**变化处**标注：同章步骤不再每张卡片都重复同一个标签
            // （用户反馈"点开每个步骤标签都显示同一个实验"）。
            const phaseChanged = i === 0 || (steps[i - 1]?.phase || '') !== (s.phase || '');
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
                          style={{ borderColor: isCurrent ? s.color || accent : 'transparent',
                            background: `linear-gradient(180deg, ${(s.color || accent)}1e, ${(s.color || accent)}0a)`,
                            boxShadow: isCurrent ? `0 12px 40px -12px ${(s.color || accent)}66` : 'none' }}>
                          <div className="flex items-center gap-2">
                            <span className="grid h-7 w-7 place-items-center rounded-lg font-mono text-[11px] font-bold"
                              style={{ background: s.color || accent, color: '#0B1220' }}>{i + 1}</span>
                            {(s.figure_refs?.length || s.table_refs?.length) ? (
                              <span className="font-mono text-[10px] text-slate-400">
                                {s.figure_refs?.length ? `图×${s.figure_refs.length}` : ''}
                                {s.table_refs?.length ? ` 表×${s.table_refs.length}` : ''}
                              </span>
                            ) : null}
                          </div>
                          <div>
                            {phaseChanged && (s.phase) && (
                              <div className="mb-0.5 font-mono text-[10px] uppercase tracking-wide text-slate-500">
                                {PHASE_LABEL[s.phase || ''] || s.phase}
                              </div>
                            )}
                            <div className="text-sm font-semibold text-white">{shortLabel(s.label)}</div>
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
        <p className="mt-3 text-[11px] text-slate-500">
          播放会按顺序揭示每一步；点任意步骤查看它的原文依据与关联图表。
        </p>
        </>
        )}

        {active > 0 && (
          <div className="mt-4 flex items-center gap-2 font-mono text-[11px] text-slate-500">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: steps[active - 1]?.color || accent }} />
            步骤 {active}/{total} · {shortLabel(steps[active - 1]?.label, 44)}
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
                {steps[explored!].phase && (
                  <Badge tone="slate">{PHASE_LABEL[steps[explored!].phase || ''] || steps[explored!].phase}</Badge>
                )}
                <h3 className="text-lg font-semibold text-white">{shortLabel(steps[explored!].label, 60)}</h3>
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
              {/* 关联图 + 关联表：**该步骤自己的**证据（可能多个），可点击放大 */}
              {(stepFigures.length > 0 || relatedTables.length > 0) && (
                <div className="mt-4">
                  <div className="mb-2 text-[11px] text-slate-500">
                    该步骤的关联图表（来自它引用的证据）
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {stepFigures.map((f) => (
                      <button key={`rf${f.fig_no}`} onClick={() => setMedia({ type: 'figure', figure: f })}
                        className="inline-flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white/[0.03] px-4 py-2 text-[13px] font-medium text-indigo-300 transition hover:bg-white/[0.06]">
                        <Layers className="h-4 w-4" /> 图 {f.fig_no}
                      </button>
                    ))}
                    {relatedTables.map((t) => (
                      <button key={`rt${t.table_no}`} onClick={() => setMedia({ type: 'table', table: t })}
                        className="inline-flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white/[0.03] px-4 py-2 text-[13px] font-medium text-indigo-300 transition hover:bg-white/[0.06]">
                        <Table2 className="h-4 w-4" /> 表 {t.table_no}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {stepFigures.length === 0 && relatedTables.length === 0 && (
                <p className="mt-4 text-[12px] text-slate-500">
                  该步骤的断言尚未绑定图表（证据门只把 caption 与陈述词面重合的图表绑上；
                  不重合就不绑，避免给出无关的图）。
                </p>
              )}
              {hero && stepFigures.length === 0 && relatedTables.length === 0 && (
                <button onClick={() => heroRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                  className="mt-2 inline-flex items-center gap-2 rounded-xl border border-[var(--line)] bg-white/[0.03] px-4 py-2 text-[13px] font-medium text-indigo-300 transition hover:bg-white/[0.06]">
                  <FileText className="h-4 w-4" /> 查看论文原图（图 {hero.fig_no}，非本步骤专属）
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
