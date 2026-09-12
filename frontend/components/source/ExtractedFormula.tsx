'use client';

// 提取公式视图（§5.13）：KaTeX trust=false、禁危险宏。
// 渲染失败显示"可转原件"状态；原编号来自解析/人工标注，不自动编造。
//
// M3 修复：`media.extracted.latex` 存的是**带定界符**的原始串
// （实测 `$$ \operatorname{Attention}(Q,K,V)=…\tag{1} $$`），此前直接丢给 KaTeX，
// 于是用户在"原件媒体"里看到的是未渲染的 LaTeX 源码。现在统一交给 `lib/richtext.ts`
// 内核：先去定界符与 `\tag`（编号单独展示），再渲染；失败降级为可读文本。

import { Sigma } from 'lucide-react';
import type { Media } from '@/lib/contracts';
import { compactLatex, katexToHtml } from '@/lib/richtext';

export function ExtractedFormula({ media, onShowOriginal }: {
  media: Media;
  onShowOriginal: (mediaId: string) => void;
}) {
  const latex = media.extracted?.latex ?? '';
  const { body, tagNo } = compactLatex(latex);
  const label = media.extracted?.equation_label || media.original_label || (tagNo ? `(${tagNo})` : null);
  const html = katexToHtml(body, true);

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      {label && (
        <div className="mb-2 text-right font-mono text-xs text-slate-400">
          编号 · {label}
        </div>
      )}
      {html ? (
        <div
          className="overflow-x-auto text-center text-[15px] text-slate-900"
          // KaTeX trust=false 输出已禁用危险宏；正文文本由内核 escapeHtml
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-6 text-center">
          <Sigma className="h-8 w-8 text-slate-300" />
          {body ? (
            // 渲染失败但公式体可读：等宽展示（绝不显示 `$$` / `\tag` 定界符）
            <code className="max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded bg-slate-100 px-2 py-1 text-left font-mono text-[12px] text-slate-600">
              {body}
            </code>
          ) : (
            <p className="text-sm text-slate-500">公式渲染失败，可查看原件。</p>
          )}
          <button
            onClick={() => onShowOriginal(media.id)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-indigo-600 transition hover:bg-slate-50"
          >
            查看原件
          </button>
        </div>
      )}
    </div>
  );
}
