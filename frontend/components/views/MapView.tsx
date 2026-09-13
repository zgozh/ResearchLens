'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, FileText, Table2, Image as ImageIcon, Expand } from 'lucide-react';
import type { ReactNode } from 'react';
import type { PaperDetail, SectionOut } from '@/lib/types';
import { Badge, GlassCard, Kicker } from '@/components/ui';
import { absoluteApiUrl } from '@/lib/api';
import { MediaModal, type MediaItem } from '@/components/MediaModal';
import { FigureImage } from '@/components/FigureImage';
import { TableRender } from '@/components/TableRender';
import { cn } from '@/lib/cn';
import { MathText } from '@/components/MathText';
import { LongText } from '@/components/LongText';

const KIND_LABEL: Record<string, string> = {
  intro: '引言', problem: '问题与背景', method: '方法', experiment: '实验',
  result: '结果', limitation: '局限', discussion: '讨论与局限',
  conclusion: '结论', references: '参考文献', body: '正文',
};
const TONE: Record<string, 'accent'|'cyan'|'emerald'|'amber'|'rose'|'violet'|'slate'> = {
  intro: 'violet', problem: 'rose', method: 'accent', experiment: 'cyan',
  result: 'emerald', limitation: 'amber', discussion: 'rose',
  conclusion: 'slate', body: 'slate',
};

export function MapView({ detail, accent, onOpenSection }: {
  detail: PaperDetail; accent: string; onOpenSection?: (s: SectionOut) => void;
}) {
  const map = detail.map_summary || {};
  // D29：只渲染**后端真的产出了内容**的卡片。
  // 旧行为是六张卡片全渲染、缺的显示 "—"，实测 paper 2 有 5/6 是 "—"、
  // paper 3 有 4/6 是 "—"，整页看起来就是"乱的内容都不齐"。
  const boxes = [
    { key: 'problem', label: '问题', c: '#F43F5E' },
    { key: 'method', label: '方法', c: '#6366F1' },
    { key: 'dataset', label: '数据集', c: '#22D3EE' },
    { key: 'experiment', label: '实验', c: '#38BDF8' },
    { key: 'result', label: '结果', c: '#34D399' },
    { key: 'limitation', label: '局限', c: '#F59E0B' },
  ].filter((b) => (map[b.key] || '').trim().length > 0);
  const [openSec, setOpenSec] = useState<number | undefined>(0);
  const [media, setMedia] = useState<MediaItem | null>(null);

  return (
    <div className="space-y-6">
      {/* 摘要 + 元信息 */}
      <GlassCard className="p-6">
        <Kicker>摘要 · ABSTRACT</Kicker>
        <MathText text={detail.abstract} className="mt-3 block text-[15px] leading-relaxed text-slate-300" />
        <div className="mt-4 flex flex-wrap gap-2">
          {(detail.tags || []).map((t) => <Badge key={t} tone="slate">{t}</Badge>)}
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-[var(--line)] pt-4 font-mono text-[11px] text-slate-500">
          {(detail.authors?.length ?? 0) > 0 && <span>作者 · {detail.authors.join(', ')}</span>}
          <span>年份 · {detail.year}</span>
          <span>领域 · {detail.domain}</span>
          <span>图表 · {detail.figures?.length ?? 0} 图 / {detail.tables?.length ?? 0} 表 · 章节 {detail.sections?.length} 个</span>
          {detail.pdf_url && (
            // `pdf_url` 现在给的是**可访问地址**：网址导入的是官网 URL，上传件是本站文档接口
            // （`/api/papers/{id}/document`）。后者必须补成绝对地址，否则会拼到前端域名上
            // （用户实测点开 404）。见 ADR-0069。
            <a href={absoluteApiUrl(detail.pdf_url)} target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-1 text-indigo-300 hover:text-indigo-200">
              <ImageIcon className="h-3.5 w-3.5" /> 查看论文原文 ↗
            </a>
          )}
        </div>
      </GlassCard>

      {/* 六维卡片 */}
      <div>
        <Kicker className="mb-3">论文地图 · PAPER MAP</Kicker>
        {boxes.length === 0 ? (
          <GlassCard className="p-5 text-sm text-slate-500">
            本篇论文尚未生成可追溯的论文地图（需要已通过证据校验的断言）。
          </GlassCard>
        ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {boxes.map((b, i) => (
            <motion.div key={b.key} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
              <GlassCard className="h-full p-5" style={{ borderTopColor: b.c, borderTopWidth: 2 }}>
                <div className="flex items-center gap-2.5">
                  <span className="h-2 w-2 rounded-full" style={{ background: b.c }} />
                  <span className="font-mono text-[11px] uppercase tracking-[0.2em]" style={{ color: b.c }}>{b.label}</span>
                </div>
                <LongText
                  text={map[b.key]}
                  className="mt-3"
                  paragraphClassName="text-sm leading-relaxed text-slate-300"
                  collapsible
                  collapsedHeight={140}
                />
              </GlassCard>
            </motion.div>
          ))}
        </div>
        )}
      </div>

      {/* 章节结构树 */}
      <div>
        <Kicker className="mb-3">章节结构 · STRUCTURE</Kicker>
        <GlassCard className="divide-y divide-[var(--line)] overflow-hidden">
          {(detail.sections || []).map((s, i) => {
            const open = openSec === i;
            return (
              <div key={s.heading}>
                <button onClick={() => setOpenSec(open ? undefined : i)}
                  className="group flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-white/[0.03]">
                  <span className="grid h-7 w-7 place-items-center rounded-lg bg-white/[0.04] font-mono text-[11px] text-slate-400">{s.page_end && s.page_end !== s.page_start ? `${s.page_start}–${s.page_end}` : s.page}</span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-slate-100">{s.heading}</div>
                    <LongText
                      text={s.summary}
                      className="mt-0.5"
                      paragraphClassName="line-clamp-2 text-[12px] text-slate-500"
                    />
                  </div>
                  <Badge tone={TONE[s.kind] || 'slate'}>{KIND_LABEL[s.kind] || s.kind}</Badge>
                  <ChevronDown className={cn('h-4 w-4 text-slate-500 transition-transform', open && 'rotate-180')} />
                </button>
                <AnimateSection open={open}>
                  <div className="space-y-3 px-5 pb-4 pl-14">
                    {open && (
                      <>
                        {/* 章节正文 = 该节原文全文（实测最长 6647 字）→ 必须切段 + 默认折叠，
                            否则展开后是一大坨没有段落间距的文字（用户反馈"挤在一起很乱"）。 */}
                        <LongText
                          text={s.body}
                          paragraphClassName="text-[13px] leading-7 text-slate-300"
                          collapsible
                          collapsedHeight={260}
                        />
                        {(s.key_points?.length ?? 0) > 0 && (
                          <ul className="space-y-1">
                            {s.key_points.map((kp, j) => (
                              <li key={j} className="flex items-start gap-2 text-[12px] text-slate-400">
                                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: accent }} />
                                {kp}
                              </li>
                            ))}
                          </ul>
                        )}
                        <button onClick={() => onOpenSection?.(s)}
                          className="inline-flex items-center gap-1.5 text-[12px] font-medium text-indigo-300 hover:text-indigo-200">
                          <FileText className="h-3.5 w-3.5" /> 阅读该章节正文
                        </button>
                      </>
                    )}
                  </div>
                </AnimateSection>
              </div>
            );
          })}
        </GlassCard>
      </div>

      {/* 关键图表（可点击放大） */}
      <div>
        <Kicker className="mb-3">关键图表 · FIGURES &amp; TABLES</Kicker>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {detail.figures.map((f) => (
            <GlassCard key={`f${f.fig_no}`} onClick={() => setMedia({ type: 'figure', figure: f })}
              className="group cursor-pointer p-3 transition-all hover:border-white/20">
              <div className="mb-2 flex items-center gap-2">
                <ImageIcon className="h-3.5 w-3.5 text-slate-500" />
                <span className="text-xs font-semibold text-slate-200">图 {f.fig_no}</span>
                <span className="ml-auto flex items-center gap-1 font-mono text-[10px] text-slate-500">
                  p.{f.page}
                  <span className="inline-flex items-center gap-0.5 rounded-md bg-white/[0.04] px-1 py-0.5 text-slate-500 transition group-hover:text-indigo-300"><Expand className="h-3 w-3" /></span>
                </span>
              </div>
              <div className="overflow-hidden rounded-md border border-[var(--line)] bg-[#0F172A]">
                <FigureImage image_url={f.image_url} image_b64={f.image_b64} glyph_svg={f.glyph_svg} caption={f.caption} />
              </div>
              <MathText text={f.caption} className="mt-2 line-clamp-2 block text-[11px] text-slate-500" />
            </GlassCard>
          ))}
        </div>

        {detail.tables.length > 0 && (
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {detail.tables.map((t) => (
              <GlassCard key={`t${t.table_no}`} onClick={() => setMedia({ type: 'table', table: t })}
                className="group cursor-pointer p-4 transition-all hover:border-white/20">
                <div className="mb-2 flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                    <Table2 className="h-3.5 w-3.5 text-slate-500" /> 表 {t.table_no}
                  </span>
                  <span className="flex items-center gap-1 font-mono text-[10px] text-slate-500">
                    p.{t.page}
                    <span className="inline-flex items-center gap-0.5 rounded-md bg-white/[0.04] px-1 py-0.5 text-slate-500 transition group-hover:text-indigo-300"><Expand className="h-3 w-3" /></span>
                  </span>
                </div>
                <MathText text={t.caption} className="mb-2 block text-[11px] text-slate-500" />
                <div className="overflow-hidden rounded-md border border-[var(--line)]">
                  <TableRender table={t} className="text-[11px]" />
                </div>
                {t.key_finding && <p className="mt-2 line-clamp-2 text-[11px] text-emerald-200/80">{t.key_finding}</p>}
              </GlassCard>
            ))}
          </div>
        )}
      </div>

      <MediaModal item={media} accent={accent} onClose={() => setMedia(null)} />
    </div>
  );
}

function AnimateSection({ open, children }: { open: boolean; children: ReactNode }) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25 }} className="overflow-hidden">
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
