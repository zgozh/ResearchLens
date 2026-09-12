'use client';

import type { TableOut } from '@/lib/types';
import { cn } from '@/lib/cn';
import { renderMathInHtml } from '@/lib/mathHtml';
import { renderRichHtml } from '@/lib/richtext';

/** 安全地渲染原始表格：优先展示 MinerU 原始 HTML 表（保留原格式/合并单元格/公式），
 *  仅当无 table_html 时才回退到 content 矩阵。已做基础消毒（去 script/on* 事件）。 */
function sanitizeTableHtml(html: string): string {
  if (!html) return '';
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
    .replace(/javascript:/gi, '');
}

export function TableRender({ table, className }: { table: TableOut; className?: string }) {
  // 表格 HTML 里夹着 LaTeX（实测 `$1.0 \cdot 10^{20}$`）：先消毒，再就地渲染成公式
  const html = renderMathInHtml(sanitizeTableHtml(table.table_html || ''));
  if (html) {
    return (
      <div
        className={cn('overflow-x-auto', className)}
        // 原始表 HTML 由 MinerU 生成（<table>/<tr>/<td>），已做基础消毒
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }
  // 回退：矩阵
  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-white/[0.04]">
            {(table.content[0] || []).map((h, i) => (
              <th key={i} className="border-b border-[var(--line)] px-2.5 py-1.5 font-medium text-slate-200">
                <span dangerouslySetInnerHTML={{ __html: renderRichHtml(String(h ?? '')).html }} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.content.slice(1).map((row, ri) => (
            <tr key={ri} className="border-b border-[var(--line)]">
              {row.map((cell, ci) => (
                <td key={ci} className="px-2.5 py-1.5 text-slate-300">
                  {/* 矩阵回退路径里的单元格同样可能夹 LaTeX：与正文/表格共用同一内核 */}
                  <span dangerouslySetInnerHTML={{ __html: renderRichHtml(String(cell ?? '')).html }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
