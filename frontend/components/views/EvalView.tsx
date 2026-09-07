'use client';

import { motion } from 'framer-motion';
import { Gauge, ShieldAlert, CheckCircle2, ListChecks } from 'lucide-react';
import type { EvaluationOut } from '@/lib/types';
import { GlassCard, Kicker, Meter } from '@/components/ui';

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
  const unsupported = m.unsupported_claim_rate ?? 0;
  const positive = [
    ['citation_coverage', 'citation_coverage'],
    ['claim_evidence_alignment', 'claim_evidence_alignment'],
    ['structure_accuracy', 'structure_accuracy'],
    ['visual_consistency', 'visual_consistency'],
    ['answer_grounding', 'answer_grounding'],
  ] as const;

  return (
    <div className="space-y-6">
      {/* Overall + headline numbers */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[300px,1fr]">
        <GlassCard className="flex flex-col items-center justify-center p-6 text-center">
          <Kicker className="mb-3">综合评分 · SCORE</Kicker>
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="relative grid h-40 w-40 place-items-center"
          >
            <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
              <circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
              <motion.circle
                cx="60" cy="60" r="52" fill="none"
                stroke={accent} strokeWidth="10" strokeLinecap="round"
                strokeDasharray={`${(evalData.overall_score / 100) * 326.7} 326.7`}
                initial={{ strokeDasharray: '0 326.7' }}
                animate={{ strokeDasharray: `${(evalData.overall_score / 100) * 326.7} 326.7` }}
                transition={{ duration: 1.1, ease: 'easeOut' }}
              />
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
              { v: m.citation_coverage ?? 0, l: '证据覆盖率', c: '#22D3EE' },
              { v: m.claim_evidence_alignment ?? 0, l: '断言-证据对齐', c: '#6366F1' },
              { v: unsupported, l: '无证据断言', c: unsupported === 0 ? '#34D399' : '#F59E0B' },
            ].map((x) => (
              <div key={x.l} className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-4 text-center">
                <div className="text-3xl font-bold" style={{ color: x.c }}>
                  {x.v.toFixed(1)}%
                </div>
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

      {/* metric meters */}
      <GlassCard className="p-6">
        <Kicker className="mb-4">评测指标 · METRICS</Kicker>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {positive.map(([key]) => (
            <Meter key={key} value={m[key] ?? 0} label={LABEL[key]} color={METER_STYLE[key]} />
          ))}
          <div>
            <Meter
              value={unsupported}
              label="无证据断言率（目标 ≈ 0）"
              color={METER_STYLE.unsupported_claim_rate}
            />
            <p className="mt-1.5 text-[11px] text-slate-500">
              {unsupported === 0 ? '已通过 Evidence Gate，所有断言均有证据。' : '仍有断言未绑定证据，未进入事实层。'}
            </p>
          </div>
        </div>
      </GlassCard>

      <GlassCard className="border-dashed p-5 text-center font-mono text-[12px] text-slate-500">
        ResearchLens 评估 —— 指标基于论文内部真实的断言↔证据链接关系测算，非编造数字。
      </GlassCard>
    </div>
  );
}
