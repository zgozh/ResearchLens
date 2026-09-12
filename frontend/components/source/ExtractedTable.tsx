'use client';

// 提取表格视图（§5.13）：DOMPurify 严格白名单清理后内联到受约束容器。
// 清理破坏结构时退回原件（显示"退回原件"按钮），不退回截断矩阵。

import { Table2 } from 'lucide-react';
import type { Media } from '@/lib/contracts';
import { sanitizeTableHtml } from '@/lib/sanitize';
import { renderMathInHtml } from '@/lib/mathHtml';

export function ExtractedTable({ media, onShowOriginal }: {
  media: Media;
  onShowOriginal: (mediaId: string) => void;
}) {
  const html = media.extracted?.table_html ?? '';
  // 先消毒，再把单元格里的 LaTeX 渲染成公式（否则用户看到的是 `$1.0 \cdot 10^{20}$` 源码）
  const clean = renderMathInHtml(sanitizeTableHtml(html));

  if (!clean) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-slate-200 bg-slate-50 p-6 text-center">
        <Table2 className="h-8 w-8 text-slate-300" />
        <p className="text-sm text-slate-500">提取表格结构无法安全清理，已退回原件。</p>
        <button
          onClick={() => onShowOriginal(media.id)}
          className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-indigo-600 transition hover:bg-slate-50"
        >
          查看原件
        </button>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <div
        className="rl-table min-w-max"
        // 已由 DOMPurify 严格白名单清理；样式由 .rl-table 受约束容器统一提供
        dangerouslySetInnerHTML={{ __html: clean }}
      />
    </div>
  );
}
