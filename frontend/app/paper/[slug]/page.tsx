'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { Logo } from '@/components/Logo';
import { Badge, GlassCard, Kicker, Spinner } from '@/components/ui';
import { Timeline } from '@/components/Timeline';
import { EvidenceRail } from '@/components/EvidenceRail';
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

export default function Workspace() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug;
  const searchParams = useSearchParams();
  const router = useRouter();
  const paperId = searchParams.get('paper_id');
  const jobId = searchParams.get('job_id');

  const [paper, setPaper] = useState<PaperOut>();
  const [detail, setDetail] = useState<PaperDetail>();
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [graph, setGraph] = useState<GraphOut>({ nodes: [], edges: [] });
  const [presentation, setPresentation] = useState<PresentationOut>({ scenes: [] });
  const [evalData, setEvalData] = useState<EvaluationOut>({ overall_score: 0, metrics: {} });
  const [view, setView] = useState<ViewMode>(
    (searchParams.get('view') as ViewMode) || 'map',
  );
  const [selectedClaimId, setSelectedClaimId] = useState<string>();
  const [claimDetail, setClaimDetail] = useState<ClaimOut>();
  const [paperTarget, setPaperTarget] = useState<{ kind?: string; page?: number; quote?: string }>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [processing, setProcessing] = useState(false);
  const [stageLabel, setStageLabel] = useState<string>();

  const accent = detail?.accent || '#6366F1';
  const isUpload = detail?.source_mode === 'upload';
  const modeLabel = isUpload ? '实时抽取' : '演示模式';

  const jumpToPaper = useCallback((page: number, region: string, quote: string) => {
    const kindMap: Record<string, string> = {
      discussion: 'discussion', method: 'method', experiments: 'experiment', experiment: 'experiment',
      results: 'result', result: 'result', introduction: 'intro', intro: 'intro',
    };
    let kind: string | undefined;
    if (kindMap[region]) kind = kindMap[region];
    else if (/^table_/.test(region) || /^fig_/.test(region)) kind = 'result';
    setPaperTarget({ kind, page, quote });
    setView('paper');
  }, []);

  const changeView = useCallback((v: ViewMode) => {
    setView(v);
    const qs = paperId ? `paper_id=${paperId}&view=${v}` : `view=${v}`;
    if (slug) router.replace(`/paper/${slug}?${qs}`, { scroll: false });
  }, [slug, paperId, router]);


  const load = useCallback(async () => {
    if (!slug && !paperId) return;
    setLoading(true);
    setError(undefined);
    try {
      let pid: number;
      let p: PaperOut | undefined;
      if (paperId) {
        pid = Number(paperId);
      } else if (slug) {
        const pl = await api.demoLoad(slug);
        pid = pl.id;
        p = pl;
      } else {
        return;
      }
      const d = await api.paperDetail(pid);
      setPaper(p ?? d);
      setDetail(d);
      setGraph(await api.graph(pid));
      setPresentation(await api.presentation(pid));
      setEvalData(await api.evaluation(pid));

      // live (real/uploaded) papers: content is filled by background ingest/process — poll
      let c = await api.claims(pid).catch(() => []);
      if (c.length === 0) {
        setProcessing(true);
        for (let i = 0; i < 40; i++) {
          await sleep(2500);
          c = await api.claims(pid).catch(() => []);
          if (c.length > 0) break;
        }
        setProcessing(false);
        setEvalData(await api.evaluation(pid));
      }
      setClaims(c);
    } catch (e: any) {
      console.error(e);
      setError(e?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [slug, paperId]);

  useEffect(() => {
    load();
  }, [load]);

  // 实时模式：按 job 状态展示当前处理阶段（可观测）
  useEffect(() => {
    if (!processing || !jobId || Number(jobId) === 0) return;
    const id = setInterval(async () => {
      try {
        const j = await api.jobStatus(Number(jobId));
        setStageLabel(j.stage_label);
        if (j.status === 'done' || j.status === 'failed') {
          clearInterval(id);
          setProcessing(false);
        }
      } catch {
        /* 继续轮询 */
      }
    }, 2500);
    return () => clearInterval(id);
  }, [processing, jobId]);

  const topClaim = useMemo(() => claims[0]?.claim_id, [claims]);

  const selectClaim = useCallback(
    async (claimId: string) => {
      setSelectedClaimId(claimId);
      if (!paper) return;
      const c = await api.claim(paper.id, claimId).catch(() => undefined);
      setClaimDetail(c);
    },
    [paper],
  );

  useEffect(() => {
    if (view === 'claim' && !selectedClaimId && topClaim) {
      selectClaim(topClaim);
    }
  }, [view, selectedClaimId, topClaim, selectClaim]);

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
          {detail && (
            <div className="hidden min-w-0 items-center gap-2 md:flex">
              <span className="max-w-[280px] truncate text-sm text-slate-300">{detail.title}</span>
            </div>
          )}
          <div className="ml-auto flex items-center gap-3">
            <Badge tone={isUpload ? 'cyan' : 'emerald'}>{isUpload ? '实时抽取' : '演示模式'}</Badge>
            <Badge tone="slate">{detail?.domain || '加载中'}</Badge>
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
          view === 'claim' ? 'lg:grid-cols-[minmax(0,1fr),340px]' : 'lg:grid-cols-1',
        )}>
          {/* Left + center */}
          <div className="min-w-0">
            {/* stage header */}
            <div className="mb-4 flex items-center justify-between">
              <div className="min-w-0">
                <Kicker>视觉演绎 · VISUAL STAGE</Kicker>
                <div className="mt-1 flex items-center gap-2">
                  <span className="text-lg font-semibold text-white">{detail.title}</span>
                </div>
              </div>
              <div className="hidden shrink-0 flex-wrap gap-1.5 sm:flex">
                {(detail.tags || []).slice(0, 3).map((t) => (
                  <Badge key={t} tone="slate">{t}</Badge>
                ))}
              </div>
            </div>

            {processing && (
              <div className="mb-4 flex items-center gap-2 rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-4 py-2.5 text-[13px] text-cyan-200">
                <Spinner className="h-4 w-4" />
                {stageLabel || '正在调用大模型抽取结构、断言与证据…'}
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
                {view === 'map' && <MapView detail={detail} accent={accent} onOpenSection={() => changeView('paper')} />}
                {view === 'method' && <MethodView detail={detail} accent={accent} />}
                {view === 'claim' && (
                  <ClaimView
                    detail={detail}
                    claims={claims}
                    selectedClaimId={selectedClaimId}
                    onSelect={(cid) => selectClaim(cid)}
                  />
                )}
                {view === 'graph' && <GraphView graph={graph} accent={accent} onClaimSelected={(cid) => { selectClaim(cid); changeView('claim'); }} />}
                {view === 'presenter' && <PresenterView presentation={presentation} accent={accent} detail={detail} claims={claims} />}
                {view === 'qa' && <QAView paperId={paper!.id} accent={accent} detail={detail} onJump={jumpToPaper} />}
                {view === 'eval' && <EvalView evalData={evalData} accent={accent} />}
                {view === 'paper' && <PaperView detail={detail} target={paperTarget} />}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Evidence rail (only in evidence view) */}
          {view === 'claim' && (
            <div className="lg:pl-5">
              <EvidenceRail claim={claimDetail} detail={detail} accent={accent} onJump={jumpToPaper} />
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
