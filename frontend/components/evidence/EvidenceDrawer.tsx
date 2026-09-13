'use client';

// 证据抽屉（§5.13）：{scope, evidence_ids, open, onClose}。
// 桌面 rail 与移动抽屉共享同一 EvidenceContent，不因断点隐藏核验能力。
// 额外暴露 onNavigate（可选）用于接线阅读器定位；§5.13 最小契约已满足。
//
// R4-M1/M2 修复（需求 A/B）：
// · **逐条降级**：`Promise.all` + `.catch(() => setEvidence([]))` 会在任意一条失败时
//   清空**全部**已取回证据，把网络抖动伪装成"这条断言没有证据"。改为 `allSettled`；
// · **空态三分**：尚未抽取 / 确无关联证据 / 拉取失败，文案与可行动作各不相同；
// · **未判定成因细分**：显示"未配置模型 / 超时 / 调用失败"而不是笼统一句"未判定"；
// · **桌面 rail 跟随滚动**：`h-full`（stretch 成左列那根很高的行高，内容永远贴在顶部）
//   改为 `sticky` + 自身滚动；切换断言时内容回到顶部。

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ScanSearch, X, Loader2, AlertTriangle } from 'lucide-react';
import type { EvidenceRecord, Id, NavigationTarget, Scope } from '@/lib/contracts';
import { api } from '@/lib/api';
import { MathText } from '@/components/MathText';
import { CitationLink } from './CitationLink';
import { VerificationStatus } from './VerificationStatus';
import { VerdictBadge } from './VerdictBadge';
import {
  explainEmptyEvidence,
  failureCount,
  settleEvidence,
  unreviewedLabel,
  type CapabilityState,
  type EvidenceSlot,
} from '@/lib/evidenceStates';

function EvidenceContent({
  slots,
  loading,
  emptyText,
  onNavigate,
}: {
  slots: EvidenceSlot[];
  loading: boolean;
  emptyText: { title: string; detail: string };
  onNavigate?: (target: NavigationTarget) => void;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载证据中…
      </div>
    );
  }
  if (slots.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 p-6 text-center text-slate-400">
        <ScanSearch className="h-6 w-6" />
        <p className="text-sm text-slate-300">{emptyText.title}</p>
        <p className="text-[11px] leading-relaxed text-slate-500">{emptyText.detail}</p>
      </div>
    );
  }
  return (
    <ul className="space-y-3 p-4">
      {slots.map((slot) => {
        // 单条失败：**留在列表里**并如实说明，绝不因为一条失败清空整体（R4-M1）。
        if (!slot.evidence) {
          return (
            <li key={slot.id}
                className="rounded-xl border border-rose-500/30 bg-rose-500/[0.06] p-3">
              <div className="mb-1.5 flex items-center gap-2 text-[11px] text-rose-200">
                <AlertTriangle className="h-3.5 w-3.5" />
                该条证据拉取失败（可重试）
              </div>
              <p className="text-[11px] text-rose-300/70">{slot.error}</p>
              <p className="mt-1 font-mono text-[10px] text-slate-500">{slot.id}</p>
            </li>
          );
        }
        const e = slot.evidence;
        // 此前任何非 supports 的证据都显示"待核验"——那是错的：`contradicts` 是**已被反驳**、
        // `insufficient` 是**证据不足**，两者都已经有结论，不是"待核验"。
        // 只有真正没有判定（空/undefined/unreviewed）才叫待核验。
        const meta = SUPPORT_META[e.support_status as string] ?? {
          status: 'unverified' as const, label: '待核验',
        };
        // R4-M1：`未判定` 必须说清成因（未配置模型 / 超时 / 调用失败）。
        const detail = meta.detail ?? unreviewedLabel(slot.validation);
        return (
        <li key={e.id} className="rounded-xl border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center gap-2">
            <VerificationStatus status={meta.status} label={meta.label} />
            {/* R4-M1：与 ClaimView 列表**同源**的四分类徽标（可展开看后端理由） */}
            <VerdictBadge validation={slot.validation} />
            <span className="ml-auto font-mono text-[10px] text-slate-400">{e.claim_id}</span>
          </div>
          {detail && <p className="mb-1.5 text-[10px] leading-relaxed text-slate-500">{detail}</p>}
          <MathText text={e.source_text} className="mb-2 block whitespace-pre-wrap text-sm leading-6 text-slate-700" />
          {onNavigate && <CitationLink evidence={e} onNavigate={onNavigate} />}
        </li>
        );
      })}
    </ul>
  );
}

/** 证据的支撑结论 → 展示状态与文案（一一对应，不再把所有非 supports 都说成"待核验"）。 */
const SUPPORT_META: Record<
  string,
  { status: 'verified' | 'unverified' | 'contested' | 'inference'; label: string; detail?: string }
> = {
  supports: { status: 'verified', label: '支持' },
  contradicts: { status: 'contested', label: '反驳' },
  insufficient: { status: 'unverified', label: '证据不足' },
  // `detail` 留空：`unreviewed` 的成因要从 validation.reasons 现算（R4-M1），
  // 不能再写死一句"语义未判定"——那正是被用户读成"系统没证明"的原因。
  unreviewed: { status: 'unverified', label: '未判定' },
  '': { status: 'unverified', label: '未判定' },
};

export function EvidenceDrawer({
  scope,
  evidence_ids,
  open,
  onClose,
  onNavigate,
  claimsState = 'unknown',
}: {
  scope: Scope;
  evidence_ids: Id[];
  open: boolean;
  onClose: () => void;
  onNavigate?: (target: NavigationTarget) => void;
  /** `manifest.capabilities` 里 claims 域的状态，用于区分"尚未抽取"与"确无关联证据"。 */
  claimsState?: CapabilityState;
}) {
  const [slots, setSlots] = useState<EvidenceSlot[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetchFailed, setFetchFailed] = useState(false);
  const idsKey = evidence_ids.join(',');
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open || evidence_ids.length === 0) {
      setSlots([]);
      setFetchFailed(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setFetchFailed(false);
    // R4-M1：`allSettled` 而不是 `all` —— 一条失败不许清空整体。
    Promise.allSettled(
      evidence_ids.map((id) => api.getEvidence(scope.paper_id, id, scope.revision_id)),
    )
      .then((results) => {
        if (cancelled) return;
        const settled = settleEvidence(
          evidence_ids,
          results.map((r) =>
            r.status === 'fulfilled'
              ? ({ status: 'fulfilled', value: r.value } as const)
              : ({ status: 'rejected', reason: r.reason } as const),
          ),
        );
        setSlots(settled);
        setFetchFailed(failureCount(settled) > 0);
      })
      .catch(() => {
        if (!cancelled) {
          setSlots([]);
          setFetchFailed(true);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, idsKey, scope.paper_id, scope.revision_id]);

  // R4-M2：切换到别的断言时把面板内容滚回顶部。
  // 用户描述的场景是"点查看比较下面的证据，但面板内容一直停在上一条的位置"。
  useEffect(() => {
    listRef.current?.scrollTo({ top: 0 });
  }, [idsKey]);

  const empty = explainEmptyEvidence({
    hasIds: evidence_ids.length > 0,
    fetchFailed,
    claimsState,
  });

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

  // 桌面 rail 的偏移量（R4-M2）：要让出页头与底部叙事条，两者都是 sticky。
  // 取值来自 `paper/[slug]/page.tsx` 的实际结构：
  //   页头 ~104px（sticky top-0，含 view nav）+ 上下 padding ~40px；
  //   底部叙事条 ~57px（sticky bottom-0）。
  const RAIL_TOP_OFFSET = 120;
  const RAIL_MAX_HEIGHT = `calc(100vh - ${RAIL_TOP_OFFSET + 80}px)`;

  return (
    <>
      {/* 桌面 rail：**sticky 跟随滚动** + 面板内部滚动（R4-M2）
          `self-start` 解除 grid 的 stretch —— 否则高度被拉成左列行高，
          内容永远贴在超高盒子的顶部，页面往下滚就看不见了。 */}
      {open && (
        <aside
          data-testid="evidence-rail"
          style={{ top: RAIL_TOP_OFFSET, maxHeight: RAIL_MAX_HEIGHT }}
          className="hidden w-80 shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-slate-50 lg:sticky lg:block lg:self-start"
        >
          {header}
          <div ref={listRef} className="overflow-y-auto" style={{ maxHeight: `calc(${RAIL_MAX_HEIGHT} - 49px)` }}>
            <EvidenceContent
              slots={slots}
              loading={loading}
              emptyText={empty}
              onNavigate={onNavigate}
            />
          </div>
        </aside>
      )}

      {/* 移动抽屉：一行不动（R4-M2 只改 lg 以上） */}
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
              <EvidenceContent
                slots={slots}
                loading={loading}
                emptyText={empty}
                onNavigate={onNavigate}
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
