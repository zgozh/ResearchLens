'use client';

// 证据抽屉（§5.13）：{scope, evidence_ids, open, onClose}。
// 桌面 rail 与移动抽屉共享同一 EvidenceContent，不因断点隐藏核验能力。
// 额外暴露 onNavigate（可选）用于接线阅读器定位；§5.13 最小契约已满足。

import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ScanSearch, X } from 'lucide-react';
import type { EvidenceRecord, Id, NavigationTarget, Scope } from '@/lib/contracts';
import { api } from '@/lib/api';
import { CitationLink } from './CitationLink';
import { VerificationStatus } from './VerificationStatus';

function EvidenceContent({
  evidence,
  loading,
  onNavigate,
}: {
  evidence: EvidenceRecord[];
  loading: boolean;
  onNavigate?: (target: NavigationTarget) => void;
}) {
  if (loading) {
    return <div className="p-4 text-sm text-slate-400">加载证据中…</div>;
  }
  if (evidence.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-6 text-center text-slate-400">
        <ScanSearch className="h-6 w-6" />
        <p className="text-sm">暂无证据</p>
      </div>
    );
  }
  return (
    <ul className="space-y-3 p-4">
      {evidence.map((e) => {
        // 此前任何非 supports 的证据都显示"待核验"——那是错的：`contradicts` 是**已被反驳**、
        // `insufficient` 是**证据不足**，两者都已经有结论，不是"待核验"。
        // 只有真正没有判定（空/undefined/unreviewed）才叫待核验。
        const meta = SUPPORT_META[e.support_status as string] ?? {
          status: 'unverified' as const, label: '待核验',
        };
        return (
        <li key={e.id} className="rounded-xl border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center gap-2">
            <VerificationStatus status={meta.status} label={meta.label} />
            <span className="ml-auto font-mono text-[10px] text-slate-400">{e.claim_id}</span>
          </div>
          <p className="mb-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{e.source_text}</p>
          {onNavigate && <CitationLink evidence={e} onNavigate={onNavigate} />}
        </li>
        );
      })}
    </ul>
  );
}

/** 证据的支撑结论 → 展示状态与文案（一一对应，不再把所有非 supports 都说成"待核验"）。 */
const SUPPORT_META: Record<string, { status: 'verified' | 'unverified' | 'contested' | 'inference'; label: string }> = {
  supports: { status: 'verified', label: '支持' },
  contradicts: { status: 'contested', label: '反驳' },
  insufficient: { status: 'unverified', label: '证据不足' },
  unreviewed: { status: 'unverified', label: '未判定' },
  '': { status: 'unverified', label: '未判定' },
};

export function EvidenceDrawer({
  scope,
  evidence_ids,
  open,
  onClose,
  onNavigate,
}: {
  scope: Scope;
  evidence_ids: Id[];
  open: boolean;
  onClose: () => void;
  onNavigate?: (target: NavigationTarget) => void;
}) {
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const idsKey = evidence_ids.join(',');

  useEffect(() => {
    if (!open || evidence_ids.length === 0) {
      setEvidence([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    Promise.all(evidence_ids.map((id) => api.getEvidence(scope.paper_id, id, scope.revision_id)))
      .then((rs) => {
        if (!cancelled) setEvidence(rs.map((r) => r.evidence));
      })
      .catch(() => {
        if (!cancelled) setEvidence([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, idsKey, scope.paper_id, scope.revision_id]);

  const header = (
    <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
      <span className="font-mono text-xs uppercase tracking-widest text-slate-500">证据 · EVIDENCE</span>
      <button
        onClick={onClose}
        className="grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
        aria-label="关闭"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );

  return (
    <>
      {/* 桌面 rail */}
      {open && (
        <aside className="hidden h-full w-80 shrink-0 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 lg:block">
          {header}
          <EvidenceContent evidence={evidence} loading={loading} onNavigate={onNavigate} />
        </aside>
      )}

      {/* 移动抽屉 */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 lg:hidden"
            onClick={onClose}
          >
            <div className="absolute inset-0 bg-slate-900/40" />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'tween', duration: 0.25 }}
              className="absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-2xl bg-slate-50"
              onClick={(e) => e.stopPropagation()}
            >
              {header}
              <EvidenceContent evidence={evidence} loading={loading} onNavigate={onNavigate} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
