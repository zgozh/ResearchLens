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
import { Gauge, ShieldAlert, CheckCircle2, ListChecks, Info, Bot } from 'lucide-react';
import type { EvaluationReport } from '@/lib/contracts';
import type { ClaimSummary, EvaluationOut } from '@/lib/types';
import { Badge, GlassCard, Kicker, Meter } from '@/components/ui';
import {
  buildMetricViews,
  findConflicts,
  NOT_APPLICABLE_REASONS,
  parseAiJudge,
  parseOverall,
  reasonText,
} from '@/lib/evalMetrics';

/** canonical 比率型指标（值域 0–1，展示为百分比）。 */
const RATIO_METRICS: { key: string; label: string; color: string; hint?: string }[] = [
  { key: 'source_asset_coverage', label: '原件资产覆盖率', color: '#22D3EE', hint: '断言引用的图/表有多少能落到真实资产' },
  { key: 'anchor_page_accuracy', label: '锚点页准确率', color: '#6366F1' },
  { key: 'anchor_region_hit_rate', label: '锚点区域命中率', color: '#38BDF8' },
  { key: 'quote_exact_rate', label: '引文精确率', color: '#34D399' },
  { key: 'support_precision', label: '证据支撑精确率', color: '#A78BFA' },
  { key: 'support_recall', label: '证据支撑召回率', color: '#8B5CF6', hint: '需要 Golden Set 真值' },
  { key: 'unsupported_fact_escape_rate', label: '无支撑事实逃逸率（目标 ≈ 0）', color: '#F43F5E' },
  // R4-M3/M5：不可答题**诚实率**取代旧的"拒答率"；`answerable_false_refusal_rate`
  // 已删除（它测的"可答题被误拒"行为随"拒答退出产品语义"一并消失，留着就是恒 0 的假指标）。
  { key: 'unanswerable_honesty_rate', label: '不可答问题如实率', color: '#F59E0B',
    hint: '对真正不可答的问题，是否如实说明论文没有依据' },
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
  // 指标来源：**唯一解析函数**（M8）。修掉的 bug：canonical `report.metrics` 是
  // `list[MetricEntry]`，`entry.value` 是 MetricValue **对象**；旧代码把对象当数字用
  // （`toNumber(对象)` = NaN）→ 明明算出来的 0.3571 / 1.0 / 0.6667 全被渲染成"未评测"。
  const metricViews = buildMetricViews(report?.metrics ?? null, evalData.metrics ?? null);
  // 两个数据源打架时**必须显式告知**（实测 paper 7：持久化报告说未评测、现算说 1.0）
  const metricConflicts = findConflicts(report?.metrics ?? null, evalData.metrics ?? null);
  const viewByName = new Map(metricViews.map((v) => [v.name, v]));
  const metricValue = (key: string): number | null => viewByName.get(key)?.value ?? null;
  const notEvaluatedViews = metricViews.filter((v) => v.status === 'not_evaluated');
  const unparsableViews = metricViews.filter((v) => v.status === 'unparsable');

  const notEvaluated = notEvaluatedViews.map((v) => v.name);
  // AI 裁判结论（支撑判定的计数）：它同时解释 support_precision/recall 为什么是 proxy。
  const aiJudge = parseAiJudge(evalData.metrics ?? null);
  // 原因码：优先取解析结果里的 reason（canonical 的 MetricValue.reason），
  // 再回落到 legacy 的 not_evaluated_reasons 表。
  const legacyReasons: Record<string, string> =
    evalData.metrics && typeof evalData.metrics.not_evaluated_reasons === 'object'
      ? (evalData.metrics.not_evaluated_reasons as Record<string, string>)
      : {};
  const reasonOf = (name: string) => viewByName.get(name)?.reason ?? legacyReasons[name];
  // proxy 指标：值算出来了、但口径是"间接测量"，必须**标着 proxy 显示**而不是当未评测藏起来。
  const isProxy = (name: string) => viewByName.get(name)?.status === 'proxy';
  // R4-M5（ADR D-105）：主分 = **AI 质量评分（自动）**，单一口径。
  // 旧的双口径（人工真值 / AI）已随"取消一切跟人工有关的"删除。
  const overall = parseOverall(report?.metrics ?? null, evalData.metrics ?? null);
  const aiScoreValue = overall.score;
  const humanScore = aiScoreValue;   // 主位就是它（保留变量名以免大改 JSX）
  const scoreAvailable =
    humanScore !== null && evalData.metrics?.overall_score_available !== false;
  const aiScoreAvailable = false;    // 已合并到主位，不再有副卡
  const hasAnyScore = humanScore !== null;

  const claimCount = claims?.length ?? 0;
  const supportedCount = claims?.filter((c) => c.status === 'SUPPORTED').length ?? 0;
  const unsupportedCount = claimCount - supportedCount;
  const unsupportedRate = metricValue('unsupported_fact_escape_rate');
  // **只有真的算出来过**才允许说"通过"；null 必须显示"未评测"。
  const gatePassed = unsupportedRate !== null && unsupportedRate === 0;
  // R4-M5：金标集只有一种形态（AI 从原文构造），说明性告警取代"待人工确认"。
  const goldenAiConstructed = (report?.warnings ?? []).some(
    (w) => w.code === 'golden_ai_constructed',
  );

  return (
    <div className="space-y-6">
      {/* 总评 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[300px,1fr]">
        <GlassCard className="flex flex-col items-center justify-center p-6 text-center">
          <Kicker className="mb-3">AI 质量评分（自动）</Kicker>
          {humanScore !== null ? (
            <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
              className="relative grid h-40 w-40 place-items-center">
              <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
                <circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
                <motion.circle cx="60" cy="60" r="52" fill="none" stroke={accent} strokeWidth="10" strokeLinecap="round"
                  strokeDasharray={`${(Math.max(0, Math.min(100, humanScore)) / 100) * 326.7} 326.7`}
                  initial={{ strokeDasharray: '0 326.7' }}
                  animate={{ strokeDasharray: `${(Math.max(0, Math.min(100, humanScore)) / 100) * 326.7} 326.7` }}
                  transition={{ duration: 1.1, ease: 'easeOut' }} />
              </svg>
              <div className="absolute inset-0 grid place-items-center">
                <div>
                  <div className="text-4xl font-bold text-white">{Math.round(humanScore)}</div>
                  <div className="font-mono text-[10px] uppercase text-slate-500">/ 100</div>
                </div>
              </div>
            </motion.div>
          ) : (
            <div className="grid h-40 w-40 place-items-center rounded-full border border-dashed border-white/15">
              <div>
                <div className="text-2xl font-bold text-slate-400">未评测</div>
                <div className="mt-1 font-mono text-[10px] uppercase text-slate-600">
                  NOT EVALUATED
                </div>
              </div>
            </div>
          )}
          <div className="mt-4 flex items-center gap-1.5 text-[11px] text-slate-500">
            <Gauge className="h-3.5 w-3.5" /> 自动质量评测
          </div>
          {/* R4-M5 决策底线 2：分数来源必须可见 —— 删掉人工口径不等于不标来源。 */}
          <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
            由 AI 裁判与程序测量自动得出，<strong>非人工评审</strong>。
          </p>
        </GlassCard>

        <GlassCard className="p-6">
          <Kicker className="mb-4">核心指标 · HEADLINE</Kicker>
          {scoreAvailable ? null : (
            <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-[12px] text-amber-200">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {goldenAiConstructed ? (
                  'AI 质量评分尚未产出：金标集由 AI 从原文构造，AI 裁判本次未给出结论'
                  + '（support_precision/recall 因此不可用）；主分不以 0 冒充。'
                ) : (
                  '本篇尚未产出可用的 AI 质量评分：核心指标缺样本'
                  + '（需要金标集、引文跨度与已跑通的问答轨迹）。'
                )}
                界面不以 0 分冒充通过，缺失项一律标注"未评测"。
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
          {report?.golden_id ? (
            <Badge tone="emerald">金标集：AI 构造</Badge>
          ) : (
            <Badge tone="amber">缺少金标集</Badge>
          )}
          {report?.version && (
            <span className="font-mono text-[10px] text-slate-500">{report.version}</span>
          )}
        </div>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {RATIO_METRICS.map((meta) => {
            const value = metricValue(meta.key);
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
                    proxy：间接口径（AI 判定或间接测量，必须标明来源）
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
              const value = metricValue(meta.key);
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

        {aiJudge && (
          <div className="mt-5 rounded-xl border border-indigo-500/25 bg-indigo-500/[0.06] p-3.5">
            <div className="mb-2.5 flex flex-wrap items-center gap-2 text-[11px] text-indigo-200">
              <Bot className="h-3.5 w-3.5" />
              AI 裁判 · 断言↔真值支撑判定
              {aiJudge.model && (
                <span className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  模型 {aiJudge.model}
                </span>
              )}
            </div>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <div className="font-mono text-lg font-bold text-white">
                  {aiJudge.truePositive}/{aiJudge.totalPredicted}
                </div>
                <div className="mt-0.5 text-[10px] text-slate-500">命中 / 预测断言</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold text-white">
                  {aiJudge.precision === null ? '—' : `${(aiJudge.precision * 100).toFixed(1)}%`}
                </div>
                <div className="mt-0.5 text-[10px] text-slate-500">支撑精确率（proxy）</div>
              </div>
              <div>
                <div className="font-mono text-lg font-bold text-white">
                  {aiJudge.recall === null ? '—' : `${(aiJudge.recall * 100).toFixed(1)}%`}
                </div>
                <div className="mt-0.5 text-[10px] text-slate-500">
                  支撑召回率（proxy）· 真值 {aiJudge.totalGolden} 条
                </div>
              </div>
            </div>
            <p className="mt-2.5 text-[10px] leading-relaxed text-slate-500">
              上面两个比例就是「证据支撑精确率 / 召回率」的来源：由 AI 裁判逐条判定预测断言
              是否被真值支持（命中 ÷ 预测、命中 ÷ 真值），属<strong className="text-amber-300/80">间接口径 proxy</strong>，
              不是人工标注 —— 所以那两项在明细里带 proxy 标记。
            </p>
          </div>
        )}

        {notEvaluated.length > 0 && (
          <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.02] p-3.5">
            <div className="mb-2 flex items-center gap-2 text-[11px] text-slate-400">
              <Info className="h-3.5 w-3.5" />
              未评测指标（{notEvaluated.length} 项）——不是 0 分，是尚无真值：
            </div>
            <div className="flex flex-wrap gap-1.5">
              {notEvaluated.map((name) => {
                const code = reasonOf(name);
                const why = reasonText(code);
                // M9：设计上就不可测的指标（如原文没有坐标矩形）标"不适用"，
                // 与"暂时没有真值"分开 —— 两者对用户的含义完全不同。
                const na = code ? NOT_APPLICABLE_REASONS.has(code) : false;
                return (
                  <span
                    key={name}
                    title={`${na ? '不适用' : '为什么未评测'}：${why}${code ? `（${code}）` : ''}`}
                    className="inline-flex items-center gap-1 rounded-md bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-slate-500"
                  >
                    {name}
                    <span className={na ? 'text-amber-500/80' : 'text-slate-600'}>
                      · {na ? '不适用' : why}
                    </span>
                  </span>
                );
              })}
            </div>
            {unparsableViews.length > 0 && (
              <div className="mt-2 rounded-md border border-rose-500/30 bg-rose-500/5 px-2 py-1 font-mono text-[10px] text-rose-300">
                数据异常（解析失败）：{unparsableViews.map((v) => v.name).join('、')}
                ——这不是"未评测"，是前端没认出后端返回的形态，请报障。
              </div>
            )}
            {metricConflicts.length > 0 && (
              <div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1 text-[10px] text-amber-300">
                两个数据源不一致（持久化报告 vs 现算结果），已按持久化报告显示：
                {metricConflicts
                  .map((c) => `${c.name}（报告=${c.canonical ?? '未评测'} / 现算=${c.legacy}）`)
                  .join('；')}
              </div>
            )}
          </div>
        )}
      </GlassCard>

      <GlassCard className="border-dashed p-5 text-center font-mono text-[12px] text-slate-500">
        ResearchLens 评估 —— 指标基于论文内部真实的断言↔证据链接关系测算；缺真值的指标标注"未评测"，不以 0 冒充。
      </GlassCard>
    </div>
  );
}
