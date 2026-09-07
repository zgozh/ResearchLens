'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, Pause, SkipForward, SkipBack, Volume2, VolumeX, FileText, Layers } from 'lucide-react';
import type { PresentationOut, SceneOut } from '@/lib/types';
import { Badge, Btn, GlassCard, Kicker } from '@/components/ui';
import { cn } from '@/lib/cn';

const KIND_TONE: Record<string, string> = {
  intro: '#8B5CF6',
  problem: '#F43F5E',
  method: '#6366F1',
  experiment: '#38BDF8',
  result: '#34D399',
  limitation: '#F59E0B',
};

// 讲解语音（zh-CN），仅在“播放中且开语音”时朗读；失败/不可用自动回落字幕
function speak(text: string, enabled: boolean) {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  if (!enabled || !text) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'zh-CN';
    u.rate = 0.95;
    const voices = window.speechSynthesis.getVoices();
    const zh = voices.find((v) => v.lang?.toLowerCase().startsWith('zh'));
    if (zh) u.voice = zh;
    window.speechSynthesis.speak(u);
  } catch {
    /* 默认回落字幕 */
  }
}

export function PresenterView({ presentation, accent }: { presentation: PresentationOut; accent: string }) {
  const scenes = presentation.scenes || [];
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [voiceOn, setVoiceOn] = useState(false); // 语音默认关，点图标才朗读
  const scene: SceneOut | undefined = scenes[idx];
  const narr = scene?.narration || {};
  const color = KIND_TONE[scene?.kind || ''] || accent;

  // 自动推进（仅当 playing）
  useEffect(() => {
    if (!playing) return;
    const id = setTimeout(() => {
      if (idx + 1 < scenes.length) setIdx(idx + 1);
      else setPlaying(false);
    }, 6000);
    return () => clearTimeout(id);
  }, [playing, idx, scenes.length]);

  // 朗读：只在“播放中且开语音”时读当前场景；暂停或切到非播放即停
  useEffect(() => {
    if (playing && voiceOn) {
      speak((narr.script as string) || (narr.subtitle as string), true);
    } else {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel();
    }
  }, [idx, playing, voiceOn, narr.script, narr.subtitle]);

  const goto = (i: number) => {
    setIdx(Math.max(0, Math.min(scenes.length - 1, i)));
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px,1fr]">
      {/* 分镜列表 */}
      <div className="space-y-2">
        <Kicker className="mb-3">分镜 · STORYBOARD</Kicker>
        <div className="space-y-2">
          {scenes.map((s, i) => (
            <button
              key={i}
              onClick={() => { goto(i); setPlaying(false); }}
              className={cn(
                'flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-all',
                i === idx ? 'border-white/25 bg-white/[0.06]' : 'border-[var(--line)] bg-white/[0.02] hover:bg-white/[0.04]',
              )}
            >
              <span
                className="grid h-8 w-8 shrink-0 place-items-center rounded-lg font-mono text-[11px] font-bold"
                style={{ background: `${KIND_TONE[s.kind] || accent}22`, color: KIND_TONE[s.kind] || accent }}
              >
                {String(i + 1).padStart(2, '0')}
              </span>
              <div className="min-w-0">
                <div className="truncate text-[13px] font-medium text-slate-100">{s.title}</div>
                <div className="truncate text-[11px] text-slate-500">{s.summary}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 剧情播放器 */}
      <GlassCard className="flex flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-[var(--line)] px-5 py-3">
          <div className="flex items-center gap-2">
            <Kicker>场景化讲解 · STORY &amp; NARRATION</Kicker>
          </div>
          <div className="flex items-center gap-1.5">
            <Btn variant="outline" className="h-8 px-3" onClick={() => setPlaying((p) => !p)}>
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              {playing ? '暂停' : idx + 1 < scenes.length ? '播放' : '重播'}
            </Btn>
            <Btn variant="ghost" className="h-8 w-8 p-0" onClick={() => { goto(idx - 1); setPlaying(false); }}>
              <SkipBack className="h-4 w-4" />
            </Btn>
            <Btn variant="ghost" className="h-8 w-8 p-0" onClick={() => { goto(idx + 1); setPlaying(false); }}>
              <SkipForward className="h-4 w-4" />
            </Btn>
            <Btn variant="ghost" className="h-8 w-8 p-0" onClick={() => setVoiceOn((v) => !v)} aria-label="朗读开关">
              {voiceOn ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
            </Btn>
          </div>
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={idx}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3 }}
            className="flex flex-1 flex-col gap-5 p-6"
          >
            {/* 标题 */}
            <div>
              <div className="flex items-center gap-2">
                <span
                  className="rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wide"
                  style={{ background: `${color}22`, color }}
                >
                  {scene?.kind}
                </span>
                <h2 className="text-xl font-semibold text-white">{scene?.title}</h2>
              </div>
              <p className="mt-2 text-[15px] leading-relaxed text-slate-300">{scene?.summary}</p>
            </div>

            {/* 逐步要点 */}
            {(scene?.steps || []).length > 0 && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {(scene?.steps || []).map((st, i) => {
                  const label = typeof st === 'string' ? st : st?.label;
                  const detail = typeof st === 'string' ? '' : st?.detail;
                  return (
                    <div key={i} className="flex items-start gap-3 rounded-xl border border-[var(--line)] bg-white/[0.02] p-3">
                      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md font-mono text-[10px] font-bold" style={{ background: `${color}22`, color }}>
                        {i + 1}
                      </span>
                      <div className="min-w-0">
                        <div className="text-[13px] font-medium text-slate-100">{label}</div>
                        {detail && <div className="mt-0.5 text-[12px] text-slate-500">{detail}</div>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* 讲解词（主角） */}
            <div className="rounded-2xl border border-[var(--line)] bg-white/[0.03] p-5">
              <div className="mb-2 flex items-center gap-2 text-[11px] text-slate-500">
                <FileText className="h-3.5 w-3.5" style={{ color }} /> 讲解词 · NARRATION
              </div>
              <p className="text-[17px] leading-relaxed text-slate-100">{narr.script}</p>
              {narr.subtitle && (
                <div className="mt-4 border-t border-dashed border-[var(--line)] pt-3 font-mono text-[13px] text-slate-400">
                  <span className="mr-2 rounded bg-black/30 px-1.5 py-0.5 text-[10px] text-slate-500">字幕</span>
                  {narr.subtitle}
                </div>
              )}
            </div>

            {/* 引用的证据/原图 */}
            <div className="flex flex-wrap gap-2">
              {(scene?.evidence_refs || []).map((r, i) => (
                <span key={i} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-2.5 py-1 text-[12px] text-slate-300">
                  <Layers className="h-3.5 w-3.5 text-slate-500" /> 证据 · {r}
                </span>
              ))}
              {(scene?.figure_refs || []).map((f, i) => (
                <span key={`f${i}`} className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-2.5 py-1 text-[12px] text-slate-300">
                  <FileText className="h-3.5 w-3.5 text-slate-500" /> 原图 {f}
                </span>
              ))}
            </div>
          </motion.div>
        </AnimatePresence>

        {/* 进度条 */}
        <div className="flex items-center gap-1 px-6 pb-5">
          {scenes.map((s, i) => (
            <button key={i} onClick={() => { goto(i); setPlaying(false); }}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
              <div className="h-full rounded-full transition-all"
                style={{ width: i <= idx ? '100%' : '0%', background: i <= idx ? color : 'transparent' }} />
            </button>
          ))}
        </div>
      </GlassCard>
    </div>
  );
}
