'use client';

// NavigationTarget = scope + anchor_id + segment_index（§5.2）。
// navigate 设置目标并把 Promise 交给 PdfReader 渲染完成后的 onLocated 回填；
// 只有实际绘制完成才允许 region_highlighted（§6.16）。
// 额外暴露 reportLocated 作为 PdfReader.onLocated 的接线点（§5.13 最小输出 {target,navigate}）。

import { useCallback, useRef, useState } from 'react';
import type { NavigationResult, NavigationTarget, Scope } from '@/lib/contracts';

export function useEvidenceNavigation({ scope }: { scope: Scope }): {
  target: NavigationTarget | null;
  navigate: (target: NavigationTarget) => Promise<NavigationResult>;
  reportLocated: (result: NavigationResult) => void;
} {
  const [target, setTarget] = useState<NavigationTarget | null>(null);
  const pendingRef = useRef<((r: NavigationResult) => void) | null>(null);

  const navigate = useCallback(
    (t: NavigationTarget): Promise<NavigationResult> => {
      if (t.paper_id !== scope.paper_id || t.revision_id !== scope.revision_id) {
        return Promise.resolve({
          target: t,
          status: 'unavailable',
          reason: 'target scope mismatch',
        });
      }
      setTarget(t);
      return new Promise<NavigationResult>((resolve) => {
        pendingRef.current = resolve;
      });
    },
    [scope],
  );

  const reportLocated = useCallback((result: NavigationResult) => {
    pendingRef.current?.(result);
    pendingRef.current = null;
  }, []);

  return { target, navigate, reportLocated };
}
