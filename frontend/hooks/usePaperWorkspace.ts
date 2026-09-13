'use client';

// 工作台数据加载：先取 manifest 得 revision，再并行取同 revision 的 exhibits。
// 任务完成后 refresh() 重新取 manifest，按新 revision 清理旧查询。
// 空 assertions 是已完成的空态；manifest 无可读 revision 时 exhibits 保持 idle。

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ExhibitBundle, LoadState, PaperId, PaperManifest } from '@/lib/contracts';
import { api, toDomainError } from '@/lib/api';

export function usePaperWorkspace({ paper_id }: { paper_id: PaperId }): {
  manifest: LoadState<PaperManifest>;
  exhibits: LoadState<ExhibitBundle>;
  refresh: () => Promise<void>;
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

  const refresh = useCallback(async () => {
    const seq = ++seqRef.current;
    setManifest((s) => ({ ...s, status: 'loading', error: null }));
    // R4-M7：不预设 `exhibits` 为 idle —— 那会让"还没解析出 revision"看起来像
    // "什么都没发生"（调用方拿不到信号 → 白屏）。
    setExhibits((s) => ({ ...s, status: 'loading', error: null }));

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

    setExhibits((s) => ({ ...s, status: 'loading' }));
    try {
      const e = await api.getExhibitBundle(paper_id, rev);
      if (seq !== seqRef.current) return;
      setExhibits({ status: 'ready', data: e, error: null });
    } catch (err) {
      if (seq !== seqRef.current) return;
      setExhibits({ status: 'error', data: null, error: toDomainError(err) });
    }
  }, [paper_id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { manifest, exhibits, refresh };
}
