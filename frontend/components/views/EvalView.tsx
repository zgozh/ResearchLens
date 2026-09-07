'use client';

import { motion } from 'framer-motion';
import { Gauge, ShieldAlert, CheckCircle2, ListChecks, Users, UserCheck } from 'lucide-react';
import type { EvaluationOut } from '@/lib/types';
import { Badge, GlassCard, Kicker, Meter } from '@/components/ui';

const METER_STYLE: Record<string, string> = {
  citation_coverage: '#6366F1',
  claim_evidence_alignment: '#22D3EE',
  unsupported_claim_rate: '#F43F5E',
  structure_accuracy: '#34D399',
  visual_consistency: '#F59E0B',
  answer_grounding: '#8B5CF6',
};
const LABEL: Record<string, string> = {
  citation_coverage: '引用覆盖率',
  claim_evidence_alignment: '断言-证据对齐度',
  unsupported_claim_rate: '无证据断言率',
  structure_accuracy: '结构抽取准确率',
  visual_consistency: '视觉一致性',
  answer_grounding: '答案 grounded 程度',
};

export function EvalView({ evalData, accent }: { evalData: EvaluationOut; accent: string }) {
  const m = evalData.metrics || {};
  const unsupported = Number(m.unsupported_claim_rate ?? 0);
  const audience = (m.audience || {}) as Record<string, number>;
  const author = (m.author || {}) as Record<string, number>;
  const positive = [
    ['citation_coverage', 'citation_coverage'],
    ['claim_evidence_alignment', 'claim_evidence_alignment'],
    ['structure_accuracy', 'structure_accuracy'],
    ['visual_consistency', 'visual_consistency'],
    ['answer_grounding', 'answer_grounding'],
  ] as const;

  return (
    <div className="space-y-6">
      {/* 总评 + 核心指标 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[300px,1fr]">
        <GlassCard className="flex flex-col items-center justify-center p-6 text-center">
          <Kicker className="mb-3">综合评分 · SCORE</Kicker>
          <motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
            className="relative grid h-40 w-40 place-items-center">
            <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
              <circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
              <motion.circle cx="60" cy="60" r="52" fill="none" stroke={accent} strokeWidth="10" strokeLinecap="round"
                strokeDasharray={`${(evalData.overall_score / 100) * 326.7} 326.7`}
                initial={{ strokeDasharray: '0 326.7' }}
                animate={{ strokeDasharray: `${(evalData.overall_score / 100) * 326.7} 326.7` }}
                transition={{ duration: 1.1, ease: 'easeOut' }} />
            </svg>
            <div className="absolute inset-0 grid place-items-center">
              <div>
                <div className="text-4xl font-bold text-white">{Math.round(evalData.overall_score)}</div>
                <div className="font-mono text-[10px] uppercase text-slate-500">/ 100</div>
              </div>
            </div>
          </motion.div>
          <div className="mt-4 flex items-center gap-1.5 text-[11px] text-slate-500">
            <Gauge className="h-3.5 w-3.5" /> 自动质量评测
          </div>
        </GlassCard>

        <GlassCard className="p-6">
          <Kicker className="mb-4">核心指标 · HEADLINE</Kicker>
          <div className="grid grid-cols-3 gap-4">
            {[
              { v: Number(m.citation_coverage ?? 0), l: '证据覆盖率', c: '#22D3EE' },
              { v: Number(m.claim_evidence_alignment ?? 0), l: '断言-证据对齐', c: '#6366F1' },
              { v: unsupported, l: '无证据断言', c: unsupported === 0 ? '#34D399' : '#F59E0B' },
            ].map((x) => (
              <div key={x.l} className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-4 text-center">
                <div className="text-3xl font-bold" style={{ color: x.c }}>{x.v.toFixed(1)}%</div>
                <div className="mt-1 text-[11px] text-slate-500">{x.l}</div>
              </div>
            ))}
          </div>
          {(m.num_claims != null) && (
            <div className="mt-5 flex items-center justify-between border-t border-[var(--line)] pt-4 text-[12px] text-slate-400">
              <span className="inline-flex items-center gap-2">
                <ListChecks className="h-4 w-4 text-slate-500" />
                已落地 {m.num_supported}/{m.num_claims} 条断言
              </span>
              <span className={unsupported === 0 ? 'inline-flex items-center gap-1.5 text-emerald-400' : 'inline-flex items-center gap-1.5 text-amber-400'}>
                <CheckCircle2 className="h-4 w-4" />
                {unsupported === 0 ? '0 条无证据断言（目标≈0）' : `${unsupported}% 无证据`}
              </span>
            </div>
          )}
        </GlassCard>
      </div>

      {/* 双维度：观众 / 作者 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <GlassCard className="p-6">
          <div className="mb-3 flex items-center gap-2">
            <Users className="h-4 w-4 text-cyan-400" />
            <Kicker>面向观众 · AUDIENCE</Kicker>
          </div>
          <div className="space-y-4">
            <Meter value={audience.faithful ?? 0} label="忠实传达（Faithful）" color="#22D3EE" />
            <Meter value={audience.accessible ?? 0} label="易读可及（Accessible）" color="#38BDF8" />
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            衡量讲解能否忠实传达论文核心思想、并对不同背景的观众友好。
          </p>
        </GlassCard>
        <GlassCard className="p-6">
          <div className="mb-3 flex items-center gap-2">
            <UserCheck className="h-4 w-4 text-violet-400" />
            <Kicker>面向作者 · AUTHOR</Kicker>
          </div>
          <div className="space-y-4">
            <Meter value={author.contribution ?? 0} label="原创贡献凸显（Contribution）" color="#8B5CF6" />
            <Meter value={author.visibility ?? 0} label="可见度（Visibility）" color="#A78BFA" />
          </div>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            衡量是否凸显作者的原创贡献与成果可见度。
          </p>
        </GlassCard>
      </div>

      {/* 指标明细 */}
      <GlassCard className="p-6">
        <Kicker className="mb-4">评测指标 · METRICS</Kicker>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {positive.map(([key]) => (
            <Meter key={key} value={Number(m[key] ?? 0)} label={LABEL[key]} color={METER_STYLE[key]} />
          ))}
          <div>
            <Meter value={unsupported} label="无证据断言率（目标 ≈ 0）" color={METER_STYLE.unsupported_claim_rate} />
            <p className="mt-1.5 text-[11px] text-slate-500">
              {unsupported === 0 ? '已通过 Evidence Gate，所有断言均有证据。' : '仍有断言未绑定证据，未进入事实层。'}
            </p>
          </div>
        </div>
      </GlassCard>

      {/* 逐断言明细 */}
      <GlassCard className="p-6">
        <Kicker className="mb-4">逐断言明细 · CLAIM BREAKDOWN</Kicker>
        <div className="overflow-hidden rounded-lg border border-[var(--line)]">
          <table className="w-full text-left text-[12px]">
            <thead>
              <tr className="bg-white/[0.04]">
                <th className="px-3 py-2 font-medium text-slate-300">断言</th>
                <th className="px-3 py-2 font-medium text-slate-300">类型</th>
                <th className="px-3 py-2 font-medium text-slate-300">状态</th>
                <th className="px-3 py-2 font-medium text-slate-300">置信度</th>
                <th className="px-3 py-2 font-medium text-slate-300">证据</th>
              </tr>
            </thead>
            <tbody>
              {/* 该明细由证据链视图提供；此处以汇总呈现 */}
              <tr className="border-t border-[var(--line)]">
                <td className="px-3 py-2 text-slate-300">共 {m.num_claims} 条</td>
                <td className="px-3 py-2 text-slate-400">RESULT/METHOD/…</td>
                <td className="px-3 py-2"><Badge tone={unsupported === 0 ? 'emerald' : 'amber'}>{m.num_unsupported} 条未支持</Badge></td>
                <td className="px-3 py-2 text-slate-400">均值 {((m.claim_evidence_alignment ?? 0) / 100).toFixed(2)}</td>
                <td className="px-3 py-2 text-slate-400">{m.num_supported} 条已绑定</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11px] text-slate-500">完整逐条断言与证据请查看「证据链」视图。</p>
      </GlassCard>

      <GlassCard className="border-dashed p-5 text-center font-mono text-[12px] text-slate-500">
        ResearchLens 评估 —— 指标基于论文内部真实的断言↔证据链接关系测算，非编造数字。
      </GlassCard>
    </div>
  );
}
