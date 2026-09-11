'use client';

// 真实 PDF 阅读器（§5.13 / §6.16）：
// - 动态加载 react-pdf + 本地匹配 pdfjs worker 版本（不阻塞首页加载 PDF.js）
// - 邻页虚拟渲染（仅当前页 ± 1）
// - 响应新 target 的序列号，旧完成回调作废
// - 只有区域实际绘制完成后才报 region_highlighted；无区域报 page_opened

import { useCallback, useEffect, useRef, useState } from 'react';
import { FileWarning, Loader2 } from 'lucide-react';
import type {
  Anchor,
  NavigationResult,
  NavigationTarget,
  Scope,
} from '@/lib/contracts';
import { api } from '@/lib/api';
import { AnchorOverlay } from './AnchorOverlay';
import { PageSelector } from './PageSelector';

type ReactPdfModule = {
  Document: React.ComponentType<any>;
  Page: React.ComponentType<any>;
};

let pdfModulePromise: Promise<ReactPdfModule> | null = null;

function loadReactPdf(): Promise<ReactPdfModule> {
  if (!pdfModulePromise) {
    pdfModulePromise = (async () => {
      const rp = await import('react-pdf');
      // worker 由脚本从 node_modules/pdfjs-dist 同步到 public/（版本随依赖一致）。
      // 不用 `new URL(..., import.meta.url)`：那会让 webpack 把 worker 当资源交给 Terser，
      // 而 worker 是 ESM（含 import/export），生产构建会直接报
      // "'import', and 'export' cannot be used outside of module code"。
      rp.pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';
      return rp as unknown as ReactPdfModule;
    })();
  }
  return pdfModulePromise;
}

export function PdfReader({
  scope,
  document_url,
  initial_target,
  onLocated,
}: {
  scope: Scope;
  document_url: string;
  initial_target: NavigationTarget | null;
  onLocated: (result: NavigationResult) => void;
}) {
  const [rp, setRp] = useState<ReactPdfModule | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [pageDims, setPageDims] = useState<{ width: number; height: number } | null>(null);

  const seqRef = useRef(0);
  const targetRef = useRef<NavigationTarget | null>(null);
  const reportedRef = useRef(0);
  const onLocatedRef = useRef(onLocated);
  onLocatedRef.current = onLocated;

  // 动态加载 react-pdf
  useEffect(() => {
    let cancelled = false;
    loadReactPdf()
      .then((m) => {
        if (!cancelled) setRp(m);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 响应新 target：取 anchor → 定位页 → 渲染完成后报 onLocated
  useEffect(() => {
    if (!initial_target) {
      targetRef.current = null;
      setAnchor(null);
      return;
    }
    const seq = ++seqRef.current;
    targetRef.current = initial_target;

    api
      .getAnchor(scope.paper_id, initial_target.anchor_id, scope.revision_id)
      .then((a) => {
        if (seq !== seqRef.current) return; // 旧回调作废
        setAnchor(a);
        const seg = a.segments?.[initial_target.segment_index];
        setPageNumber(seg ? seg.pdf_page_index + 1 : 1);
      })
      .catch(() => {
        if (seq !== seqRef.current) return;
        setAnchor(null);
        onLocatedRef.current({
          target: initial_target,
          status: 'unavailable',
          reason: 'anchor not found',
        });
      });
  }, [initial_target, scope.paper_id, scope.revision_id]);

  const handleRenderSuccess = useCallback(
    (p: number) => () => {
      const target = targetRef.current;
      if (!target || p !== pageNumber) return;
      if (reportedRef.current === seqRef.current) return; // 同一 target 只报一次
      reportedRef.current = seqRef.current;
      const seg = anchor?.segments?.[target.segment_index];
      const hasRegion = !!seg && (seg.rect != null || (seg.quads ?? []).length > 0);
      onLocatedRef.current({
        target,
        status: hasRegion ? 'region_highlighted' : 'page_opened',
        reason: null,
      });
    },
    [anchor, pageNumber],
  );

  if (loadError) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-slate-200 bg-slate-50 p-8 text-slate-500">
        <FileWarning className="h-6 w-6" />
        <p className="text-sm">PDF 阅读器加载失败：{loadError}</p>
      </div>
    );
  }

  if (!rp) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-xl border border-slate-200 bg-slate-50 p-8 text-slate-400">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">正在加载 PDF 阅读器…</span>
      </div>
    );
  }

  const { Document, Page } = rp;
  const windowPages = [pageNumber - 1, pageNumber, pageNumber + 1].filter(
    (p) => p >= 1 && p <= numPages,
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">
          PDF 原件 · 共 {numPages} 页
        </span>
        {numPages > 0 && (
          <PageSelector page={pageNumber} pageCount={numPages} onSelect={setPageNumber} />
        )}
      </div>

      <div className="mx-auto max-w-full overflow-auto rounded-xl border border-slate-200 bg-slate-100 p-4">
        <Document
          file={document_url}
          onLoadSuccess={(doc: { numPages: number }) => setNumPages(doc.numPages)}
          loading={
            <div className="flex items-center gap-2 p-8 text-slate-400">
              <Loader2 className="h-5 w-5 animate-spin" /> 加载文档…
            </div>
          }
          error={
            <div className="p-8 text-slate-500">文档加载失败，请改用页面图片模式。</div>
          }
        >
          {windowPages.map((p) => (
            <div key={p} className={p === pageNumber ? '' : 'hidden'}>
              <div className="relative inline-block">
                <Page
                  pageNumber={p}
                  scale={1}
                  renderTextLayer={false}
                  renderAnnotationLayer={false}
                  onLoadSuccess={(page: { width: number; height: number }) => {
                    if (p === pageNumber) setPageDims({ width: page.width, height: page.height });
                  }}
                  onRenderSuccess={p === pageNumber ? handleRenderSuccess(p) : undefined}
                />
                {p === pageNumber && anchor && pageDims && (
                  <AnchorOverlay
                    anchor={anchor}
                    segment_index={targetRef.current?.segment_index ?? 0}
                    viewport_width={pageDims.width}
                    viewport_height={pageDims.height}
                  />
                )}
              </div>
            </div>
          ))}
        </Document>
      </div>
    </div>
  );
}
