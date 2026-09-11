'use client';

// 校验状态徽标（§5.13）：verified/inference/contested/unverified/rejected。

import { CheckCircle2, CircleDashed, HelpCircle, XCircle, AlertTriangle } from 'lucide-react';
import { cn } from '@/lib/cn';

export type VerificationStatusValue =
  | 'verified'
  | 'inference'
  | 'contested'
  | 'unverified'
  | 'rejected';

const MAP: Record<VerificationStatusValue, { label: string; cls: string; icon: typeof CheckCircle2 }> = {
  verified: { label: '已验证', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: CheckCircle2 },
  inference: { label: '推断', cls: 'bg-sky-50 text-sky-700 border-sky-200', icon: HelpCircle },
  contested: { label: '有争议', cls: 'bg-rose-50 text-rose-700 border-rose-200', icon: AlertTriangle },
  unverified: { label: '待核验', cls: 'bg-amber-50 text-amber-700 border-amber-200', icon: CircleDashed },
  rejected: { label: '已拒绝', cls: 'bg-slate-100 text-slate-500 border-slate-200', icon: XCircle },
};

export function VerificationStatus({
  status,
  label,
  className,
}: {
  status: VerificationStatusValue;
  label?: string;
  className?: string;
}) {
  const item = MAP[status] ?? MAP.unverified;
  const Icon = item.icon;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium',
        item.cls,
        className,
      )}
    >
      <Icon className="h-3 w-3" />
      {label ?? item.label}
    </span>
  );
}
