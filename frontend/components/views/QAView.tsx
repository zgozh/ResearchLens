'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { Send, ShieldCheck, ShieldAlert, Quote, FileText, CornerDownLeft } from 'lucide-react';
import { api } from '@/lib/api';
import type { AskResponse, EvidenceOut } from '@/lib/types';
import { Badge, Btn, GlassCard, Kicker, Spinner } from '@/components/ui';

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

export function QAView({ paperId, accent }: { paperId: number; accent: string }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  const ask = async (q: string) => {
    if (!q.trim() || loading) return;
    setMessages((m) => [...m, { role: 'user', text: q }]);
    setInput('');
    setLoading(true);
    try {
      const r = await api.qa(paperId, q);
      setMessages((m) => [...m, { role: 'assistant', text: r.answer, resp: r }]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: 'assistant', text: '出错了，请稍后再试。', resp: { answer: '', grounded: false, confidence: 'Low', evidence: [], note: '' } },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const openPreset = (q: string) => ask(q);

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-3">
        <Kicker>GROUNDED Q&A · 证据驱动的问答</Kicker>
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

      <GlassCard className="flex min-h-[360px] flex-col">
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {messages.length === 0 && (
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

          {messages.map((m, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex">
              {m.role === 'user' ? (
                <div className="ml-auto max-w-[75%] rounded-2xl rounded-br-md bg-indigo-500 px-4 py-2.5 text-sm text-white">
                  {m.text}
                </div>
              ) : (
                <div className="w-full">
                  <div className="mb-1.5 flex items-center gap-2">
                    {m.resp?.grounded ? (
                      <Badge tone="emerald"><ShieldCheck className="h-3 w-3" /> grounded</Badge>
                    ) : (
                      <Badge tone="amber"><ShieldAlert className="h-3 w-3" /> no evidence</Badge>
                    )}
                    {m.resp && <span className="font-mono text-[10px] text-slate-500">confidence: {m.resp.confidence}</span>}
                  </div>
                  <div className="max-w-full rounded-2xl rounded-bl-md border border-[var(--line)] bg-white/[0.03] px-4 py-3 text-sm leading-relaxed text-slate-200">
                    {m.text}
                  </div>
                  {m.resp && m.resp.evidence.length > 0 && (
                    <div className="mt-2 space-y-1.5">
                      {m.resp.evidence.map((e, j) => (
                        <div key={j} className="flex items-start gap-2 rounded-lg bg-white/[0.02] px-3 py-2 text-[12px] text-slate-400">
                          <Quote className="mt-0.5 h-3 w-3 shrink-0 text-slate-600" />
                          <div>
                            <span className="font-mono text-[10px] text-slate-500">
                              p.{e.page} · {e.region}
                            </span>
                            <div className="mt-0.5 line-clamp-2">{e.text || e.quote}</div>
                          </div>
                        </div>
                      ))}
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
            Enter 发送 · 回答带 Evidence + Confidence
          </div>
        </div>
      </GlassCard>
    </div>
  );
}
