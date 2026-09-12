'use client';

// 公式/富文本渲染（REFACTOR_PLAN M2/M3）。
//
// 历史：这里曾自己实现"切分 $…$ / $$…$$ + 清 LaTeX + escapeHtml"，与表格、媒体介绍、
// 证据抽屉里的另外三份实现**行为不一致**，于是同一段 MinerU 文本在不同面板表现不同
// （实测：`<sup>∗</sup>` 在正文被转义成字面量、`$$…\tag{1}$$` 在媒体介绍里原样显示）。
//
// 现在它是 `lib/richtext.ts` 唯一内核的薄壳：解析 / 渲染 / 降级 / 安全全部在内核里，
// 本文件只负责套一层元素与类名。**不要在这里再加任何解析逻辑。**

import { useMemo } from 'react';
import { renderRichHtml, type Tone } from '@/lib/richtext';
import { cn } from '@/lib/cn';

export function MathText({
  text,
  className,
  tone = 'dark',
  blockMath = true,
}: {
  text?: string | null;
  className?: string;
  /** 深色阅读面板（默认）或浅色原件/表格卡片。 */
  tone?: Tone;
  blockMath?: boolean;
}) {
  const html = useMemo(() => {
    if (!text) return '';
    return renderRichHtml(text, { tone, blockMath }).html;
  }, [text, tone, blockMath]);

  if (!html) return null;
  return (
    <span
      className={cn('text-[13.5px] leading-relaxed', className)}
      // 内核输出：文本已 escapeHtml、行内标签走白名单、公式为 KaTeX（trust=false）
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
