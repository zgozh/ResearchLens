'use client';

import type { ReactNode } from 'react';
import { renderRichHtml } from '@/lib/richtext';
import { cn } from '@/lib/cn';

type RefItem = { type: 'figure'; figure: any } | { type: 'table'; table: any };
type Opts = { figures?: any[]; tables?: any[]; onOpenMedia?: (item: RefItem) => void };

/**
 * 段落内的普通文本一律过**唯一渲染内核**（M2/M3）：
 * 这样方法步骤、问答回答里的 `$…$`、`<sup>∗</sup>` 与正文/表格表现完全一致。
 * 不要在这里自己写公式或转义逻辑。
 */
function RichSpan({ text, className }: { text: string; className?: string }) {
  const html = renderRichHtml(text).html;
  if (!html) return null;
  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}

/** 内联渲染：**bold**、`code` 以及 "图N"/"表N" 引用（若提供 figures/tables + onOpenMedia）。 */
function renderInline(text: string, opts: Opts, keyBase: number): ReactNode[] {
  const { figures = [], tables = [], onOpenMedia } = opts;
  const re = /(\*\*[^*]+\*\*|`[^`]+`|(?:如)?(?:图|表)\s*(\d+)(?:所示)?)/g;
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(<RichSpan key={`${keyBase}-t${i}`} text={text.slice(last, m.index)} />);
    const tok = m[0];
    if (tok.startsWith('**')) {
      out.push(
        <strong key={`${keyBase}-b${i}`} className="font-semibold text-slate-100">
          {tok.slice(2, -2)}
        </strong>,
      );
    } else if (tok.startsWith('`')) {
      out.push(
        <code
          key={`${keyBase}-c${i}`}
          className="rounded bg-white/[0.06] px-1.5 py-0.5 font-mono text-[0.9em] text-indigo-200"
        >
          {tok.slice(1, -1)}
        </code>,
      );
    } else {
      const num = parseInt(m[2]!, 10);
      const fig = figures.find((f) => f.fig_no === num);
      const tbl = tables.find((t) => t.table_no === num);
      const refItem: RefItem | null = fig ? { type: 'figure', figure: fig } : tbl ? { type: 'table', table: tbl } : null;
      if (onOpenMedia && refItem) {
        out.push(
          <button
            key={`${keyBase}-r${i}`}
            onClick={(e) => {
              e.stopPropagation();
              onOpenMedia(refItem);
            }}
            className="inline-flex items-baseline gap-0.5 rounded-md bg-white/[0.06] px-1.5 py-0.5 font-medium text-indigo-300 underline decoration-indigo-400/50 underline-offset-2 transition hover:bg-indigo-500/20 hover:text-indigo-200"
            title={fig ? fig.caption || `图 ${num}` : tbl ? tbl.caption || `表 ${num}` : undefined}
          >
            {tok.replace(/^如图/, '图').replace(/^如表/, '表')}
            <span className="text-[10px] text-indigo-400/70">↗</span>
          </button>,
        );
      } else {
        out.push(<RichSpan key={`${keyBase}-p${i}`} text={tok} className="text-slate-300" />);
      }
    }
    last = m.index + tok.length;
    i += 1;
  }
  if (last < text.length) out.push(<RichSpan key={`${keyBase}-tail`} text={text.slice(last)} />);
  return out;
}

/** 把「【证据 p.X / claim_YY】」「【基于论文的推断：…】」渲染为彩色 chip。 */
function renderText(text: string, opts: Opts, keyBase: number): ReactNode[] {
  const parts = text.split(/(【[^】]+】)/g);
  const out: ReactNode[] = [];
  parts.forEach((p, i) => {
    if (p.startsWith('【') && p.endsWith('】')) {
      const inner = p.slice(1, -1);
      const isEv = inner.startsWith('证据');
      const isInf = inner.startsWith('基于论文的推断');
      const tone = isEv
        ? 'border-indigo-400/40 bg-indigo-500/15 text-indigo-200'
        : isInf
          ? 'border-amber-400/40 bg-amber-500/15 text-amber-200'
          : 'border-slate-500/40 bg-white/[0.05] text-slate-300';
      out.push(
        <span
          key={`${keyBase}-m${i}`}
          className={cn('mx-0.5 inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 align-baseline text-[0.9em] font-medium', tone)}
        >
          {inner}
        </span>,
      );
    } else {
      out.push(...renderInline(p, opts, keyBase));
    }
  });
  return out;
}

function renderRich(text: string, opts: Opts, keyBase: number): ReactNode {
  return (
    <>
      {renderText(text, opts, keyBase)}
    </>
  );
}

/**
 * 轻量富文本渲染器：标题 / 编号列表 / 无序列表 / 段落、`**bold**`、`code`、
 * "图N/表N" 引用（可点击打开）、「【…】」证据/推断标记。
 */
export function RichText({ text, figures, tables, onOpenMedia, className }: {
  text: string;
  figures?: any[];
  tables?: any[];
  onOpenMedia?: (item: RefItem) => void;
  className?: string;
}) {
  const opts: Opts = { figures, tables, onOpenMedia };
  const out: ReactNode[] = [];
  let listBuf: ReactNode[] = [];
  let key = 0;

  const flush = () => {
    if (listBuf.length) {
      out.push(
        <ul key={`ul${key++}`} className="my-2 space-y-1.5">
          {listBuf}
        </ul>,
      );
      listBuf = [];
    }
  };

  const lines = text.split(/\n/);
  for (const raw of lines) {
    const line = raw.replace(/[ \t]+$/g, '');
    if (line.trim() === '') {
      flush();
      continue;
    }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      flush();
      const lvl = h[1]!.length;
      const cls =
        lvl === 1
          ? 'mt-3 mb-1.5 text-lg font-semibold text-white'
          : lvl === 2
            ? 'mt-3 mb-1 text-base font-semibold text-slate-100'
            : 'mt-2.5 mb-1 text-sm font-semibold text-slate-200';
      out.push(
        <div key={`h${key++}`} className={cls}>
          {renderRich(h[2]!.trim(), opts, key)}
        </div>,
      );
      continue;
    }
    const num = line.match(/^\s*(\d+)[.、)]\s+(.*)$/);
    const bul = line.match(/^\s*[-*•]\s+(.*)$/);
    if (num || bul) {
      const content = (num ? num[2]! : bul![1]!).trim();
      listBuf.push(
        <li key={`li${key++}`} className="flex items-start gap-2 text-[13.5px] leading-relaxed text-slate-300">
          <span className="mt-0.5 shrink-0 font-mono text-[11px] text-indigo-300/80">
            {num ? num[1] : '•'}
          </span>
          <span className="min-w-0">{renderRich(content, opts, key)}</span>
        </li>,
      );
      continue;
    }
    flush();
    out.push(
      <p key={`p${key++}`} className="my-1.5 text-[13.5px] leading-relaxed text-slate-300">
        {renderRich(line.trim(), opts, key)}
      </p>,
    );
  }
  flush();

  return <div className={cn('space-y-1 text-slate-300', className)}>{out}</div>;
}
