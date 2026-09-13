'use client';

// 论文阅读视图（§3.4 视图政策 / §5.13 / §6.16）。
//
// D05 修复：默认模式是**原件 PDF**（PdfReader 渲染真实 document_url），
//           「结构化导读」「全文原文」是次级解读层，不再自称原件。
// D06 修复：图/表/公式改用 SourceMedia，来源徽标由 resolveMediaPolicy 决定。
// D12 修复：跳转目标是 NavigationTarget(anchor_id, segment_index)，不再是章节 kind。
// D13 修复：只有 onLocated 返回 region_highlighted 才说"已在原文第 N 页高亮"。

import { useEffect, useMemo, useRef, useState } from 'react';
import { BookOpen, ScrollText, FileText, FileDown } from 'lucide-react';
import type { PaperDetail } from '@/lib/types';
import type {
  Asset, ExhibitBundle, Media, MediaIndexEntry, NavigationResult,
  NavigationTarget, Scope,
} from '@/lib/contracts';
import { GlassCard, Kicker } from '@/components/ui';
import { PdfReader } from '@/components/reader/PdfReader';
import { PageImageReader } from '@/components/reader/PageImageReader';
import { SourceMedia } from '@/components/source/SourceMedia';
import { SourceBadge } from '@/components/source/SourceBadge';
import { MediaModal, type MediaItem } from '@/components/MediaModal';
import { FigureImage } from '@/components/FigureImage';
import { TableRender } from '@/components/TableRender';
import { MathText } from '@/components/MathText';
import { LongText } from '@/components/LongText';
import { api } from '@/lib/api';
import { findAsset, resolveMediaPolicy } from '@/lib/sourcePolicy';
import { cn } from '@/lib/cn';

type Mode = 'pdf' | 'structured' | 'fulltext';

/** 旧 sections 与新 canonical sections 的统一视图模型。 */
interface SectionVM {
  heading: string;
  kind: string;
  page: number;
  page_start?: number;
  page_end?: number;
  summary: string;
  body: string;
  key_points: string[];
  /** 页锚点（canonical section 自带）；用于"在原件中打开本节"。 */
  anchor_ids: string[];
}

export function PaperView({
  detail,
  scope,
  documentUrl,
  exhibits,
  mediaIndex,
  assets,
  target,
  locateNotice,
  pdfFailed,
  onPdfFailed,
  onLocated,
  onNavigate,
}: {
  detail: PaperDetail;
  scope: Scope | null;
  documentUrl?: string;
  exhibits: ExhibitBundle | null;
  mediaIndex: MediaIndexEntry[];
  assets: Asset[];
  target: NavigationTarget | null;
  locateNotice: { status: string; page?: number | null; anchorId?: string } | null;
  pdfFailed: boolean;
  onPdfFailed: () => void;
  onLocated: (r: NavigationResult) => void;
  onNavigate: (t: NavigationTarget) => void;
}) {
  const [mode, setMode] = useState<Mode>('pdf');
  // 旧图表大图（legacy 降级路径）
  const [media, setMedia] = useState<MediaItem | null>(null);
  // canonical 媒体大图（浅色原件层）
  const [openCanonical, setOpenCanonical] = useState<Media | null>(null);
  // PDF 失败时的页面图片兜底页码
  const [fallbackPage, setFallbackPage] = useState(1);

  // 目标页（D13 展示用）：只有 region_highlighted / page_opened 才有页码
  const locatedPage = locateNotice && (locateNotice.status === 'region_highlighted' || locateNotice.status === 'page_opened')
    ? locateNotice.page ?? null
    : null;

  // 页码变化时同步 PDF 失败兜底的页图片页码
  useEffect(() => {
    if (locatedPage && locatedPage > 0) setFallbackPage(locatedPage);
  }, [locatedPage]);

  // canonical sections 优先，旧 detail.sections 降级
  //
  // D29 修复：canonical section **没有 body / 页码**（它只有 heading/kind/summary/
  // key_points/source_block_ids/anchor_ids），此前这里把 body 写死 ''、page 写死 0，
  // 于是"结构化导读"每一节都只剩一句 summary，正文（实测 6353/4022/6647 字）
  // 与页码徽标被整块丢弃 —— 用户看到的就是"结构化导读的内容不齐"。
  // 现在按 heading 与旧 detail.sections 合并，缺什么补什么。
  const sections: SectionVM[] = useMemo(() => {
    const legacyByHeading = new Map(detail.sections.map((s) => [s.heading, s]));
    const canon = exhibits?.structure?.sections ?? [];
    if (canon.length > 0) {
      return canon.map((s) => {
        const legacy = legacyByHeading.get(s.heading);
        const canonPoints = (s.key_points ?? []).map((k) => k.text).filter(Boolean);
        return {
          heading: s.heading,
          kind: s.kind || legacy?.kind || 'body',
          page: legacy?.page ?? 0,
          page_start: legacy?.page_start ?? legacy?.page,
          page_end: legacy?.page_end ?? legacy?.page,
          summary: s.summary?.text || legacy?.summary || '',
          body: legacy?.body ?? '',
          key_points: canonPoints.length > 0 ? canonPoints : (legacy?.key_points ?? []),
          anchor_ids: (s as { anchor_ids?: string[] }).anchor_ids ?? [],
        };
      });
    }
    return detail.sections.map((s) => ({
      heading: s.heading,
      kind: s.kind,
      page: s.page,
      page_start: s.page_start ?? s.page,
      page_end: s.page_end ?? s.page,
      summary: s.summary,
      body: s.body,
      key_points: s.key_points ?? [],
      anchor_ids: [],
    }));
  }, [exhibits, detail.sections]);

  // canonical media：从 media_index 取 id，再 fetch media（懒加载 + 缓存）
  const [loadedMedia, setLoadedMedia] = useState<Media[]>([]);
  const requestedRef = useRef(false);
  useEffect(() => {
    if (!scope || mediaIndex.length === 0 || requestedRef.current) return;
    requestedRef.current = true;
    Promise.all(
      mediaIndex.slice(0, 40).map((m) =>
        api.getMedia(scope.paper_id, m.id, scope.revision_id).then((r) => r.media).catch(() => null),
      ),
    ).then((rs) => setLoadedMedia(rs.filter((m): m is Media => !!m)));
  }, [scope, mediaIndex]);

  const openMedia = (mediaId: string) => {
    const m = loadedMedia.find((x) => x.id === mediaId);
    if (m) setOpenCanonical(m);
  };

  const hasCanonicalMedia = loadedMedia.length > 0;

  return (
    <div className="mx-auto max-w-4xl">
      {/* D13：定位结果提示——只有真正画出区域才说"已高亮" */}
      {locateNotice && (
        <div
          className={cn(
            'mb-4 rounded-xl border px-4 py-2.5 text-[13px]',
            locateNotice.status === 'region_highlighted'
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
              : locateNotice.status === 'page_opened'
                ? 'border-indigo-500/40 bg-indigo-500/10 text-indigo-200'
                : 'border-amber-500/40 bg-amber-500/10 text-amber-200',
          )}
        >
          {locateNotice.status === 'region_highlighted' && (
            locatedPage ? `已在原文第 ${locatedPage} 页高亮该证据区域。` : '已在原文中高亮该证据区域。'
          )}
          {locateNotice.status === 'page_opened' && (
            locatedPage ? `已跳转到第 ${locatedPage} 页（该证据无区域坐标，仅定位到页）。` : '已定位到对应页（该证据无区域坐标，未高亮）。'
          )}
          {locateNotice.status === 'unavailable' && '无法定位到原文（缺少可用的锚点或页面）。'}
        </div>
      )}

      <GlassCard className="p-8">
        <Kicker className="mb-3">论文阅读 · PAPER</Kicker>
        <h1 className="text-2xl font-semibold leading-tight text-white">{detail.title}</h1>
        <p className="mt-1 font-mono text-[12px] text-slate-500">{detail.subtitle}</p>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px] text-slate-500">
          <span>{detail.authors.join(', ')}</span>
          <span>{detail.year}</span>
          <span>{detail.domain}</span>
        </div>
        <div className="mt-5 border-t border-[var(--line)] pt-5">
          <Kicker>摘要</Kicker>
          <p className="mt-2 text-[15px] leading-relaxed text-slate-300">{detail.abstract}</p>
        </div>
        <div className="mt-4 flex items-center gap-2 border-t border-[var(--line)] pt-4">
          <div className="flex rounded-xl border border-[var(--line)] bg-white/[0.03] p-0.5">
            <button onClick={() => setMode('pdf')}
              className={cn('inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition',
                mode === 'pdf' ? 'bg-indigo-500/25 text-white' : 'text-slate-400 hover:text-slate-200')}>
              <FileDown className="h-3.5 w-3.5" /> 原件 PDF
            </button>
            <button onClick={() => setMode('structured')}
              className={cn('inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition',
                mode === 'structured' ? 'bg-indigo-500/25 text-white' : 'text-slate-400 hover:text-slate-200')}>
              <BookOpen className="h-3.5 w-3.5" /> 结构化导读
            </button>
            <button onClick={() => setMode('fulltext')}
              className={cn('inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition',
                mode === 'fulltext' ? 'bg-indigo-500/25 text-white' : 'text-slate-400 hover:text-slate-200')}>
              <ScrollText className="h-3.5 w-3.5" /> 全文原文
            </button>
          </div>
          <span className="ml-auto font-mono text-[10px] text-slate-600">
            {mode === 'pdf' ? '真实原件 · PDF.js'
              : mode === 'structured' ? '解读层 · 章节/要点/图表'
                : `${detail.pages?.length || 0} 页原文本`}
          </span>
        </div>
      </GlassCard>

      <div className="mt-6 space-y-6">
        {/* 原件 PDF（默认）：D05 */}
        {mode === 'pdf' && (
          <GlassCard className="p-4">
            {scope && documentUrl && !pdfFailed ? (
              <PdfReader
                scope={scope}
                document_url={documentUrl}
                initial_target={target}
                onLocated={onLocated}
              />
            ) : (
              <div className="space-y-2">
                <p className="text-[12px] text-slate-500">
                  PDF 阅读器不可用，改用页面预览图片（§3.2）。共 {detail.pages?.length || 1} 页。
                </p>
                <PageImageReader
                  paperId={scope?.paper_id ?? 0}
                  pdfPageNo={fallbackPage}
                  revisionId={scope?.revision_id}
                />
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setFallbackPage((p) => Math.max(1, p - 1))}
                    className="rounded-md border border-white/10 px-2 py-0.5 text-[11px] text-slate-400 hover:text-white"
                  >上一页</button>
                  <span className="font-mono text-[11px] text-slate-500">p.{fallbackPage}</span>
                  <button
                    onClick={() => setFallbackPage((p) => p + 1)}
                    className="rounded-md border border-white/10 px-2 py-0.5 text-[11px] text-slate-400 hover:text-white"
                  >下一页</button>
                </div>
              </div>
            )}
            {/* PdfReader 内部 Document onError 无回调，这里提供手动降级入口 */}
            {!pdfFailed && scope && documentUrl && (
              <button
                onClick={onPdfFailed}
                className="mt-2 text-[11px] text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
              >
                原件加载失败？改用页面图片
              </button>
            )}
          </GlassCard>
        )}

        {/* 全文原文模式 */}
        {mode === 'fulltext' && (
          <GlassCard className="p-6">
            <Kicker className="mb-3">论文原文 · FULL TEXT（按页）</Kicker>
            {(!detail.pages || detail.pages.length === 0) && (
              <p className="text-[13px] text-slate-500">未提取到原文文本（示例论文为程序化内容）。</p>
            )}
            <div className="space-y-5">
              {(detail.pages || []).map((pg) => (
                <div key={pg.page_no} className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="rounded-md bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] text-slate-500">p.{pg.page_no}</span>
                  </div>
                  <LongText
                    text={pg.text}
                    paragraphClassName="text-[14px] leading-7 text-slate-400"
                    collapsible
                    collapsedHeight={420}
                  />
                </div>
              ))}
            </div>
          </GlassCard>
        )}

        {/* 结构化导读：章节（canonical 优先，旧字段降级） */}
        {mode === 'structured' && sections.map((sec) => (
          <GlassCard key={sec.heading} className="p-6">
            <div className="mb-2 flex items-center gap-2">
              <FileText className="h-4 w-4 text-slate-500" />
              <h2 className="text-lg font-semibold text-white">{sec.heading}</h2>
              {sec.page_start ? (
                <span className="ml-auto rounded-md bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] text-slate-500">
                  {sec.page_end && sec.page_end !== sec.page_start
                    ? `p.${sec.page_start}–${sec.page_end}`
                    : `p.${sec.page_start}`}
                </span>
              ) : null}
            </div>
            <LongText
              text={sec.body || sec.summary}
              paragraphClassName="text-[14px] leading-7 text-slate-300"
              collapsible
              collapsedHeight={320}
            />
            {sec.key_points.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {sec.key_points.map((kp, j) => (
                  <li key={j} className="flex items-start gap-2 text-[12px] text-slate-500">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-400" />
                    <MathText text={kp} />
                  </li>
                ))}
              </ul>
            )}
            {sec.anchor_ids.length > 0 && scope && (
              <button
                onClick={() => onNavigate({
                  paper_id: scope.paper_id,
                  revision_id: scope.revision_id,
                  anchor_id: sec.anchor_ids[0],
                  segment_index: 0,
                })}
                className="mt-3 inline-flex items-center gap-1.5 text-[12px] font-medium text-indigo-300 hover:text-indigo-200"
              >
                <BookOpen className="h-3.5 w-3.5" /> 在原件中打开本节
              </button>
            )}
          </GlassCard>
        ))}

        {/* D06：canonical 媒体走 SourceMedia（浅色原件层包在深色容器里） */}
        {mode === 'structured' && hasCanonicalMedia && (
          <div>
            <Kicker className="mb-3">原件媒体 · SOURCE MEDIA</Kicker>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              {loadedMedia.map((m) => (
                <div key={m.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-2">
                  <SourceMedia
                    media={m}
                    assets={assets}
                    onOpen={openMedia}
                    onNavigate={onNavigate}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 结构化导读：图（D29 修复：canonical 媒体不再顶掉真图真表） */}
        {mode === 'structured' && detail.figures.length > 0 && (
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            {detail.figures.map((f) => (
            <GlassCard key={`fig-${f.fig_no}`} onClick={() => setMedia({ type: 'figure', figure: f, media: null } as unknown as MediaItem)}
              className="group cursor-pointer p-4 transition-all hover:border-white/20">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-200">图 {f.fig_no}</span>
                <span className="flex items-center gap-2 font-mono text-[10px] text-slate-500">
                  p.{f.page}
                </span>
              </div>
              <div className="overflow-hidden rounded-lg border border-[var(--line)] bg-[#0F172A] p-1">
                <FigureImage image_url={f.image_url} image_b64={f.image_b64} glyph_svg={f.glyph_svg} caption={f.caption} />
              </div>
              <MathText text={f.caption} className="mt-2 block text-[11px] text-slate-500" />
            </GlassCard>
          ))}
          </div>
        )}

        {/* 结构化导读：表（D29 修复：与 canonical 媒体并存） */}
        {mode === 'structured' && detail.tables.length > 0 && (
        <div className="space-y-6">
          {detail.tables.map((t) => (
            <GlassCard key={`tbl-${t.table_no}`} onClick={() => setMedia({ type: 'table', table: t })}
              className="group cursor-pointer p-6 transition-all hover:border-white/20">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-200">表 {t.table_no}</span>
                <span className="ml-auto font-mono text-[10px] text-slate-500">p.{t.page}</span>
              </div>
              <MathText text={t.caption} className="mb-3 block text-[12px] text-slate-500" />
              <div className="overflow-hidden rounded-lg border border-[var(--line)] p-1">
                <TableRender table={t} className="rl-table" />
              </div>
              {t.key_finding && (
                <div className="mt-2.5 rounded-lg border-l-2 border-emerald-400 bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-100/90">
                  关键结论：{t.key_finding}
                </div>
              )}
            </GlassCard>
          ))}
        </div>
        )}

        <MediaModal item={media} accent={detail.accent || '#6366F1'} onClose={() => setMedia(null)} />

        {/* D06：canonical 原件大图——来源层级由 resolveMediaPolicy 决定，浅底更真实 */}
        {openCanonical && (
          <CanonicalMediaLightbox
            media={openCanonical}
            assets={assets}
            onClose={() => setOpenCanonical(null)}
            onNavigate={onNavigate}
          />
        )}
      </div>
    </div>
  );
}

function CanonicalMediaLightbox({
  media,
  assets,
  onClose,
  onNavigate,
}: {
  media: Media;
  assets: Asset[];
  onClose: () => void;
  onNavigate: (t: NavigationTarget) => void;
}) {
  const policy = resolveMediaPolicy(media, assets);
  const asset = policy.original_asset_ids.map((id) => findAsset(assets, id)).find((a) => !!a);
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur"
      onClick={onClose}
    >
      <div
        className="max-h-[88vh] w-full max-w-4xl overflow-y-auto rounded-3xl border border-white/10 bg-[#0c1526] p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center gap-2">
          <SourceBadge mode={policy.default_mode} label={policy.label} />
          {media.original_label && <span className="font-mono text-[11px] text-slate-400">{media.original_label}</span>}
          <span className="ml-auto font-mono text-[11px] text-slate-500">原件 · PDF 第 {media.anchor_ids.length} 锚点</span>
          <button onClick={onClose} className="grid h-8 w-8 place-items-center rounded-lg text-slate-400 hover:bg-white/5 hover:text-white">
            ✕
          </button>
        </div>
        {/* 浅色原件层用外层深色卡片包裹，保持工作台深色观感协调（§6.16 交付限制） */}
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-2">
          <SourceMedia media={media} assets={assets} onOpen={() => {}} onNavigate={onNavigate} />
        </div>
        {asset && <p className="mt-2 text-[11px] text-slate-500">资产：{asset.kind} · {asset.mime}</p>}
        {policy.warnings.length > 0 && (
          <p className="mt-1 text-[11px] text-amber-300/80">{policy.warnings[0].message}</p>
        )}
      </div>
    </div>
  );
}
