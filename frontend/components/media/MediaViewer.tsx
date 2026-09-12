'use client';

// 媒体查看器：旋转（90° 步进）/ 缩放 / 复位（REFACTOR_PLAN M4）。
//
// 用户实测："很多图方向反了，要求点击图片展示时加旋转按钮。"
// 设计要点：
// - 旋转是**视图层状态**（CSS transform），不改资产、不上传；组件卸载即复位；
// - 旋转 90/270 度时 `object-contain` 仍按原方向计算，因此给容器留出可滚动空间，
//   避免"转过之后图被裁掉"；
// - 工具栏浮在右上角，不占布局；`tone` 决定深色/浅色底色（论文阅读 vs 原件卡片）。

import { useState, type ReactNode } from 'react';
import { RotateCcw, RotateCw, ZoomIn, ZoomOut, Undo2 } from 'lucide-react';
import { clampZoom, nextRotation, transformStyle } from '@/lib/mediaView';
import { cn } from '@/lib/cn';

export function MediaViewer({
  children,
  className,
  tone = 'dark',
  rotatable = true,
  label,
}: {
  /** 被查看的内容（`<img>` / FigureImage / 任意媒体节点）。 */
  children: ReactNode;
  className?: string;
  tone?: 'dark' | 'light';
  /** 是否允许旋转（默认允许）。 */
  rotatable?: boolean;
  label?: string;
}) {
  const [rotation, setRotation] = useState(0);
  const [zoom, setZoom] = useState(1);

  const btn =
    tone === 'light'
      ? 'border-slate-200 bg-white/90 text-slate-600 hover:text-slate-900 hover:bg-white'
      : 'border-white/10 bg-black/40 text-slate-300 hover:text-white hover:bg-black/60';

  return (
    <div className={cn('relative', className)}>
      <div className="absolute right-2 top-2 z-10 flex items-center gap-1">
        {rotatable && (
          <>
            <button
              type="button"
              title="向左旋转 90°"
              aria-label="向左旋转 90°"
              onClick={() => setRotation((r) => nextRotation(r, -90))}
              className={cn('grid h-7 w-7 place-items-center rounded-md border backdrop-blur transition', btn)}
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="向右旋转 90°"
              aria-label="向右旋转 90°"
              onClick={() => setRotation((r) => nextRotation(r, 90))}
              className={cn('grid h-7 w-7 place-items-center rounded-md border backdrop-blur transition', btn)}
            >
              <RotateCw className="h-3.5 w-3.5" />
            </button>
          </>
        )}
        <button
          type="button"
          title="放大"
          aria-label="放大"
          onClick={() => setZoom((z) => clampZoom(z * 1.25))}
          className={cn('grid h-7 w-7 place-items-center rounded-md border backdrop-blur transition', btn)}
        >
          <ZoomIn className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          title="缩小"
          aria-label="缩小"
          onClick={() => setZoom((z) => clampZoom(z / 1.25))}
          className={cn('grid h-7 w-7 place-items-center rounded-md border backdrop-blur transition', btn)}
        >
          <ZoomOut className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          title="复位（方向 + 缩放）"
          aria-label="复位（方向 + 缩放）"
          onClick={() => {
            setRotation(0);
            setZoom(1);
          }}
          className={cn('grid h-7 w-7 place-items-center rounded-md border backdrop-blur transition', btn)}
        >
          <Undo2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {(rotation !== 0 || zoom !== 1) && (
        <div
          className={cn(
            'absolute left-2 top-2 z-10 rounded-md px-1.5 py-0.5 font-mono text-[10px] backdrop-blur',
            tone === 'light' ? 'bg-white/85 text-slate-500' : 'bg-black/40 text-slate-400',
          )}
        >
          {rotation !== 0 ? `${rotation}° ` : ''}
          {zoom !== 1 ? `${Math.round(zoom * 100)}%` : ''}
        </div>
      )}

      {/* 旋转后宽高互换，用 overflow-auto 兜住：宁可滚动，不裁掉内容 */}
      <div className="grid max-h-[70vh] place-items-center overflow-auto">
        <div style={transformStyle(rotation, zoom)} className="transition-transform">
          {children}
        </div>
      </div>
      {label && (
        <div className={cn('mt-1 text-center font-mono text-[10px]', tone === 'light' ? 'text-slate-400' : 'text-slate-500')}>
          {label}
        </div>
      )}
    </div>
  );
}
