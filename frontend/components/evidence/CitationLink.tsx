'use client';

// 引用链接（§5.13）：{evidence, onNavigate}。
// 展示"PDF 第 N 页 / 印刷页 label"；未知 label 不显示。

import { FileText } from 'lucide-react';
import type { EvidenceRecord, NavigationTarget } from '@/lib/contracts';

export function CitationLink({
  evidence,
  onNavigate,
}: {
  evidence: EvidenceRecord;
  onNavigate: (target: NavigationTarget) => void;
}) {
  const page = evidence.source_page;
  const label = evidence.source_region?.[0]?.page_label ?? null;

  const navigate = () => {
    onNavigate({
      paper_id: evidence.paper_id,
      revision_id: evidence.revision_id,
      anchor_id: evidence.anchor_id,
      segment_index: 0,
    });
  };

  return (
    <button
      onClick={navigate}
      className="inline-flex items-center gap-1.5 rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-700 transition hover:bg-indigo-50 hover:text-indigo-700"
    >
      <FileText className="h-3.5 w-3.5" />
      <span className="font-medium">PDF 第 {page} 页</span>
      {label && <span className="text-slate-400">/ 印刷页 {label}</span>}
    </button>
  );
}
