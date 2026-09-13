'use client';

// 证据 verdict 徽标（REFACTOR_PLAN_R3 M2）。
//
// 四类语义（非研究发现 / 真矛盾 / 有支持但未通过其他检查 / 证据不足）+ 可展开的理由。
// 分类规则全部来自 `lib/evidenceVerdict.ts`（唯一真相），本组件只负责显示。
//
// 为什么重要：把这 9 条非 verified 全写成"未支持"会把语义压平 ——
// 其中 6 条其实是**系统主动排除的非研究发现**，用户会误以为"系统没能证明"。

import { useState } from 'react';
import { AlertTriangle, Ban, CircleHelp, Info, ShieldAlert } from 'lucide-react';
import { classifyVerdict, type EvidenceVerdictView } from '@/lib/evidenceVerdict';
import { cn } from '@/lib/cn';

const ICON: Record<EvidenceVerdictView['category'], typeof Info> = {
  non_claim: Ban,
  contradiction: ShieldAlert,
  rejected_other: AlertTriangle,
  insufficient: CircleHelp,
};

const TONE: Record<EvidenceVerdictView['category'], string> = {
  non_claim: 'border-slate-500/40 bg-white/[0.05] text-slate-300',
  contradiction: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
  rejected_other: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  insufficient: 'border-slate-500/30 bg-white/[0.03] text-slate-400',
};

export function VerdictBadge({
  validation,
  className,
  showReasons = true,
}: {
  /** 后端 `validation{decision, semantic_status, reasons}`；缺失时不渲染。 */
  validation: unknown;
  className?: string;
  showReasons?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const view = classifyVerdict(validation);
  if (!view) return null;
  const Icon = ICON[view.category];
  return (
    <span className={cn('inline-flex flex-col items-start gap-1', className)}>
      <button
        type="button"
        onClick={() => showReasons && setOpen((v) => !v)}
        title={view.explain}
        className={cn(
          'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium',
          TONE[view.category],
          showReasons && view.reasons.length > 0 ? 'cursor-pointer' : 'cursor-default',
        )}
      >
        <Icon className="h-3 w-3" />
        {view.label}
        {view.reasons.length > 0 && (
          <span className="opacity-60">{open ? '▾' : '▸'}</span>
        )}
      </button>
      {open && (
        <span className="max-w-[420px] rounded-md border border-white/10 bg-white/[0.03] px-2 py-1.5 text-[10px] leading-relaxed text-slate-400">
          <span className="mb-1 block text-slate-500">{view.explain}</span>
          {view.reasons.map((r, i) => (
            <span key={`${r.code}-${i}`} className="mt-0.5 block">
              <span className="font-mono text-slate-500">[{r.code}]</span> {r.message}
            </span>
          ))}
        </span>
      )}
    </span>
  );
}
