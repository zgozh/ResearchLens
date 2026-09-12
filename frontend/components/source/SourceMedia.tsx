'use client';

// 统一来源媒体组件（§5.13）：{media, assets, mode?, onOpen, onNavigate}。
// 依据 resolveMediaPolicy 决定展示层级，统一来源标签 + 加载/失败状态；
// 真实 source 缺原图绝不回退 synthetic；整页预览明确标"整页"。

import { useState } from 'react';
import { ExternalLink, ImageOff, Maximize2, MapPin } from 'lucide-react';
import type { Asset, Media, MediaViewMode, NavigationTarget } from '@/lib/contracts';
import { findAsset, resolveMediaPolicy } from '@/lib/sourcePolicy';
import { SourceBadge } from './SourceBadge';
import { ExtractedTable } from './ExtractedTable';
import { ExtractedFormula } from './ExtractedFormula';
import { MathText } from '@/components/MathText';
import { cn } from '@/lib/cn';
import { absoluteApiUrl } from '@/lib/api';

type ImgState = 'loading' | 'ready' | 'failed';

export function SourceMedia({
  media,
  assets,
  mode,
  onOpen,
  onNavigate,
}: {
  media: Media;
  assets: Asset[];
  mode?: 'original' | 'extracted';
  onOpen: (mediaId: string) => void;
  onNavigate: (target: NavigationTarget) => void;
}) {
  const policy = resolveMediaPolicy(media, assets);
  const [imgState, setImgState] = useState<ImgState>('loading');

  const originalAsset = policy.original_asset_ids
    .map((id) => findAsset(assets, id))
    .find((a): a is Asset => !!a);
  const pagePreviewAsset = assets.find((a) => a.kind === 'page_preview');
  const isPageFallback =
    policy.default_mode === 'original' && !originalAsset && !!pagePreviewAsset;

  const effectiveMode: MediaViewMode =
    mode === 'extracted' && (media.extracted?.table_html || media.extracted?.latex)
      ? 'extracted'
      : policy.default_mode;

  const displayAsset = originalAsset ?? (isPageFallback ? pagePreviewAsset : undefined);
  const badgeMode: MediaViewMode =
    effectiveMode === 'original' && isPageFallback ? 'original' : effectiveMode;
  const label = isPageFallback ? '整页预览' : policy.label;

  const navigateToFirstAnchor = () => {
    const anchorId = media.anchor_ids[0];
    if (!anchorId) return;
    onNavigate({
      paper_id: media.paper_id,
      revision_id: media.revision_id,
      anchor_id: anchorId,
      segment_index: 0,
    });
  };

  return (
    <figure className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <figcaption className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
        <SourceBadge mode={badgeMode} label={label} />
        {media.original_label && (
          <span className="font-mono text-xs text-slate-500">{media.original_label}</span>
        )}
        <span className="ml-auto flex items-center gap-1">
          {media.anchor_ids.length > 0 && (
            <button
              onClick={navigateToFirstAnchor}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
            >
              <MapPin className="h-3 w-3" /> 定位
            </button>
          )}
          <button
            onClick={() => onOpen(media.id)}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-indigo-600 transition hover:bg-indigo-50"
          >
            <Maximize2 className="h-3 w-3" /> 打开
          </button>
        </span>
      </figcaption>

      <div className="p-3">
        {effectiveMode === 'extracted' ? (
          media.kind === 'equation' ? (
            <ExtractedFormula media={media} onShowOriginal={onOpen} />
          ) : (
            <ExtractedTable media={media} onShowOriginal={onOpen} />
          )
        ) : displayAsset ? (
          <button
            onClick={() => onOpen(media.id)}
            className="relative block w-full overflow-hidden rounded-lg bg-slate-50"
            title={isPageFallback ? '整页预览' : media.caption}
          >
            {imgState === 'failed' ? (
              <span className="flex items-center justify-center gap-2 p-8 text-sm text-slate-400">
                <ImageOff className="h-4 w-4" /> 原件加载失败
              </span>
            ) : (
              <img
                src={absoluteApiUrl(displayAsset.url)}
                alt={media.caption || media.original_label || 'media'}
                className="h-auto w-full object-contain"
                loading="lazy"
                onLoad={() => setImgState('ready')}
                onError={() => setImgState('failed')}
              />
            )}
            {imgState === 'loading' && (
              <span className="absolute inset-0 grid place-items-center text-xs text-slate-400">
                加载中…
              </span>
            )}
            {isPageFallback && imgState === 'ready' && (
              <span className="absolute right-2 top-2 rounded bg-slate-900/70 px-1.5 py-0.5 text-[10px] text-white">
                整页
              </span>
            )}
          </button>
        ) : (
          <div className="flex items-center justify-center gap-2 rounded-lg border border-dashed border-slate-200 p-8 text-sm text-slate-400">
            <ExternalLink className="h-4 w-4" />
            {policy.warnings[0]?.message ?? '该媒体无可展示资产'}
          </div>
        )}
      </div>

      {media.caption && (
        // 题注同样夹 LaTeX/`<sup>`（实测用户看到的 `$$…\tag{1}$$` 就在这里）：
        // 与正文、表格共用同一内核渲染，浅色底用 tone="light"
        <div className="px-3 pb-3">
          <MathText text={media.caption} tone="light" className={cn('block text-xs leading-relaxed text-slate-500')} />
        </div>
      )}
    </figure>
  );
}
