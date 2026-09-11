'use client';

// 分页选择器（§3.2）：上一页/下一页 + 页码输入 + 总数。

import { ChevronLeft, ChevronRight } from 'lucide-react';

export function PageSelector({
  page,
  pageCount,
  onSelect,
}: {
  page: number;
  pageCount: number;
  onSelect: (page: number) => void;
}) {
  const clamp = (p: number) => Math.min(Math.max(1, p), Math.max(1, pageCount));
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => onSelect(clamp(page - 1))}
        disabled={page <= 1}
        className="grid h-8 w-8 place-items-center rounded-lg border border-slate-200 bg-white text-slate-600 transition hover:bg-slate-50 disabled:opacity-40"
        aria-label="上一页"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span className="flex items-center gap-1 text-sm text-slate-600">
        <input
          type="number"
          min={1}
          max={pageCount}
          value={page}
          onChange={(e) => onSelect(clamp(Number(e.target.value)))}
          className="w-14 rounded-md border border-slate-200 bg-white px-2 py-1 text-center text-sm text-slate-800 outline-none focus:border-indigo-400"
          aria-label="页码"
        />
        <span className="text-slate-400">/ {pageCount}</span>
      </span>
      <button
        onClick={() => onSelect(clamp(page + 1))}
        disabled={page >= pageCount}
        className="grid h-8 w-8 place-items-center rounded-lg border border-slate-200 bg-white text-slate-600 transition hover:bg-slate-50 disabled:opacity-40"
        aria-label="下一页"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
