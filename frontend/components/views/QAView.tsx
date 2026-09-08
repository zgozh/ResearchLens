'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { Send, ShieldCheck, ShieldAlert, Quote, FileText, CornerDownLeft, ChevronDown } from 'lucide-react';
import { api } from '@/lib/api';
import type { AskResponse, EvidenceOut, PaperDetail } from '@/lib/types';
import { Badge, Btn, GlassCard, Kicker, Spinner } from '@/components/ui';
import { RichText } from '@/components/RichText';
import { MediaModal, type MediaItem } from '@/components/MediaModal';
import { cn } from '@/lib/cn';

const PRESETS = [
  '这篇论文哪里最值得质疑？',
  '这篇论文的主要贡献是什么？',
  '论文用了什么数据集？',
];

interface Msg {
  role: 'user' | 'assistant';
  text: string;
  resp?: AskResponse;
}

export function QAView({ paperId, accent, detail, onJump, messages, onMessagesChange }: {
  paperId: number; accent: string; detail?: PaperDetail;
  onJump?: (page: number, region: string, quote: string) => void;
  messages?: Msg[]; onMessagesChange?: (m: Msg[]) => void;
}) {
  const [localMessages, setLocalMessages] = useState<Msg[]>([]);
  const isControlled = !!messages;
  const msgs = isControlled ? messages! : localMessages;
  const setMsgs = isControlled ? (m: Msg[]) => onMessagesChange?.(m) : setLocalMessages;
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [media, setMedia] = useState<MediaItem | null>(null);
  const [openEv, setOpenEv] = useState<Record<number, boolean>>({});

  const ask = async (q: string) => {
    if (!q.trim() || loading) return;
    setMsgs([...msgs, { role: 'user', text: q }]);
    setInput('');
    setLoading(true);
    try {
      const r = await api.qa(paperId, q);
      setMsgs([...msgs, { role: 'user', text: q }, { role: 'assistant', text: r.answer, resp: r }]);
    } catch (e) {
      setMsgs([
        ...msgs,
        { role: 'user', text: q },
        { role: 'assistant', text: '出错了，请稍后再试。', resp: { answer: '', grounded: false, confidence: 'Low', evidence: [], note: '' } },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const openPreset = (q: string) => ask(q);
  const toggleEv = (i: number) => setOpenEv((s) => ({ ...s, [i]: !s[i] }));

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-3">
        <Kicker>证据驱动的问答 · GROUNDED Q&amp;A</Kicker>
        <div className="ml-auto flex items-center gap-3">
          {PRESETS.map((q) => (
            <button
              key={q}
              onClick={() => openPreset(q)}
              className="rounded-full border border-[var(--line)] bg-white/[0.03] px-3 py-1.5 text-[11px] text-slate-300 transition hover:bg-white/[0.07]"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      <GlassCard className="flex min-h-[480px] flex-col">
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {msgs.length === 0 && (
            <div className="grid h-full place-items-center text-center">
              <div>
                <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl" style={{ background: `${accent}1c` }}>
                  <FileText className="h-6 w-6" style={{ color: accent }} />
                </div>
                <p className="text-sm text-slate-400">向论文提问，回答将绑定证据与置信度。</p>
                <p className="mt-1 font-mono text-[11px] text-slate-600">无证据 → 拒绝编造</p>
              </div>
            </div>
          )}

          {msgs.map((m, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex">
              {m.role === 'user' ? (
                <div className="ml-auto max-w-[75%] rounded-2xl rounded-br-md bg-indigo-500 px-4 py-2.5 text-sm text-white">
                  {m.text}
                </div>
              ) : (
                <div className="w-full">
                  <div className="mb-1.5 flex items-center gap-2">
                    {m.resp?.grounded ? (
                      <Badge tone="emerald"><ShieldCheck className="h-3 w-3" /> 有据可依</Badge>
                    ) : (
                      <Badge tone="amber"><ShieldAlert className="h-3 w-3" /> 无证据支持</Badge>
                    )}
                    {m.resp && <span className="font-mono text-[10px] text-slate-500">置信度 · {m.resp.confidence}</span>}
                  </div>
                  <div className="max-w-full rounded-2xl rounded-bl-md border border-[var(--line)] bg-white/[0.03] px-4 py-3">
                    {m.text ? (
                      <RichText
                        text={m.text}
                        figures={detail?.figures}
                        tables={detail?.tables}
                        onOpenMedia={setMedia}
                      />
                    ) : null}
                  </div>

                  {/* 证据卡片（可点击定位到论文原文，可展开） */}
                  {m.resp && m.resp.evidence.length > 0 && (
                    <div className="mt-2 space-y-1.5">
                      <div className="flex items-center gap-1.5 font-mono text-[10px] text-slate-500">
                        <Quote className="h-3 w-3" /> 引用证据 · 点击定位到论文
                      </div>
                      {m.resp.evidence.map((e, j) => {
                        const open = openEv[j];
                        return (
                          <button
                            key={j}
                            onClick={() => {
                              if (onJump && (e.text || e.quote)) onJump(e.page, e.region, e.quote || e.text);
                            }}
                            className="group flex w-full items-start gap-2 rounded-lg bg-white/[0.02] px-3 py-2 text-left text-[12px] text-slate-400 transition hover:bg-white/[0.05]"
                          >
                            <Quote className="mt-0.5 h-3 w-3 shrink-0 text-slate-600" />
                            <div className="min-w-0 flex-1">
                              <span className="font-mono text-[10px] text-slate-500">
                                p.{e.page} · {e.region}
                              </span>
                              {open || !e.text ? (
                                <div className="mt-0.5 text-slate-300">{e.text || e.quote}</div>
                              ) : (
                                <div className="mt-0.5 line-clamp-2">{e.text || e.quote}</div>
                              )}
                            </div>
                            <ChevronDown
                              className={cn('mt-0.5 h-3 w-3 shrink-0 text-slate-600 transition-transform group-hover:text-indigo-300', open && 'rotate-180')}
                              onClick={(ev) => { ev.stopPropagation(); toggleEv(j); }}
                            />
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {m.resp && !m.resp.grounded && (
                    <div className="mt-2 text-[11px] text-amber-400/80">{m.resp.note}</div>
                  )}
                </div>
              )}
            </motion.div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <Spinner /> 检索证据中…
            </div>
          )}
        </div>

        <div className="border-t border-[var(--line)] p-3">
          <form
            onSubmit={(e) => { e.preventDefault(); ask(input); }}
            className="flex items-center gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入一个问题，例如：这篇论文哪里最值得质疑？"
              className="flex-1 rounded-xl border border-[var(--line)] bg-white/[0.03] px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:border-white/25"
            />
            <Btn type="submit" variant="primary" className="px-3">
              <Send className="h-4 w-4" />
            </Btn>
          </form>
          <div className="mt-2 flex items-center gap-1.5 font-mono text-[10px] text-slate-600">
            <CornerDownLeft className="h-3 w-3" />
            回车发送 · 回答带证据与置信度 · 点证据可定位到原文，点「图/表N」可查看
          </div>
        </div>
      </GlassCard>

      <MediaModal item={media} accent={accent} onClose={() => setMedia(null)} />
    </div>
  );
}
