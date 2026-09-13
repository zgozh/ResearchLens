'use client';

// 工作台数据加载：先取 manifest 得 revision，再并行取同 revision 的 exhibits。
// 任务完成后 refresh() 重新取 manifest，按新 revision 清理旧查询。
// 空 assertions 是已完成的空态；manifest 无可读 revision 时 exhibits 标 pending（并继续轮询）。
//
// R4-M7b：`refresh({ silent })` —— **后台轮询必须用 silent**。
// 旧实现每次开头都把 status 置 `'loading'`，而进度卡的可见性又绑了它 →
// 每个轮询 tick 必然走一遍「卡片出现 → 卡片消失」，用户看到的就是"一闪一闪"。

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ExhibitBundle, LoadState, LoadStateStatus, PaperId, PaperManifest } from '@/lib/contracts';
import { api, toDomainError } from '@/lib/api';
import { nextLoadStatus } from '@/lib/paperProgress';

export function usePaperWorkspace({ paper_id }: { paper_id: PaperId }): {
  manifest: LoadState<PaperManifest>;
  exhibits: LoadState<ExhibitBundle>;
  refresh: (opts?: { silent?: boolean }) => Promise<void>;
} {
  const [manifest, setManifest] = useState<LoadState<PaperManifest>>({
    status: 'idle',
    data: null,
    error: null,
  });
  const [exhibits, setExhibits] = useState<LoadState<ExhibitBundle>>({
    status: 'idle',
    data: null,
    error: null,
  });
  const seqRef = useRef(0);

  const refresh = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = !!opts?.silent;
    const seq = ++seqRef.current;
    // silent：保持当前 status（不清空、不闪）；非 silent：置 loading（首帧确实没数据）
    setManifest((s) => ({ ...s, status: nextLoadStatus(s.status, silent), error: null }));
    // R4-M7：不预设 `exhibits` 为 idle —— 那会让"还没解析出 revision"看起来像
    // "什么都没发生"（调用方拿不到信号 → 白屏）。
    setExhibits((s) => ({ ...s, status: nextLoadStatus(s.status, silent), error: null }));

    let m: PaperManifest;
    try {
      m = await api.getManifest(paper_id);
    } catch (e) {
      if (seq !== seqRef.current) return;
      setManifest({ status: 'error', data: null, error: toDomainError(e) });
      // manifest 都取不到时 exhibits 也标 error（不许停在 loading 转圈）
      setExhibits((s) => ({ ...s, status: 'error', error: toDomainError(e) }));
      return;
    }
    if (seq !== seqRef.current) return;
    setManifest({ status: 'ready', data: m, error: null });

    const rev = m.revision?.id;
    if (!rev) {
      // R4-M7 关键修复：以前这里是 `return`（exhibits 永远停在 idle、且不重试）。
      // 现在显式标 `pending`：调用方据此显示"正在解析"并**继续轮询**，
      // 而不是给用户一片空白。
      setExhibits({ status: 'pending', data: null, error: null });
      return;
    }

    if (!silent) setExhibits((s) => ({ ...s, status: 'loading' }));
    try {
      const e = await api.getExhibitBundle(paper_id, rev);
      if (seq !== seqRef.current) return;
      setExhibits({ status: 'ready', data: e, error: null });
    } catch (err) {
      if (seq !== seqRef.current) return;
      // silent 失败**保留旧数据**（后台刷新失败不该把用户正在看的内容清掉）
      if (silent && seq === seqRef.current) {
        setExhibits((s) => (s.data ? s : { ...s, status: 'error', error: toDomainError(err) }));
        return;
      }
      setExhibits({ status: 'error', data: null, error: toDomainError(err) });
    }
  }, [paper_id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { manifest, exhibits, refresh };
}
