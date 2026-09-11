'use client';

// 来源徽标：原件 / 提取(再排版) / 示意 / 不可用。

import { CircleSlash, FileCheck2, FileCode2, PenTool } from 'lucide-react';
import type { MediaViewMode } from '@/lib/contracts';
import { MEDIA_MODE_LABELS } from '@/lib/sourcePolicy';
import { cn } from '@/lib/cn';

const TONES: Record<MediaViewMode, string> = {
  original: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  extracted: 'bg-sky-50 text-sky-700 border-sky-200',
  synthetic: 'bg-amber-50 text-amber-700 border-amber-200',
  unavailable: 'bg-slate-100 text-slate-500 border-slate-200',
};

const ICONS: Record<MediaViewMode, typeof FileCheck2> = {
  original: FileCheck2,
  extracted: FileCode2,
  synthetic: PenTool,
  unavailable: CircleSlash,
};

export function SourceBadge({ mode, label, className }: {
  mode: MediaViewMode;
  label?: string;
  className?: string;
}) {
  const Icon = ICONS[mode];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium',
        TONES[mode],
        className,
      )}
    >
      <Icon className="h-3 w-3" />
      {label ?? MEDIA_MODE_LABELS[mode]}
    </span>
  );
}
