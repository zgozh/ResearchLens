'use client';

// 同页坐标覆盖层（§5.13）：{anchor, segment_index, viewport_width, viewport_height}。
// 归一化 0..1 坐标乘 viewport；无区域（rect=null 且 quads=[]）时不画假框。

import type { Anchor, Rect } from '@/lib/contracts';

export function AnchorOverlay({
  anchor,
  segment_index,
  viewport_width,
  viewport_height,
}: {
  anchor: Anchor;
  segment_index: number;
  viewport_width: number;
  viewport_height: number;
}) {
  const segment = anchor?.segments?.[segment_index];
  if (!segment || !viewport_width || !viewport_height) return null;

  const rect = segment.rect;
  const quads = segment.quads ?? [];
  const hasRegion = rect != null || quads.length > 0;
  if (!hasRegion) return null; // 无区域不画假框

  if (rect) {
    const box = toPixelRect(rect, viewport_width, viewport_height);
    return (
      <div
        className="pointer-events-none absolute"
        style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
      >
        <div className="absolute inset-0 rounded-[2px] border-2 border-indigo-500/80 bg-indigo-400/15" />
      </div>
    );
  }

  const points = quads
    .map((quad) =>
      quad
        .map(([x, y]) => `${x * viewport_width},${y * viewport_height}`)
        .join(' '),
    );
  return (
    <svg
      className="pointer-events-none absolute inset-0"
      width={viewport_width}
      height={viewport_height}
      style={{ left: 0, top: 0 }}
    >
      {points.map((p, i) => (
        <polygon
          key={i}
          points={p}
          fill="rgba(99,102,241,0.15)"
          stroke="rgba(99,102,241,0.85)"
          strokeWidth={2}
        />
      ))}
    </svg>
  );
}

function toPixelRect(
  rect: Rect,
  width: number,
  height: number,
): { x: number; y: number; w: number; h: number } {
  const x0 = Math.min(rect[0], rect[2]);
  const x1 = Math.max(rect[0], rect[2]);
  const y0 = Math.min(rect[1], rect[3]);
  const y1 = Math.max(rect[1], rect[3]);
  return {
    x: x0 * width,
    y: y0 * height,
    w: (x1 - x0) * width,
    h: (y1 - y0) * height,
  };
}
