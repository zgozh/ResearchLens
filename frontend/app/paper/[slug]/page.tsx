'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, LayoutGrid, Workflow, FileSearch, Share2, Mic, MessageCircle, Gauge, BookOpen, ChevronRight,
} from 'lucide-react';
import { api, sleep } from '@/lib/api';
import type {
  ClaimOut, ClaimSummary, EvaluationOut, GraphOut, PaperDetail, PaperOut, PresentationOut, ViewMode,
} from '@/lib/types';
import type {
  ClaimRecord, ExhibitBundle, MediaIndexEntry, NavigationTarget, Scope,
} from '@/lib/contracts';
import { usePaperWorkspace } from '@/hooks/usePaperWorkspace';
import { useEvidenceNavigation } from '@/hooks/useEvidenceNavigation';
import { useJobEvents } from '@/hooks/useJobEvents';
import { JobProgress } from '@/components/jobs/JobProgress';
import { AgentTrace } from '@/components/jobs/AgentTrace';
import { Logo } from '@/components/Logo';
import { Badge, GlassCard, Kicker, Spinner } from '@/components/ui';
import { Timeline } from '@/components/Timeline';
import { EvidenceDrawer } from '@/components/evidence/EvidenceDrawer';
import { MapView } from '@/components/views/MapView';
import { MethodView } from '@/components/views/MethodView';
import { ClaimView } from '@/components/views/ClaimView';
import { GraphView } from '@/components/views/GraphView';
import { PresenterView } from '@/components/views/PresenterView';
import { QAView } from '@/components/views/QAView';
import { EvalView } from '@/components/views/EvalView';
import { PaperView } from '@/components/views/PaperView';
import { cn } from '@/lib/cn';

const NAV: { view: ViewMode; label: string; icon: any }[] = [
  { view: 'map', label: '论文地图', icon: LayoutGrid },
  { view: 'method', label: '方法动画', icon: Workflow },
  { view: 'claim', label: '证据链', icon: FileSearch },
  { view: 'graph', label: '研究图谱', icon: Share2 },
  { view: 'presenter', label: '讲解', icon: Mic },
  { view: 'qa', label: '证据问答', icon: MessageCircle },
  { view: 'eval', label: '自动评测', icon: Gauge },
  { view: 'paper', label: '论文阅读', icon: BookOpen },
];

/** 从 canonical ClaimRecord 生成旧 ClaimSummary（视图分组/长度仍用旧形状）。
 *
 * D29 修复：``rationale`` 对 canonical 断言**恒为空串**，此前回退到 ``claim_id``
 * 于是证据链列表把 ``haar_superior_to_linear_metrics`` 这类内部 ID 当正文显示。
 * 断言正文在 ``statements`` 表里，由调用方用 ``statement_id → text`` 映射回填
 * （见 ``statementsById``）；这里只保留"确实拿不到"时的诚实占位。
 */
function claimSummaryOf(c: ClaimRecord, statementsById?: Map<string, string>): ClaimSummary {
  const fromStatement = c.statement_id ? statementsById?.get(c.statement_id) : undefined;
  return {
    claim_id: c.claim_id,
    statement: (fromStatement || '').trim() || c.rationale || '',
    type: c.type,
    confidence: c.confidence ?? 0,
    status: c.status === 'verified' ? 'SUPPORTED' : 'UNSUPPORTED',
    evidence_count: c.evidence_ids.length,
  };
}

export default function Workspace() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug;
  const searchParams = useSearchParams();
  const router = useRouter();
  const paperIdParam = searchParams.get('paper_id');
  const jobId = searchParams.get('job_id');

  const [resolvedPaperId, setResolvedPaperId] = useState<number | undefined>(
    paperIdParam ? Number(paperIdParam) : undefined,
  );
  const [detail, setDetail] = useState<PaperDetail>();
  const [paper, setPaper] = useState<PaperOut>();
  const [graph, setGraph] = useState<GraphOut>({ nodes: [], edges: [] });
  const [presentation, setPresentation] = useState<PresentationOut>({ scenes: [] });
  const [evalData, setEvalData] = useState<EvaluationOut>({ overall_score: 0, metrics: {} });
  const [view, setView] = useState<ViewMode>(
    (searchParams.get('view') as ViewMode) || 'map',
  );
  const [selectedClaimId, setSelectedClaimId] = useState<string>();
  // 兼容旧 ClaimOut（text.indexOf 引文高亮的旧路径已移除，这里是降级壳）
  const [claimDetail, setClaimDetail] = useState<ClaimOut>();
  // 证据问答历史消息（提升到本页，跨视图切换保持）
  const [qaMessages, setQaMessages] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [processing, setProcessing] = useState(false);
  const [stageLabel, setStageLabel] = useState<string>();
  // PDF 阅读器定位结果（D13：只有真正画出区域才报已高亮）
  const [locateNotice, setLocateNotice] = useState<{ status: string; page?: number | null; anchorId?: string } | null>(null);
  const [pdfFailed, setPdfFailed] = useState(false);

  // ---- canonical：先 manifest 得 revision，再并行取同 revision 的 exhibits（§5.13）----
  const workspace = usePaperWorkspace({ paper_id: resolvedPaperId ?? 0 });
  const manifest = workspace.manifest.data;
  const exhibits: ExhibitBundle | null = workspace.exhibits.data;
  const revisionId = manifest?.revision?.id ?? null;
  const scope: Scope | null = useMemo(
    () => (resolvedPaperId && revisionId ? { paper_id: resolvedPaperId, revision_id: revisionId } : null),
    [resolvedPaperId, revisionId],
  );

  // slug-only 访问：先 demoLoad 拿 id，再走 canonical
  useEffect(() => {
    if (resolvedPaperId || !slug) return;
    let cancelled = false;
    api
      .demoLoad(slug)
      .then((p) => {
        if (!cancelled) setResolvedPaperId(p.id);
      })
      .catch(async () => {
        // 兜底：从论文列表按 slug 找
        try {
          const list = await api.papers();
          const hit = list.find((x) => x.slug === slug);
          if (hit && !cancelled) setResolvedPaperId(hit.id);
        } catch {
          /* ignore */
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug, resolvedPaperId]);

  const accent = detail?.accent || '#6366F1';
  const isUpload = detail?.source_mode === 'upload';

  // 导航到物理页（D12/D13）：NavigationTarget 真正交给阅读器，结果由 onLocated 回填
  const evidenceNav = useEvidenceNavigation({
    scope: scope ?? { paper_id: 0, revision_id: '' },
  });

  /** 旧视图把证据映射到物理页（D12）：NavigationTarget 交给阅读器，结果由 onLocated 回填。 */
  const jumpToPaper = useCallback(
    (anchorId: string | null | undefined) => {
      setView('paper');
      setLocateNotice(null);
      if (!scope || !anchorId) {
        // 无 anchor：只能打开论文视图，不谎称已高亮
        setLocateNotice({ status: 'unavailable' });
        return;
      }
      const target: NavigationTarget = {
        paper_id: scope.paper_id,
        revision_id: scope.revision_id,
        anchor_id: anchorId,
        segment_index: 0,
      };
      // 页码由 anchor.segments[0].pdf_page_index 决定（±1 → PDF 页序），与阅读器一致
      const pageP = api
        .getAnchor(scope.paper_id, anchorId, scope.revision_id)
        .then((a) => (a.segments?.[0] ? a.segments[0].pdf_page_index + 1 : null))
        .catch(() => null);
      evidenceNav.navigate(target).then(async (r) => {
        setLocateNotice({ status: r.status, page: await pageP, anchorId });
      });
    },
    [scope, evidenceNav],
  );

  const changeView = useCallback(
    (v: ViewMode) => {
      setView(v);
      const pid = resolvedPaperId;
      const qs = pid ? `paper_id=${pid}&view=${v}` : `view=${v}`;
      if (slug) router.replace(`/paper/${slug}?${qs}`, { scroll: false });
    },
    [slug, resolvedPaperId, router],
  );

  /** D29：论文地图点「阅读该章节正文」→ 用本节**页锚点**定位到原件正文页。
   *
   * 此前这里把 section 参数整个丢掉（`() => changeView('paper')`），
   * 于是用户点了章节只是"切到论文视图"，并没有跳到该章节对应的正文页。
   * 锚点取自 canonical `structure.sections[].anchor_ids`（由本节块的页锚点派生）；
   * 没有锚点时如实报告"无法定位"，不假装已跳转。
   */
  const openSectionInPaper = useCallback(
    (section: { heading: string; page_start?: number; page?: number }) => {
      const canon = (exhibits?.structure?.sections ?? []) as Array<{
        heading?: string; anchor_ids?: string[];
      }>;
      const hit = canon.find((c) => c.heading === section.heading);
      const anchorId = hit?.anchor_ids?.[0];
      if (anchorId) {
        jumpToPaper(anchorId);
        return;
      }
      setView('paper');
      setLocateNotice({ status: 'unavailable' });
    },
    [exhibits, jumpToPaper],
  );

  const loadLegacy = useCallback(async () => {
    if (!resolvedPaperId) return;
    setLoading(true);
    setError(undefined);
    try {
      const d = await api.paperDetail(resolvedPaperId);
      setPaper(d);
      setDetail(d);
      setGraph(await api.graph(resolvedPaperId));
      setPresentation(await api.presentation(resolvedPaperId));
      setEvalData(await api.evaluation(resolvedPaperId));
    } catch (e: any) {
      console.error(e);
      setError(e?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [resolvedPaperId]);

  useEffect(() => {
    loadLegacy();
  }, [loadLegacy]);

  // canonical 就绪后：用 exhibits.structure.sections 覆盖旧 sections，旧字段降级保留
  const canonicalClaims: ClaimRecord[] = exhibits?.claims ?? [];
  // 断言正文只在 statements 表里（claim.rationale 对 canonical 恒为空），
  // 这里建 statement_id → text 映射供断言列表回填，否则列表显示的是一串 claim_id。
  const statementsById = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of exhibits?.statements ?? []) {
      if (s?.id && (s.text || '').trim()) map.set(s.id, s.text);
    }
    return map;
  }, [exhibits]);
  const claims: ClaimSummary[] = useMemo(() => {
    if (canonicalClaims.length > 0) {
      return canonicalClaims.map((c) => claimSummaryOf(c, statementsById));
    }
    return [];
  }, [canonicalClaims, statementsById]);

  // 实时模式：canonical 无断言且存在 job → 轮询旧 claims（降级）
  useEffect(() => {
    if (!resolvedPaperId || processing) return;
    if (exhibits && canonicalClaims.length === 0 && detail?.source_mode === 'upload') {
      setProcessing(true);
    }
  }, [resolvedPaperId, exhibits, canonicalClaims.length, detail?.source_mode, processing]);

  useEffect(() => {
    if (!processing || !resolvedPaperId) return;
    if (exhibits && canonicalClaims.length > 0) {
      setProcessing(false);
      return;
    }
    let cancelled = false;
    (async () => {
      for (let i = 0; i < 40 && !cancelled; i++) {
        await sleep(2500);
        await workspace.refresh();
        if (cancelled) break;
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [processing, resolvedPaperId, exhibits, canonicalClaims.length]);

  // ---- 阶段 E：job 事件流（SSE），jobStatus 轮询作降级 ----
  const jobEvents = useJobEvents({ job_id: jobId ? Number(jobId) : 0 });
  useEffect(() => {
    if (!processing || !jobId || Number(jobId) === 0) return;
    // SSE 不可用（failed）时退化为 jobStatus 轮询
    if (jobEvents.state !== 'failed' && jobEvents.state !== 'idle') return;
    const id = setInterval(async () => {
      try {
        const j = await api.jobStatus(Number(jobId));
        setStageLabel(j.stage_label);
        if (j.status === 'done' || j.status === 'failed') clearInterval(id);
      } catch {
        /* 继续轮询 */
      }
    }, 2500);
    return () => clearInterval(id);
  }, [processing, jobId, jobEvents.state]);

  const topClaim = useMemo(() => claims[0]?.claim_id, [claims]);

  const selectClaim = useCallback(
    async (claimId: string, evidenceIdx?: number) => {
      setSelectedClaimId(claimId);
      if (!resolvedPaperId) return;
      // 兼容旧 ClaimOut（EvidenceDrawer 用 canonical evidence_ids，此处仅为旧视图保留）
      const c = await api.claim(resolvedPaperId, claimId).catch(() => undefined);
      setClaimDetail(c);
    },
    [resolvedPaperId],
  );

  useEffect(() => {
    if (view === 'claim' && !selectedClaimId && topClaim) {
      selectClaim(topClaim);
    }
  }, [view, selectedClaimId, topClaim, selectClaim]);

  // 选中 claim 的 canonical evidence_ids
  const selectedClaimRecord: ClaimRecord | undefined = useMemo(
    () => canonicalClaims.find((c) => c.claim_id === selectedClaimId),
    [canonicalClaims, selectedClaimId],
  );
  const evidenceIds = selectedClaimRecord?.evidence_ids ?? [];

  const mediaIndex: MediaIndexEntry[] = manifest?.media_index ?? [];
  const assets = manifest?.assets ?? [];

  const title = manifest?.paper?.title || detail?.title || '';
  const domain = manifest?.paper?.domain || detail?.domain || '';
  const modeLabel = isUpload ? '实时抽取' : '演示模式';

  return (
    <div className="grid-bg min-h-screen">
      {/* Top bar */}
      <header className="sticky top-0 z-30 border-b border-[var(--line)] bg-[#060a13]/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1500px] items-center gap-4 px-5 py-3">
          <Link href="/" className="flex items-center gap-2 text-slate-400 transition hover:text-white">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <Logo />
          <div className="hidden h-6 w-px bg-[var(--line)] sm:block" />
          {title && (
            <div className="hidden min-w-0 items-center gap-2 md:flex">
              <span className="max-w-[280px] truncate text-sm text-slate-300">{title}</span>
            </div>
          )}
          <div className="ml-auto flex items-center gap-3">
            <Badge tone={isUpload ? 'cyan' : 'emerald'}>{modeLabel}</Badge>
            <Badge tone="slate">{domain || '加载中'}</Badge>
          </div>
        </div>
        {/* view nav */}
        {detail && (
          <div className="mx-auto max-w-[1500px] px-5 pb-2.5">
            <div className="flex items-center gap-1 overflow-x-auto no-scrollbar">
              {NAV.map((n) => {
                const active = view === n.view;
                return (
                  <button
                    key={n.view}
                    onClick={() => changeView(n.view)}
                    className={cn(
                      'flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-[12px] font-medium transition-all',
                      active ? 'text-white' : 'text-slate-500 hover:text-slate-200',
                    )}
                    style={active ? { background: `${accent}1c`, border: `1px solid ${accent}44` } : { border: '1px solid transparent' }}
                  >
                    <n.icon className="h-3.5 w-3.5" style={{ color: active ? accent : undefined }} />
                    {n.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </header>

      {loading ? (
        <div className="grid min-h-[70vh] place-items-center">
          <div className="text-center">
            <Spinner className="mx-auto mb-4" />
            <p className="text-sm text-slate-500">ResearchLens 正在解析论文…</p>
          </div>
        </div>
      ) : error ? (
        <div className="grid min-h-[60vh] place-items-center px-6">
          <GlassCard className="max-w-md p-6">
            <Kicker>出错了</Kicker>
            <p className="mt-2 text-sm text-rose-300">{error}</p>
            <Link href="/" className="mt-4 inline-block text-sm text-indigo-300">← 返回选择论文</Link>
          </GlassCard>
        </div>
      ) : detail ? (
        <div className={cn(
          'mx-auto grid max-w-[1500px] grid-cols-1 gap-0 px-5 py-5',
          view === 'claim' ? 'lg:grid-cols-[minmax(0,1fr),360px]' : 'lg:grid-cols-1',
        )}>
          {/* Left + center */}
          <div className="min-w-0">
            {/* stage header */}
            <div className="mb-4 flex items-center justify-between">
              <div className="min-w-0">
                <Kicker>视觉演绎 · VISUAL STAGE</Kicker>
                <div className="mt-1 flex items-center gap-2">
                  <span className="text-lg font-semibold text-white">{title}</span>
                </div>
              </div>
              <div className="hidden shrink-0 flex-wrap gap-1.5 sm:flex">
                {(detail.tags || []).slice(0, 3).map((t) => (
                  <Badge key={t} tone="slate">{t}</Badge>
                ))}
              </div>
            </div>

            {/* 阶段 E：任务事件流（SSE）——阶段列表 + Agent 工具轨迹 */}
            {processing && (
              <div className="mb-4 space-y-3">
                {jobId && Number(jobId) !== 0 && jobEvents.events.length > 0 ? (
                  <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                    <JobProgress events={jobEvents.events} />
                    <AgentTrace events={jobEvents.events} />
                  </div>
                ) : (
                  <div className="flex items-center gap-2 rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-4 py-2.5 text-[13px] text-cyan-200">
                    <Spinner className="h-4 w-4" />
                    {stageLabel || '正在调用大模型抽取结构、断言与证据…'}
                  </div>
                )}
              </div>
            )}

            <AnimatePresence mode="wait">
              <motion.div
                key={view}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.25 }}
              >
                {view === 'map' && <MapView detail={detail} accent={accent} onOpenSection={openSectionInPaper} />}
                {view === 'method' && <MethodView detail={detail} accent={accent} />}
                {view === 'claim' && (
                  <ClaimView
                    detail={detail}
                    claims={claims}
                    selectedClaimId={selectedClaimId}
                    onSelect={(cid) => selectClaim(cid)}
                  />
                )}
                {view === 'graph' && <GraphView graph={graph} accent={accent} paperId={resolvedPaperId} scope={scope ?? undefined} onNavigate={(t) => jumpToPaper(t.anchor_id)} onClaimSelected={(cid, evIdx) => { selectClaim(cid, evIdx); changeView('claim'); }} />}
                {view === 'presenter' && <PresenterView presentation={presentation} accent={accent} detail={detail} claims={claims} statements={exhibits?.statements} />}
                {view === 'qa' && <QAView scope={scope} accent={accent} detail={detail} onNavigate={(t) => { jumpToPaper(t.anchor_id); }} messages={qaMessages} onMessagesChange={setQaMessages} />}
                {view === 'eval' && <EvalView evalData={evalData} accent={accent} report={exhibits?.evaluation ?? null} claims={claims} />}
                {view === 'paper' && (
                  <PaperView
                    detail={detail}
                    scope={scope}
                    documentUrl={resolvedPaperId && revisionId ? api.documentUrl(resolvedPaperId, revisionId) : undefined}
                    exhibits={exhibits}
                    mediaIndex={mediaIndex}
                    assets={assets}
                    target={evidenceNav.target}
                    locateNotice={locateNotice}
                    pdfFailed={pdfFailed}
                    onPdfFailed={() => setPdfFailed(true)}
                    onLocated={evidenceNav.reportLocated}
                    onNavigate={(t) => jumpToPaper(t.anchor_id)}
                  />
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* 证据链：桌面 rail + 移动抽屉共享同一内容（阶段 C / D14） */}
          {view === 'claim' && scope && (
            <div className="lg:pl-5">
              <EvidenceDrawer
                scope={scope}
                evidence_ids={evidenceIds}
                open={!!selectedClaimId}
                onClose={() => setSelectedClaimId(undefined)}
                onNavigate={(t) => jumpToPaper(t.anchor_id)}
              />
            </div>
          )}
        </div>
      ) : null}

      {/* bottom timeline */}
      {detail && (
        <div className="sticky bottom-0 z-30 border-t border-[var(--line)] bg-[#060a13]/85 backdrop-blur-xl">
          <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-5 py-3">
            <div className="text-[11px] font-mono text-slate-500">叙事线 · TIMELINE</div>
            <div className="flex-1">
              <Timeline current={view} accent={accent} onSelect={changeView} />
            </div>
          </div>
        </div>
      )}

      <div className="h-6" />
    </div>
  );
}
