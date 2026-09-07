'use client';

import { cn } from '@/lib/cn';

/** 渲染图：优先真实图（base64 PNG，来自真实论文），否则程序化 SVG。 */
export function FigureImage({ image_b64, glyph_svg, caption, className }: {
  image_b64?: string; glyph_svg?: string; caption?: string; className?: string;
}) {
  if (image_b64) {
    return (
      <img
        src={`data:image/png;base64,${image_b64}`}
        alt={caption || 'figure'}
        className={cn('h-auto w-full object-contain', className)}
        loading="lazy"
      />
    );
  }
  return <div className={cn('[&_svg]:w-full [&_svg]:h-auto', className)} dangerouslySetInnerHTML={{ __html: glyph_svg || '' }} />;
}
