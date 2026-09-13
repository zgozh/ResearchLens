'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, LayoutGrid, Workflow, FileSearch, Share2, Mic, MessageCircle, Gauge, BookOpen, ChevronRight,
  ShieldAlert,
} from 'lucide-react';
import { api, sleep } from '@/lib/api';
import type {
  ClaimOut, ClaimSummary, EvaluationOut, GraphOut, PaperDetail, PaperOut, PresentationOut, ViewMode,
} from '@/lib/types';
import type {
  Capability, ClaimRecord, ExhibitBundle, MediaIndexEntry, NavigationTarget, Scope,
} from '@/lib/contracts';
import { usePaperWorkspace } from '@/hooks/usePaperWorkspace';
import { useEvidenceNavigation } from '@/hooks/useEvidenceNavigation';
import { useJobEvents } from '@/hooks/useJobEvents';
import {
  deriveProgress,
  derivedTargetsFor,
  isProgressVisible,
  newlyReadyDomains,
  nextPollDelay,
  type DerivedTarget,
} from '@/lib/paperProgress';
import { JobProgress } from '@/components/jobs/JobProgress';
import { AgentTrace } from '@/components/jobs/AgentTrace';
import { Logo } from '@/components/Logo';
import { Badge, GlassCard, Kicker, Spinner } from '@/components/ui';
import { Timeline } from '@/components/Timeline';
import { EvidenceDrawer } from '@/components/evidence/EvidenceDrawer';
import type { CapabilityState } from '@/lib/evidenceStates';
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
function claimSummaryOf(
  c: ClaimRecord,
  statementsById?: Map<string, string>,
  validationsById?: Map<string, unknown>,
): ClaimSummary {
  const fromStatement = c.statement_id ? statementsById?.get(c.statement_id) : undefined;
  return {
    claim_id: c.claim_id,
    statement: (fromStatement || '').trim() || c.rationale || '',
    type: c.type,
    confidence: c.confidence ?? 0,
    status: c.status === 'verified' ? 'SUPPORTED' : 'UNSUPPORTED',
    evidence_count: c.evidence_ids.length,
    // M2：把 validation 一起带上，证据链列表才能显示"为什么未支持"的四分类
    validation: c.statement_id ? validationsById?.get(c.statement_id) : undefined,
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
      const params = new URLSearchParams();
      if (resolvedPaperId) params.set('paper_id', String(resolvedPaperId));
      params.set('view', v);
      // R4-M7b：**必须保留 `job_id`**。旧实现只写 `paper_id` + `view`，于是切一次视图
      // 就把 job_id 从 URL 里抹掉 → `useJobEvents({job_id: 0})` → SSE 被 abort、
      // 事件数组被清空 → 阶段列表退回通用转圈，**而且再也接不上进度**。
      if (jobId) params.set('job_id', jobId);
      if (slug) router.replace(`/paper/${slug}?${params.toString()}`, { scroll: false });
    },
    [slug, resolvedPaperId, router, jobId],
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
  // M2：statement_id → validation（四分类徽标的数据来源）
  const validationsByStatement = useMemo(() => {
    const map = new Map<string, unknown>();
    for (const s of exhibits?.statements ?? []) {
      const v = (s as { validation?: unknown }).validation;
      if (s?.id && v) map.set(s.id, v);
    }
    return map;
  }, [exhibits]);
  const claims: ClaimSummary[] = useMemo(() => {
    if (canonicalClaims.length > 0) {
      return canonicalClaims.map((c) => claimSummaryOf(c, statementsById, validationsByStatement));
    }
    return [];
  }, [canonicalClaims, statementsById, validationsByStatement]);

  // ---- R4-M7：进度真相 = manifest.capabilities + active_job（不再是"exhibits 非空"）----
  //
  // 旧实现在这里判定 `exhibits && canonicalClaims.length === 0 && source_mode === 'upload'`，
  // 而 `exhibits` 在"还没有 revision"时恒为 null → **那段 40×2.5s 轮询根本不会启动** →
  // 页面一片空白，用户只能手动刷新。现在由 `deriveProgress` 统一推导：
  // 分域进度、三终态、是否继续轮询、退避间隔。
  const [elapsedMs, setElapsedMs] = useState(0);
  const progress = useMemo(
    () => deriveProgress({
      capabilities: manifest?.capabilities ?? null,
      activeJob: manifest?.active_job ?? null,
      elapsedMs,
    }),
    [manifest?.capabilities, manifest?.active_job, elapsedMs],
  );
  // 进度驱动轮询（指数退避 + 预算上限 + 页面隐藏时暂停）
  useEffect(() => {
    if (!resolvedPaperId || !progress.shouldPoll) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (cancelled) return;
      if (typeof document !== 'undefined' && document.hidden) {
        // 页面不可见时降频（不空转），可见后自动恢复
        timer = setTimeout(tick, 5000);
        return;
      }
      setElapsedMs((v) => v + 1000);
      // **silent**：后台轮询不许把加载状态刷成 loading —— 那会让进度卡
      // 跟着轮询周期出现/消失（用户报的"一闪一闪"）。
      await workspace.refresh({ silent: true });
      if (cancelled) return;
      timer = setTimeout(tick, nextPollDelay(elapsedMs, !!manifest?.active_job));
    };
    timer = setTimeout(tick, nextPollDelay(elapsedMs, !!manifest?.active_job));
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // elapsedMs 有意不进依赖：它由 tick 自己推进，进依赖会形成重建循环
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedPaperId, progress.shouldPoll, manifest?.active_job, workspace.refresh]);

  /**
   * 还没到"可看内容"的状态：显示分域进度与终态，而不是空白。
   *
   * R4-M7b：**只看进度真相**，不再看 `exhibits.status` ——
   * 那个值会被轮询自己重置（见 `usePaperWorkspace.refresh`），
   * 把它当判据等于让卡片跟着轮询闪烁。
   */
  const notReady = isProgressVisible(progress.phase);
  // 兼容旧变量名：`processing` 现在由进度真相驱动（供阶段 E 的事件流区块复用）
  const processing = progress.shouldPoll;

  // ---- R4-M7b：分域就绪 → 拉对应派生数据（解析结果**实时上屏**）----
  //
  // 为什么需要：轮询只刷新 manifest + exhibits，而各视图消费的是 legacy 派生数据
  // （detail / graph / presentation / evaluation）—— 那些原先**整篇论文只加载一次**，
  // 所以解析完成后图谱/讲解/评测/图表永远不会自动出现，用户必须手动刷新。
  //
  // 只在**状态跃迁**（pending→ready）时拉，且走 silent：`detail` 是较重的聚合端点，
  // 周期性重取会打断正在看的图表/讲解；失败时**保留旧数据**。
  const capsRef = useRef<Capability[] | null>(null);

  const refreshDerived = useCallback(async (targets: DerivedTarget[]) => {
    if (!resolvedPaperId || targets.length === 0) return;
    try {
      if (targets.includes('detail')) setDetail(await api.paperDetail(resolvedPaperId));
      if (targets.includes('graph')) setGraph(await api.graph(resolvedPaperId));
      if (targets.includes('presentation')) setPresentation(await api.presentation(resolvedPaperId));
      if (targets.includes('evaluation')) setEvalData(await api.evaluation(resolvedPaperId));
    } catch (e) {
      console.warn('[live] 派生数据刷新失败，保留旧数据：', e);
    }
  }, [resolvedPaperId]);

  useEffect(() => {
    const caps = manifest?.capabilities ?? null;
    const justReady = newlyReadyDomains(capsRef.current, caps);
    capsRef.current = caps;
    if (justReady.length > 0) {
      void refreshDerived(derivedTargetsFor(justReady));
    }
  }, [manifest?.capabilities, refreshDerived]);

  // 完成后让进度卡多留 1.2s 再淡出（让用户看到"完成"，而不是瞬间消失）
  const [holdProgress, setHoldProgress] = useState(false);
  const prevPhaseRef = useRef(progress.phase);
  useEffect(() => {
    const prev = prevPhaseRef.current;
    prevPhaseRef.current = progress.phase;
    if (prev !== 'ready' && progress.phase === 'ready') {
      setHoldProgress(true);
      const t = setTimeout(() => setHoldProgress(false), 1200);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [progress.phase]);

  const showProgress = notReady || holdProgress;

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
  // R4-M1：证据抽屉要区分「尚未抽取」与「确无关联证据」，判据取自 manifest.capabilities
  // （claims 域状态）—— 这是页面本来就拿得到、却一直没人用的现成信号。
  const claimsCapabilityState: CapabilityState =
    (manifest?.capabilities?.find((c) => c.name === 'claims')?.state as CapabilityState)
    ?? 'unknown';

  const title = manifest?.paper?.title || detail?.title || '';
  const domain = manifest?.paper?.domain || detail?.domain || '';
  // R4：'演示模式' 这个词随 DEMO_MODE 一起退休 —— 它描述的是一个已不存在的模式。
  // 现在只区分「这篇是从上传/网址导入的」与「库内自带论文」。
  const modeLabel = isUpload ? '实时抽取' : '库内论文';

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

            {/* R4-M7：**`manifest.capabilities` 驱动的分域进度**。
                以前这里什么都没有 —— 用户看到一片空白，只能手动刷新。
                现在：每个域一行（含后端给的原因），三终态各有界面。 */}
            {showProgress && (
              <GlassCard className="mb-4 p-5">
                {progress.phase === 'failed' ? (
                  <div className="flex items-start gap-2 text-rose-200">
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>
                      <div className="text-sm font-medium">处理失败</div>
                      <div className="mt-1 text-[12px] text-rose-300/80">
                        {progress.failureMessage}
                      </div>
                      <div className="mt-2 flex gap-2">
                        <button
                          onClick={() => void workspace.refresh()}
                          className="rounded-lg border border-rose-400/30 px-2.5 py-1 text-[11px] transition hover:bg-rose-500/15"
                        >
                          重新检查状态
                        </button>
                        <Link href="/upload" className="rounded-lg border border-[var(--line)] px-2.5 py-1 text-[11px] text-slate-300 transition hover:bg-white/[0.06]">
                          重新上传
                        </Link>
                      </div>
                    </div>
                  </div>
                ) : progress.phase === 'unavailable' ? (
                  <div className="flex items-start gap-2 text-amber-200">
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    <div>
                      <div className="text-sm font-medium">该论文没有可用的源文件</div>
                      <ul className="mt-1.5 space-y-0.5 text-[12px] text-amber-300/80">
                        {progress.domains.filter((d) => d.reason).map((d) => (
                          <li key={d.name}>· {d.label}：{d.reason}</li>
                        ))}
                      </ul>
                      <Link href="/upload" className="mt-2 inline-block rounded-lg border border-amber-400/30 px-2.5 py-1 text-[11px] transition hover:bg-amber-500/15">
                        重新上传论文
                      </Link>
                    </div>
                  </div>
                ) : (
                  <div>
                    <div className="mb-3 flex items-center gap-2">
                      <Spinner className="h-4 w-4" />
                      <span className="text-sm font-medium text-white">
                        {progress.phase === 'timeout'
                          ? '处理时间超出预期，仍在后台继续'
                          : '正在解析这篇论文…'}
                      </span>
                      <span className="ml-auto font-mono text-[11px] text-slate-500">
                        {Math.round(progress.ratio * 100)}%
                      </span>
                    </div>
                    <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                      <div
                        className="h-full rounded-full bg-indigo-400 transition-all duration-500"
                        style={{ width: `${Math.round(progress.ratio * 100)}%` }}
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
                      {progress.domains.map((d) => (
                        <div key={d.name} className="flex items-center gap-1.5 text-[11px]">
                          <span
                            className={
                              d.state === 'ready'
                                ? 'h-1.5 w-1.5 rounded-full bg-emerald-400'
                                : d.state === 'unavailable'
                                  ? 'h-1.5 w-1.5 rounded-full bg-amber-400'
                                  : 'h-1.5 w-1.5 animate-pulse rounded-full bg-slate-500'
                            }
                          />
                          <span className={d.state === 'ready' ? 'text-slate-300' : 'text-slate-500'}>
                            {d.label}
                          </span>
                          {d.reason && d.state !== 'ready' && (
                            <span className="truncate text-slate-600" title={d.reason}>
                              {d.reason}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                    {progress.phase === 'timeout' && (
                      <p className="mt-3 text-[11px] text-slate-500">
                        后台仍在继续；你也可以手动刷新查看最新进度（不必反复刷新）。
                      </p>
                    )}
                  </div>
                )}
              </GlassCard>
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
                claimsState={claimsCapabilityState}
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
