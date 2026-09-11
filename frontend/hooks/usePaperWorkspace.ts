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
    setExhibits({ status: 'idle', data: null, error: null });

    let m: PaperManifest;
    try {
      m = await api.getManifest(paper_id);
    } catch (e) {
      if (seq !== seqRef.current) return;
      setManifest({ status: 'error', data: null, error: toDomainError(e) });
      return;
    }
    if (seq !== seqRef.current) return;
    setManifest({ status: 'ready', data: m, error: null });

    const rev = m.revision?.id;
    if (!rev) return; // 暂无可读 revision

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
