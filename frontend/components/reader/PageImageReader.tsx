'use client';

// 页面图片兜底（§3.2 / §5.12）：PDF.js 失败时按需请求页预览图片，不预生成整篇。

import { useState } from 'react';
import { ImageOff } from 'lucide-react';
import { api } from '@/lib/api';
import type { RevisionId } from '@/lib/contracts';

export function PageImageReader({
  paperId,
  pdfPageNo,
  revisionId,
  label,
}: {
  paperId: number;
  pdfPageNo: number;
  revisionId?: RevisionId;
  label?: string | null;
}) {
  const [failed, setFailed] = useState(false);
  const src = api.pagePreviewUrl(paperId, pdfPageNo, revisionId);

  if (failed) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-slate-200 bg-slate-50 p-8 text-slate-400">
        <ImageOff className="h-6 w-6" />
        <span className="text-sm">页预览不可用</span>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-white">
      <img
        src={src}
        alt={label ? `第 ${label} 页` : `第 ${pdfPageNo} 页`}
        className="h-auto w-full"
        onError={() => setFailed(true)}
      />
      <span className="absolute bottom-2 right-2 rounded bg-slate-900/70 px-1.5 py-0.5 text-[10px] text-white">
        第 {pdfPageNo} 页
      </span>
    </div>
  );
}
