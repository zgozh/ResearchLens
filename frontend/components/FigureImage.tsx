'use client';

import { cn } from '@/lib/cn';
import { absoluteApiUrl } from '@/lib/api';

/**
 * 渲染图，按优先级取来源：
 * 1. `image_url` —— canonical 真实图资产（`/api/assets/{id}`，D-24 落库的 crop 图）；
 * 2. `image_b64` —— 旧的内联 base64（demo/历史数据）；
 * 3. `glyph_svg`  —— 程序化 SVG（demo 自绘）。
 *
 * 为什么加 `image_url`（ADR-0027）：canonical 侧不再内联图片字节，图都在 asset 里；
 * 而这里此前只认内联 b64/svg，于是真实论文的图全部渲染空白——"有摘要没图"。
 */
export function FigureImage({ image_url, image_b64, glyph_svg, caption, className }: {
  image_url?: string; image_b64?: string; glyph_svg?: string; caption?: string; className?: string;
}) {
  const classNames = cn('h-auto w-full object-contain', className);
  const url = absoluteApiUrl(image_url);
  if (url) {
    return <img src={url} alt={caption || 'figure'} className={classNames} loading="lazy" />;
  }
  if (image_b64) {
    return (
      <img
        src={`data:image/png;base64,${image_b64}`}
        alt={caption || 'figure'}
        className={classNames}
        loading="lazy"
      />
    );
  }
  return <div className={cn('[&_svg]:w-full [&_svg]:h-auto', className)} dangerouslySetInnerHTML={{ __html: glyph_svg || '' }} />;
}
