'use client';

// 证据问答视图（§5.7 / §5.13 / §6.16）。
//
// 优先走流式 POST /papers/{id}/qa/stream：先 citation 事件，再 verified_sentence，
// 最后唯一 final/error；UI 逐句渲染，每个经验证的句子可点击跳到证据（onNavigate）。
// 非流式 api.qa() 作为降级路径（SSE 不可用时），语义与结构保持一致（§551）。
// 无证据 → 拒答，不允许编造。

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Send, ShieldCheck, ShieldAlert, Quote, FileText, CornerDownLeft, ChevronDown, Loader2, Info, SearchX, MessageCircle } from 'lucide-react';
import { api } from '@/lib/api';
import type { AskResponse, EvidenceOut, PaperDetail } from '@/lib/types';
import type {
  EvidenceRecord, NavigationTarget, QACitation, QAFinal, QAMeta, QASentence, QAStatus, Scope,
} from '@/lib/contracts';
import { useQAStream } from '@/hooks/useQAStream';
import { Badge, Btn, GlassCard, Kicker, Spinner } from '@/components/ui';
import { RichText } from '@/components/RichText';
import { MathText } from '@/components/MathText';
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
  /** 流式：逐句经验证陈述（可点击定位） */
  sentences?: { text: string; evidenceIds: string[] }[];
  /** 流式：命中的证据 */
  citations?: EvidenceRecord[];
  /** 是否来自流式 */
  streamed?: boolean;
}

export function QAView({ scope, accent, detail, onNavigate, messages, onMessagesChange }: {
  scope: Scope | null;
  accent: string;
  detail?: PaperDetail;
  onNavigate?: (t: NavigationTarget) => void;
  messages?: Msg[];
  onMessagesChange?: (m: Msg[]) => void;
}) {
  const [localMessages, setLocalMessages] = useState<Msg[]>([]);
  const isControlled = !!messages;
  const msgs = isControlled ? messages! : localMessages;
  const setMsgs = isControlled ? (m: Msg[]) => onMessagesChange?.(m) : setLocalMessages;
  const [input, setInput] = useState('');
  const [fallbackLoading, setFallbackLoading] = useState(false);
  const [media, setMedia] = useState<MediaItem | null>(null);
  const [openEv, setOpenEv] = useState<Record<string, boolean>>({});

  // 流式状态
  const [streamQuestion, setStreamQuestion] = useState<string>('');
  const stream = useQAStream({
    scope: scope ?? { paper_id: 0, revision_id: '' },
    request: { question: '', top_k: 5 },
  });
  const streamDoneRef = useRef(false);

  const askFallback = useCallback(
    async (q: string) => {
      if (!scope) return;
      setFallbackLoading(true);
      try {
        const r = await api.qa(scope.paper_id, q);
        setMsgs([...msgs, { role: 'user', text: q }, { role: 'assistant', text: r.answer, resp: r }]);
      } catch {
        setMsgs([
          ...msgs,
          { role: 'user', text: q },
          {
            role: 'assistant',
            text: '出错了，请稍后再试。',
            resp: { answer: '', grounded: false, confidence: 'Low', evidence: [], note: '问答服务不可用' },
          },
        ]);
      } finally {
        setFallbackLoading(false);
      }
    },
    [scope, msgs, setMsgs],
  );

  // 流式结束时把结果落成一条消息（含逐句 + 引用）
  useEffect(() => {
    if (!streamQuestion) return;
    const finalEv = stream.events.find((e) => e.type === 'final');
    if (stream.state === 'completed' && finalEv && !streamDoneRef.current) {
      streamDoneRef.current = true;
      const f = finalEv.data as QAFinal;
      const sentences = stream.events
        .filter((e) => e.type === 'sentence')
        .map((e) => {
          const s = e.data as QASentence;
          return { text: s.statement.text, evidenceIds: s.statement.evidence_ids };
        });
      const citations = stream.events
        .filter((e) => e.type === 'citation')
        .map((e) => (e.data as QACitation).evidence);
      const legacy: AskResponse = {
        answer: f.answer.text?.text ?? '',
        grounded: f.answer.grounded,
        confidence: f.answer.confidence,
        evidence: citations.map((c) => ({
          page: c.source_page,
          region: c.source_region?.[0]?.page_label ?? c.anchor_id,
          region_type: 'anchor',
          text: c.source_text,
          quote: c.source_text,
          confidence: c.confidence ?? 0,
        })),
        note: f.answer.note,
        // **mode 必须透传**：前端靠它区分"通用回答"与"拒答"（ADR-0069）。
        // 此前 SSE 路径漏了这个字段 → 通用回答也按"拒答"样式渲染。
        mode: (f.answer as unknown as { mode?: string }).mode,
      };
      setMsgs([
        ...msgs,
        { role: 'user', text: streamQuestion },
        { role: 'assistant', text: legacy.answer, resp: legacy, sentences, citations, streamed: true },
      ]);
      setStreamQuestion('');
    }
    if (stream.state === 'failed' && !streamDoneRef.current) {
      streamDoneRef.current = true;
      // 失败也要**先按 answer_id 取回**（服务端在发 final 前就落库了，连接断了不代表答案没了），
      // 取不回再降级到非流式 POST /qa —— 最后才提示可重试。
      const meta = stream.events.find((e) => e.type === 'meta');
      const failedAnswerId = (meta?.data as QAMeta | undefined)?.answer_id;
      const q = streamQuestion;
      if (failedAnswerId && scope) {
        setStreamQuestion('');
        void api
          .qaAnswer(scope.paper_id, failedAnswerId)
          .then((r) => {
            if (r.status === 'completed' && r.legacy) {
              setMsgs([
                ...msgs,
                { role: 'user', text: q },
                {
                  role: 'assistant',
                  text: r.legacy.answer,
                  resp: { ...r.legacy, note: '连接中断，已从服务端取回完整结果。' },
                  streamed: true,
                },
              ]);
              return;
            }
            void askFallback(q);
          })
          .catch(() => void askFallback(q));
        return;
      }
      setStreamQuestion('');
      void askFallback(q);
    }
    // **流结束却没有 final**（ADR-0069 / REFACTOR_PLAN M6）：
    // 以前这里什么都不做 → 用户看到"转圈转了一会儿就没反应"。
    // 现在分两步：① 若已拿到 meta.answer_id，就按它去后端**取回已落库的结果**
    // （服务端在发 final 之前就持久化了，网络断了不代表答案没了）；② 取不回来才退回
    // "已生成的部分 + 可重试"提示，绝不静默。
    if (stream.state === 'completed' && !finalEv && !streamDoneRef.current) {
      streamDoneRef.current = true;
      const meta = stream.events.find((e) => e.type === 'meta');
      const answerId = (meta?.data as QAMeta | undefined)?.answer_id;
      const sentences = stream.events
        .filter((e) => e.type === 'sentence')
        .map((e) => {
          const s = e.data as QASentence;
          return { text: s.statement.text, evidenceIds: s.statement.evidence_ids };
        });
      const citations = stream.events
        .filter((e) => e.type === 'citation')
        .map((e) => (e.data as QACitation).evidence);
      const partial = sentences.map((s) => s.text).join(' ').trim();

      const finish = (resp: AskResponse, note: string) => {
        setMsgs([
          ...msgs,
          { role: 'user', text: streamQuestion },
          { role: 'assistant', text: resp.answer, resp: { ...resp, note, mode: resp.mode ?? 'cached' },
            sentences, citations, streamed: true },
        ]);
        setStreamQuestion('');
      };

      if (answerId && scope) {
        void api
          .qaAnswer(scope.paper_id, answerId)
          .then((r) => {
            if (r.status === 'completed' && r.legacy) {
              finish(r.legacy, '连接中断，已从服务端取回完整结果。');
              return;
            }
            fallbackPartial();
          })
          .catch(() => fallbackPartial());
        return;
      }
      fallbackPartial();

      function fallbackPartial() {
        setMsgs([
          ...msgs,
          { role: 'user', text: streamQuestion },
          {
            role: 'assistant',
            text: partial,
            resp: {
              answer: partial,
              grounded: false,
              confidence: 'Low',
              evidence: citations.map((c) => ({
                page: c.source_page,
                region: c.source_region?.[0]?.page_label ?? c.anchor_id,
                region_type: 'anchor',
                text: c.source_text,
                quote: c.source_text,
                confidence: c.confidence ?? 0,
              })),
              note: partial
                ? '这次连接中断了（未收到完整结果），以上是已生成的部分；已为你保留。'
                : '这次没能拿到完整结果，已保留你的问题，可以点「重试」再问一次。',
              mode: 'interrupted',
            },
            sentences,
            citations,
            streamed: true,
          },
        ]);
        setStreamQuestion('');
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.state, stream.events, streamQuestion]);

  const streaming = streamQuestion !== '' &&
    (stream.state === 'connecting' || stream.state === 'streaming');
  const loading = streaming || fallbackLoading;

  const ask = (q: string) => {
    if (!q.trim() || loading) return;
    setInput('');
    if (!scope) {
      void askFallback(q);
      return;
    }
    streamDoneRef.current = false;
    setStreamQuestion(q);
    stream.start({ question: q, top_k: 5, revision_id: scope.revision_id });
  };

  // 流式进行中的临时消息
  const liveSentences = stream.events
    .filter((e) => e.type === 'sentence')
    .map((e) => (e.data as QASentence).statement);
  const liveStatus = stream.events.filter((e) => e.type === 'status').map((e) => (e.data as QAStatus).message);

  const toggleEv = (key: string) => setOpenEv((s) => ({ ...s, [key]: !s[key] }));

  /** 逐句渲染：经验证的句子可点击跳到证据 */
  const renderSentences = (m: Msg) => {
    if (!m.sentences || m.sentences.length === 0) return null;
    return (
      <div className="space-y-1.5">
        {m.sentences.map((s, i) => {
          const canJump = !!onNavigate && m.citations && m.citations.length > 0;
          const target = m.citations?.find((c) => s.evidenceIds.includes(c.id)) ?? m.citations?.[0];
          return (
            <button
              key={i}
              disabled={!canJump || !target}
              onClick={() => target && onNavigate?.({
                paper_id: target.paper_id,
                revision_id: target.revision_id,
                anchor_id: target.anchor_id,
                segment_index: 0,
              })}
              className={cn(
                'block w-full rounded-lg px-2.5 py-1.5 text-left text-[13px] leading-relaxed transition',
                canJump && target
                  ? 'text-slate-200 hover:bg-indigo-500/10 hover:text-white'
                  : 'text-slate-400',
              )}
            >
              <span className={cn('mr-1.5 align-middle text-[10px]', target ? 'text-emerald-400' : 'text-slate-600')}>●</span>
              {s.text}
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center gap-3">
        <Kicker>证据驱动的问答 · GROUNDED Q&amp;A</Kicker>
        <div className="ml-auto flex items-center gap-3">
          {PRESETS.map((q) => (
            <button
              key={q}
              onClick={() => ask(q)}
              className="rounded-full border border-[var(--line)] bg-white/[0.03] px-3 py-1.5 text-[11px] text-slate-300 transition hover:bg-white/[0.07]"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      <GlassCard className="flex min-h-[480px] flex-col">
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {msgs.length === 0 && !loading && (
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
                    {m.resp?.mode === 'not_mentioned' ? (
                      <Badge tone="slate"><SearchX className="h-3 w-3" /> 论文未提及</Badge>
                    ) : m.resp?.mode === 'general' ? (
                      <Badge tone="cyan"><MessageCircle className="h-3 w-3" /> 通用回答 · 未用论文证据</Badge>
                    ) : m.resp?.mode === 'interrupted' ? (
                      <Badge tone="amber"><ShieldAlert className="h-3 w-3" /> 回答被中断</Badge>
                    ) : m.resp?.grounded ? (
                      <Badge tone="emerald"><ShieldCheck className="h-3 w-3" /> 有据可依</Badge>
                    ) : (
                      <Badge tone="amber"><ShieldAlert className="h-3 w-3" /> 无证据支持</Badge>
                    )}
                    {m.streamed && <span className="font-mono text-[10px] text-slate-600">流式</span>}
                    {m.resp && <span className="font-mono text-[10px] text-slate-500">置信度 · {m.resp.confidence}</span>}
                  </div>
                  <div className="max-w-full rounded-2xl rounded-bl-md border border-[var(--line)] bg-white/[0.03] px-4 py-3">
                    {m.sentences && m.sentences.length > 0
                      ? renderSentences(m)
                      : m.text
                        ? <RichText text={m.text} figures={detail?.figures} tables={detail?.tables} onOpenMedia={setMedia} />
                        : null}
                  </div>

                  {/* 证据卡片（可点击定位到论文原文，可展开） */}
                  {m.resp && m.resp.evidence.length > 0 && (
                    <div className="mt-2 space-y-1.5">
                      <div className="flex items-center gap-1.5 font-mono text-[10px] text-slate-500">
                        <Quote className="h-3 w-3" /> 引用证据 · 点击定位到论文
                      </div>
                      {m.resp.evidence.map((e, j) => {
                        const key = `${i}-${j}`;
                        const open = openEv[key];
                        return (
                          <button
                            key={key}
                            onClick={() => {
                              const c = m.citations?.[j];
                              if (onNavigate && c) {
                                onNavigate({
                                  paper_id: c.paper_id,
                                  revision_id: c.revision_id,
                                  anchor_id: c.anchor_id,
                                  segment_index: 0,
                                });
                              }
                            }}
                            className="group flex w-full items-start gap-2 rounded-lg bg-white/[0.02] px-3 py-2 text-left text-[12px] text-slate-400 transition hover:bg-white/[0.05]"
                          >
                            <Quote className="mt-0.5 h-3 w-3 shrink-0 text-slate-600" />
                            <div className="min-w-0 flex-1">
                              <span className="font-mono text-[10px] text-slate-500">
                                PDF 第 {e.page} 页{e.region ? ` · ${e.region}` : ''}
                              </span>
                              {open || !e.text ? (
                                <MathText text={e.text || e.quote} className="mt-0.5 block text-slate-300" />
                              ) : (
                                <MathText text={e.text || e.quote} className="mt-0.5 line-clamp-2 block" />
                              )}
                            </div>
                            <ChevronDown
                              className={cn('mt-0.5 h-3 w-3 shrink-0 text-slate-600 transition-transform group-hover:text-indigo-300', open && 'rotate-180')}
                              onClick={(ev) => { ev.stopPropagation(); toggleEv(key); }}
                            />
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {m.resp && !m.resp.grounded && (
                    <div className="mt-2 text-[11px] text-amber-400/80">{m.resp.note || '检索到的证据不足以支撑回答，已拒答。'}</div>
                  )}
                  {m.resp && m.resp.mode === 'general' && (
                    <div className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-sky-500/25 bg-sky-500/10 px-2 py-1 text-[10px] text-sky-200/90">
                      <Info className="h-3 w-3" /> 通用回答（非论文内容，未使用原文证据）
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          ))}

          {/* 流式进行中：先 citation，再逐句 */}
          {streaming && (
            <div className="w-full">
              <div className="mb-1.5 flex items-center gap-2 text-[11px] text-slate-400">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {liveStatus[liveStatus.length - 1] || '正在检索并逐句校验…'}
              </div>
              <div className="rounded-2xl rounded-bl-md border border-[var(--line)] bg-white/[0.03] px-4 py-3">
                {liveSentences.length > 0 ? (
                  <div className="space-y-1.5">
                    {liveSentences.map((s, i) => (
                      <MathText key={i} text={s.text} className="block text-[13px] leading-relaxed text-slate-200" />
                    ))}
                  </div>
                ) : (
                  <p className="text-[13px] text-slate-500">等待首个已验证句子…</p>
                )}
              </div>
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
            回车发送 · 流式逐句校验 · 点句子/证据可定位到原文，点「图/表N」可查看
          </div>
        </div>
      </GlassCard>

      <MediaModal item={media} accent={accent} onClose={() => setMedia(null)} />
    </div>
  );
}
