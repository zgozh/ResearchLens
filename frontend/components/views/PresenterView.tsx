'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, Pause, SkipForward, SkipBack, Volume2, VolumeX } from 'lucide-react';
import type { PresentationOut, SceneOut } from '@/lib/types';
import { Btn, GlassCard, Kicker } from '@/components/ui';
import { cn } from '@/lib/cn';

const KIND_TONE: Record<string, string> = {
  intro: '#8B5CF6',
  problem: '#F43F5E',
  method: '#6366F1',
  experiment: '#38BDF8',
  result: '#34D399',
  limitation: '#F59E0B',
};

// 浏览器语音合成（zh-CN），失败/不可用时自动回落字幕（不报错）
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
    /* 默认回落字幕，不干预 */
  }
}

export function PresenterView({ presentation, accent }: { presentation: PresentationOut; accent: string }) {
  const scenes = presentation.scenes || [];
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [voiceOn, setVoiceOn] = useState(true);
  const scene: SceneOut | undefined = scenes[idx];

  useEffect(() => {
    if (!playing) return;
    const id = setTimeout(() => {
      if (idx + 1 < scenes.length) setIdx(idx + 1);
      else setPlaying(false);
    }, 4200);
    return () => clearTimeout(id);
  }, [playing, idx, scenes.length]);

  // 讲解语音：跟随场景切换（仅当说明开启且浏览器支持）
  useEffect(() => {
    const narr = scene?.narration || {};
    speak((narr.script as string) || (narr.subtitle as string), voiceOn);
    return () => { if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel(); };
  }, [idx, voiceOn, scene?.narration?.script]);

  const narr = scene?.narration || {};
  const color = KIND_TONE[scene?.kind || ''] || accent;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px,1fr]">
      {/* Scene list */}
      <div className="space-y-2">
        <Kicker className="mb-3">分镜 · STORYBOARD</Kicker>
        <div className="space-y-2">
          {scenes.map((s, i) => (
            <button
              key={i}
              onClick={() => { setIdx(i); setPlaying(false); }}
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
                <div className="truncate text-[11px] text-slate-500">{s.kind}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Stage */}
      <GlassCard className="flex flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-[var(--line)] px-5 py-3">
          <div className="flex items-center gap-2">
            <Kicker>AI 讲解员 · PRESENTER</Kicker>
          </div>
          <div className="flex items-center gap-1.5">
            <Btn variant="ghost" className="h-8 w-8 p-0" onClick={() => { setIdx(Math.max(0, idx - 1)); setPlaying(false); }}>
              <SkipBack className="h-4 w-4" />
            </Btn>
            <Btn variant="outline" className="h-8 px-3" onClick={() => setPlaying((p) => !p)}>
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              {playing ? '暂停' : idx + 1 < scenes.length ? '播放' : '重播'}
            </Btn>
            <Btn variant="ghost" className="h-8 w-8 p-0" onClick={() => { setIdx(Math.min(scenes.length - 1, idx + 1)); setPlaying(false); }}>
              <SkipForward className="h-4 w-4" />
            </Btn>
            <Btn variant="ghost" className="h-8 w-8 p-0" onClick={() => setVoiceOn((v) => !v)}>
              {voiceOn ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
            </Btn>
          </div>
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={idx}
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.35 }}
            className="flex flex-1 flex-col gap-5 p-5"
          >
            {/* Presenter */}
            <div className="flex items-center gap-5">
              <div className="relative grid h-20 w-20 place-items-center">
                <motion.div
                  className="absolute inset-0 rounded-full"
                  animate={{ boxShadow: [`0 0 0 0px ${color}33`, `0 0 0 26px transparent`] }}
                  transition={{ repeat: Infinity, duration: 2.2 }}
                />
                <div
                  className="grid h-16 w-16 place-items-center rounded-full text-xl font-bold text-white"
                  style={{ background: `linear-gradient(135deg, ${color}, ${color}88)` }}
                >
                  🅁
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-lg font-semibold text-white">{scene?.title}</span>
                  <span
                    className="rounded-full px-2 py-0.5 font-mono text-[10px] uppercase"
                    style={{ background: `${color}22`, color }}
                  >
                    {scene?.kind}
                  </span>
                </div>
                <p className="mt-1 text-sm text-slate-400">{scene?.summary}</p>
              </div>
            </div>

            {/* steps */}
            <div className="flex flex-wrap gap-2">
              {(scene?.steps || []).map((st, i) => (
                <motion.span
                  key={i}
                  whileHover={{ y: -2 }}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-3 py-1.5 text-[12px] text-slate-300"
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
                  {st}
                </motion.span>
              ))}
            </div>

            {/* narration + subtitle */}
            <div className="mt-auto space-y-3">
              <div className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-4">
                <div className="mb-1.5 flex items-center gap-2 text-[11px] text-slate-500">
                  <Volume2 className="h-3.5 w-3.5" /> 讲解词 · NARRATION
                </div>
                <p className="text-[15px] leading-relaxed text-slate-200">{narr.script}</p>
              </div>
              {narr.subtitle && (
                <div className="flex items-center justify-between gap-3 rounded-xl bg-black/30 px-4 py-2.5 font-mono text-[13px] text-slate-300">
                  <span className="truncate">{narr.subtitle}</span>
                  {narr.audio_url ? <span className="ml-3 shrink-0 text-[10px] text-emerald-400">● 音频</span> : null}
                </div>
              )}
            </div>
          </motion.div>
        </AnimatePresence>

        {/* scene progress */}
        <div className="flex items-center gap-1 px-5 pb-4">
          {scenes.map((s, i) => (
            <button
              key={i}
              onClick={() => { setIdx(i); setPlaying(false); }}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]"
            >
              <div
                className="h-full rounded-full transition-all"
                style={{ width: i === idx ? '100%' : i < idx ? '100%' : '0%', background: i <= idx ? color : 'transparent' }}
              />
            </button>
          ))}
        </div>
      </GlassCard>
    </div>
  );
}
