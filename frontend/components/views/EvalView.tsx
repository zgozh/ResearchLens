'use client';

// D29 重写：此前的实现整体读的是**已废弃的 legacy 指标名**
// （citation_coverage / claim_evidence_alignment / unsupported_claim_rate /
// structure_accuracy / visual_consistency / answer_grounding / audience / author /
// num_claims …），而 `/api/papers/{id}/evaluation` 返回的是 canonical 指标集
// （source_asset_coverage / support_precision / quote_exact_rate … +
// overall_score_available + not_evaluated）。
//
// 两个后果，正是用户看到的"自动评测完全没数据"：
// 1. 所有值都取不到 → 一律显示 0.0%；
// 2. 更糟的是 `Number(undefined ?? 0) === 0` 让 `unsupported === 0` 为真，
//    于是界面**把"没有数据"渲染成"已通过 Evidence Gate，所有断言均有证据"** ——
//    一个纯属虚构的绿色通过。
//
// 现在：优先读 `/exhibits` 里持久化的真实 report；缺失的指标如实显示"未评测"，
// 绝不用 0 冒充，也绝不把"没数据"当成"通过"。

import { motion } from 'framer-motion';
import { Gauge, ShieldAlert, CheckCircle2, ListChecks, Info } from 'lucide-react';
import type { EvaluationReport } from '@/lib/contracts';
import type { ClaimSummary, EvaluationOut } from '@/lib/types';
import { Badge, GlassCard, Kicker, Meter } from '@/components/ui';

/** canonical 比率型指标（值域 0–1，展示为百分比）。 */
const RATIO_METRICS: { key: string; label: string; color: string; hint?: string }[] = [
  { key: 'source_asset_coverage', label: '原件资产覆盖率', color: '#22D3EE', hint: '断言引用的图/表有多少能落到真实资产' },
  { key: 'anchor_page_accuracy', label: '锚点页准确率', color: '#6366F1' },
  { key: 'anchor_region_hit_rate', label: '锚点区域命中率', color: '#38BDF8' },
  { key: 'quote_exact_rate', label: '引文精确率', color: '#34D399' },
  { key: 'support_precision', label: '证据支撑精确率', color: '#A78BFA' },
  { key: 'support_recall', label: '证据支撑召回率', color: '#8B5CF6', hint: '需要 Golden Set 真值' },
  { key: 'unsupported_fact_escape_rate', label: '无支撑事实逃逸率（目标 ≈ 0）', color: '#F43F5E' },
  { key: 'unanswerable_refusal_rate', label: '不可答问题拒答率', color: '#F59E0B' },
  { key: 'answerable_false_refusal_rate', label: '可答问题误拒率', color: '#FB923C' },
  { key: 'recovery_success_rate', label: '失败恢复成功率', color: '#64748B' },
];

/** 运行型指标（不是百分比，单独展示）。 */
const RUNTIME_METRICS: { key: string; label: string; unit?: string }[] = [
  { key: 'ingest_ms', label: '解析入库耗时', unit: 'ms' },
  { key: 'qa_first_verified_ms', label: '问答首条已验证耗时', unit: 'ms' },
  { key: 'qa_total_ms', label: '问答总耗时', unit: 'ms' },
  { key: 'input_tokens', label: '输入 tokens' },
  { key: 'output_tokens', label: '输出 tokens' },
];

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function EvalView({
  evalData, accent, report, claims,
}: {
  evalData: EvaluationOut;
  accent: string;
  /** `/exhibits` 里**持久化**的评测报告（优先；它带着真实算出的指标）。 */
  report?: EvaluationReport | null;
  /** 用于逐断言汇总（避免再显示 undefined 计数）。 */
  claims?: ClaimSummary[];
}) {
  // 指标来源优先级：持久化 report > legacy EvaluationOut.metrics
  const metrics: Record<string, unknown> = (() => {
    const out: Record<string, unknown> = {};
    for (const entry of report?.metrics ?? []) out[entry.name] = entry.value;
    for (const [k, v] of Object.entries(evalData.metrics || {})) {
      if (out[k] === undefined || out[k] === null) out[k] = v;
    }
    return out;
  })();

  const notEvaluated = Array.isArray(metrics.not_evaluated)
    ? (metrics.not_evaluated as unknown[]).map(String)
    : [];
  // proxy 指标：值算出来了、但口径是"间接测量"，必须**标着 proxy 显示**而不是当未评测藏起来。
  const proxyNames = Array.isArray(metrics.proxy)
    ? (metrics.proxy as unknown[]).map(String)
    : [];
  const isProxy = (name: string) => proxyNames.includes(name);
  const scoreValue = toNumber(report?.overall_score) ?? toNumber(evalData.overall_score);
  // 「可用」必须由后端显式声明，且分数确实是数字；否则一律按未评测处理。
  const scoreAvailable = metrics.overall_score_available !== false && scoreValue !== null;
  // **AI 口径**综合分（ADR-0056）：人工真值缺失时由 LLM 语义裁判给出，标着口径显示，
  // 绝不与人工真值口径混为一谈。展示优先级：人工真值 > AI 裁判 > 未评测。
  const aiScoreValue = toNumber(metrics.ai_overall_score);
  const aiScoreAvailable =
    !scoreAvailable && metrics.ai_overall_score_available !== false && aiScoreValue !== null;
  const shownScore = scoreAvailable ? scoreValue : aiScoreAvailable ? aiScoreValue : null;
  const scoreBasis = scoreAvailable ? 'human' : aiScoreAvailable ? 'ai' : null;

  const claimCount = claims?.length ?? 0;
  const supportedCount = claims?.filter((c) => c.status === 'SUPPORTED').length ?? 0;
  const unsupportedCount = claimCount - supportedCount;
  const unsupportedRate = toNumber(metrics.unsupported_fact_escape_rate);
  // **只有真的算出来过**才允许说"通过"；null 必须显示"未评测"。
  const gatePassed = unsupportedRate !== null && unsupportedRate === 0;
  // 金标集来源：机器构造的集合**不是人工真值**（规格 §5.9），不能让它给自己打分。
  const goldenTuning = (report?.warnings ?? []).some(
    (w) => w.code === 'golden_not_annotated',
  );

  return (
    <div className="space-y-6">
      {/* 总评 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[300px,1fr]">
        <GlassCard className="flex flex-col items-center justify-center p-6 text-center">
          <Kicker className="mb-3">
            综合评分 · SCORE{scoreBasis === 'ai' ? '（AI 评测）' : ''}
          </Kicker>
          {shownScore !== null ? (
            <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
              className="relative grid h-40 w-40 place-items-center">
              <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
                <circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
                <motion.circle cx="60" cy="60" r="52" fill="none" stroke={accent} strokeWidth="10" strokeLinecap="round"
                  strokeDasharray={`${(Math.max(0, Math.min(100, shownScore)) / 100) * 326.7} 326.7`}
                  initial={{ strokeDasharray: '0 326.7' }}
                  animate={{ strokeDasharray: `${(Math.max(0, Math.min(100, shownScore)) / 100) * 326.7} 326.7` }}
                  transition={{ duration: 1.1, ease: 'easeOut' }} />
              </svg>
              <div className="absolute inset-0 grid place-items-center">
                <div>
                  <div className="text-4xl font-bold text-white">{Math.round(shownScore)}</div>
                  <div className="font-mono text-[10px] uppercase text-slate-500">/ 100</div>
                </div>
              </div>
            </motion.div>
          ) : (
            <div className="grid h-40 w-40 place-items-center rounded-full border border-dashed border-white/15">
              <div>
                <div className="text-2xl font-bold text-slate-400">未评测</div>
                <div className="mt-1 font-mono text-[10px] uppercase text-slate-600">NOT EVALUATED</div>
              </div>
            </div>
          )}
          <div className="mt-4 flex items-center gap-1.5 text-[11px] text-slate-500">
            <Gauge className="h-3.5 w-3.5" /> 自动质量评测
          </div>
          {scoreBasis === 'ai' && (
            <p className="mt-2 text-[10px] leading-relaxed text-amber-300/70">
              AI 口径：support_precision/recall 由 **LLM 语义裁判**按语义判等给出（proxy），
              金标集未经人工确认 → 不是人工真值分。
            </p>
          )}
        </GlassCard>

        <GlassCard className="p-6">
          <Kicker className="mb-4">核心指标 · HEADLINE</Kicker>
          {scoreAvailable ? null : (
            <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-[12px] text-amber-200">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {scoreAvailable ? null : aiScoreAvailable ? (
                  <>
                    上面是 **AI 评测口径**的分数：金标集是机器从原文构造的草案（未人工确认），
                    所以 support_precision/recall 标为 proxy、由 LLM 语义裁判判等给出。
                    人工真值口径的综合评分仍不出（避免"让模型给自己出卷子"）。
                  </>
                ) : goldenTuning ? (
                  '综合评分尚未产出：金标集是**机器从原文自动构造的草案**，未经过人工确认，'
                  + '因此不当作真值（避免"让模型给自己出卷子"）；AI 裁判本次也未给出结论。'
                ) : (
                  '本篇尚未产出可用的综合评分：核心指标缺真值（需要 Golden Set 与已跑通的问答轨迹）。'
                )}
                界面**不以 0 分冒充通过**，缺失项一律标注"未评测"。
              </span>
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-4">
              <div className="text-2xl font-bold text-emerald-400">{claimCount}</div>
              <div className="mt-1 text-[11px] text-slate-500">已抽取断言</div>
            </div>
            <div className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-4">
              <div className={unsupportedCount === 0 ? 'text-2xl font-bold text-emerald-400' : 'text-2xl font-bold text-amber-400'}>
                {unsupportedCount}
              </div>
              <div className="mt-1 text-[11px] text-slate-500">未通过证据校验（共 {supportedCount} 条已验证）</div>
            </div>
          </div>
          {claimCount > 0 && (
            <div className="mt-5 flex items-center justify-between border-t border-[var(--line)] pt-4 text-[12px] text-slate-400">
              <span className="inline-flex items-center gap-2">
                <ListChecks className="h-4 w-4 text-slate-500" />
                已落地 {supportedCount}/{claimCount} 条断言
              </span>
              {gatePassed ? (
                <span className="inline-flex items-center gap-1.5 text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" /> 无支撑逃逸率为 0
                </span>
              ) : unsupportedRate !== null ? (
                <span className="inline-flex items-center gap-1.5 text-amber-400">
                  <ShieldAlert className="h-4 w-4" /> 无支撑逃逸率 {(unsupportedRate * 100).toFixed(1)}%
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-slate-500">
                  <Info className="h-4 w-4" /> 无支撑逃逸率未评测
                </span>
              )}
            </div>
          )}
        </GlassCard>
      </div>

      {/* 指标明细 */}
      <GlassCard className="p-6">
        <div className="mb-4 flex items-center gap-2">
          <Kicker>评测指标 · METRICS</Kicker>
          {goldenTuning ? (
            <Badge tone="amber">金标集待人工确认</Badge>
          ) : report?.golden_id ? (
            <Badge tone="emerald">Golden Set 已确认</Badge>
          ) : (
            <Badge tone="amber">缺少 Golden Set</Badge>
          )}
          {report?.version && (
            <span className="font-mono text-[10px] text-slate-500">{report.version}</span>
          )}
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {RATIO_METRICS.map((meta) => {
            const value = toNumber(metrics[meta.key]);
            if (value === null) {
              return (
                <div key={meta.key}>
                  <div className="flex items-center justify-between text-[12px]">
                    <span className="text-slate-400">{meta.label}</span>
                    <span className="font-mono text-[11px] text-slate-600">未评测</span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-white/[0.05]" />
                  {meta.hint && <p className="mt-1 text-[10px] text-slate-600">{meta.hint}</p>}
                </div>
              );
            }
            return (
              <div key={meta.key}>
                <Meter value={value * 100} label={meta.label} color={meta.color} />
                {isProxy(meta.key) ? (
                  <p className="mt-1 text-[10px] text-amber-300/70">
                    proxy：间接口径（规格允许报告但必须标明），非人工真值
                  </p>
                ) : (
                  meta.hint && <p className="mt-1 text-[10px] text-slate-600">{meta.hint}</p>
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-6 border-t border-[var(--line)] pt-4">
          <div className="mb-3 font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">运行指标 · RUNTIME</div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {RUNTIME_METRICS.map((meta) => {
              const value = toNumber(metrics[meta.key]);
              return (
                <div key={meta.key} className="rounded-lg border border-[var(--line)] bg-white/[0.02] px-3 py-2">
                  <div className="font-mono text-[13px] text-slate-200">
                    {value === null ? '—' : value.toLocaleString()}
                    {value !== null && meta.unit ? <span className="ml-1 text-[10px] text-slate-500">{meta.unit}</span> : null}
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-500">{meta.label}</div>
                </div>
              );
            })}
          </div>
        </div>

        {notEvaluated.length > 0 && (
          <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.02] p-3.5">
            <div className="mb-2 flex items-center gap-2 text-[11px] text-slate-400">
              <Info className="h-3.5 w-3.5" />
              未评测指标（{notEvaluated.length} 项）——不是 0 分，是**尚无真值**：
            </div>
            <div className="flex flex-wrap gap-1.5">
              {notEvaluated.map((name) => (
                <span key={name} className="rounded-md bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
                  {name}
                </span>
              ))}
            </div>
          </div>
        )}
      </GlassCard>

      <GlassCard className="border-dashed p-5 text-center font-mono text-[12px] text-slate-500">
        ResearchLens 评估 —— 指标基于论文内部真实的断言↔证据链接关系测算；缺真值的指标标注"未评测"，不以 0 冒充。
      </GlassCard>
    </div>
  );
}
