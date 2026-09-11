'use client';

// 提取公式视图（§5.13）：KaTeX trust=false、禁危险宏。
// 渲染失败显示"可转原件"状态；原编号来自解析/人工标注，不自动编造。

import { Sigma } from 'lucide-react';
import type { Media } from '@/lib/contracts';
import { renderKatex } from '@/lib/sanitize';

export function ExtractedFormula({ media, onShowOriginal }: {
  media: Media;
  onShowOriginal: (mediaId: string) => void;
}) {
  const latex = media.extracted?.latex ?? '';
  const label = media.extracted?.equation_label ?? media.original_label ?? null;
  const html = renderKatex(latex, true);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      {label && (
        <div className="mb-2 text-right font-mono text-xs text-slate-400">
          编号 · {label}
        </div>
      )}
      {html ? (
        <div
          className="overflow-x-auto text-center text-[15px] text-slate-900"
          // KaTeX trust=false 输出已禁用危险宏
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-6 text-center">
          <Sigma className="h-8 w-8 text-slate-300" />
          <p className="text-sm text-slate-500">公式渲染失败，可查看原件。</p>
          <button
            onClick={() => onShowOriginal(media.id)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-indigo-600 transition hover:bg-slate-50"
          >
            查看原件
          </button>
        </div>
      )}
    </div>
  );
}
