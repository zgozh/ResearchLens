'use client';

// 长文排版（ADR-0049）。
//
// 为什么需要：`sections[].body` 是**章节原文全文**（实测最长 6647 字）、
// `pages[].text` 是整页原文，此前整段塞进一个 <p>：没有段落间距、没有行宽限制，
// 一大坨挤在一起，读者无法定位。这里统一处理：
//   ① 按换行切段，逐段渲染（段间留白）；切段是**数学感知**的（splitParagraphs），
//      不会把跨行块级公式 `$$\n…\n$$` 拦腰截断（截断后永远配不成公式，就是"乱码"）；
//   ② 每段过 MathText（KaTeX + 转义清理）；
//   ③ 长文默认折叠（可给出高度阈值），点"展开全文"再展开——避免首屏被一大段塞满。

import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { MathText } from '@/components/MathText';
import { splitParagraphs } from '@/lib/richtext';
import { cn } from '@/lib/cn';

export function LongText({
  text,
  className,
  paragraphClassName,
  collapsible = false,
  collapsedHeight = 280,
  clampLines,
}: {
  text?: string | null;
  className?: string;
  paragraphClassName?: string;
  /** true 时长文默认折叠，给出"展开全文/收起"开关。 */
  collapsible?: boolean;
  /** 折叠时的高度阈值（px）。 */
  collapsedHeight?: number;
  /** 用 CSS 行数截断代替高度折叠（卡片场景更稳）。 */
  clampLines?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const paragraphs = useMemo(() => splitParagraphs(text || ''), [text]);

  if (paragraphs.length === 0) return null;

  const useClamp = typeof clampLines === 'number' && !expanded;
  const canCollapse = collapsible && paragraphs.length > 0;

  return (
    <div className={className}>
      <div
        className={cn('space-y-3', useClamp && 'overflow-hidden')}
        style={
          useClamp
            ? { display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: clampLines }
            : collapsible && !expanded
              ? { maxHeight: collapsedHeight, overflow: 'hidden' }
              : undefined
        }
      >
        {paragraphs.map((p, i) => (
          <MathText key={i} text={p} className={cn('block', paragraphClassName)} />
        ))}
      </div>
      {canCollapse && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-[var(--line)] bg-white/[0.03] px-2.5 py-1 text-[12px] font-medium text-slate-300 transition hover:border-white/25 hover:text-white"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? '收起' : `展开全文（${(text || '').length} 字）`}
        </button>
      )}
    </div>
  );
}
