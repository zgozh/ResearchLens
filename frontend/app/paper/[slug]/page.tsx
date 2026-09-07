'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, LayoutGrid, Workflow, FileSearch, Share2, Mic, MessageCircle, Gauge, BookOpen, ChevronRight,
} from 'lucide-react';
import { api } from '@/lib/api';
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
  { view: 'map', label: 'Paper Map', icon: LayoutGrid },
  { view: 'method', label: 'Method', icon: Workflow },
  { view: 'claim', label: 'Evidence', icon: FileSearch },
  { view: 'graph', label: 'Research Graph', icon: Share2 },
  { view: 'presenter', label: 'Presenter', icon: Mic },
  { view: 'qa', label: 'Grounded Q&A', icon: MessageCircle },
  { view: 'eval', label: 'Evaluation', icon: Gauge },
  { view: 'paper', label: 'Paper View', icon: BookOpen },
];

export default function Workspace() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug;
  const searchParams = useSearchParams();
  const router = useRouter();

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  const accent = detail?.accent || '#6366F1';

  const changeView = useCallback((v: ViewMode) => {
    setView(v);
    if (slug) router.replace(`/paper/${slug}?view=${v}`, { scroll: false });
  }, [slug, router]);


  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    setError(undefined);
    try {
      const p = await api.demoLoad(slug);
      setPaper(p);
      const [d, c, g, pr, ev] = await Promise.all([
        api.paperDetail(p.id),
        api.claims(p.id),
        api.graph(p.id),
        api.presentation(p.id),
        api.evaluation(p.id),
      ]);
      setDetail(d);
      setClaims(c);
      setGraph(g);
      setPresentation(pr);
      setEvalData(ev);
    } catch (e: any) {
      console.error(e);
      setError(e?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

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
            <Badge tone="emerald">demo-mode</Badge>
            <Badge tone="slate">{detail?.domain || 'loading'}</Badge>
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
            <Kicker>ERROR</Kicker>
            <p className="mt-2 text-sm text-rose-300">{error}</p>
            <Link href="/" className="mt-4 inline-block text-sm text-indigo-300">← 返回选择论文</Link>
          </GlassCard>
        </div>
      ) : detail ? (
        <div className="mx-auto grid max-w-[1500px] grid-cols-1 gap-0 px-5 py-5 lg:grid-cols-[minmax(0,1fr),340px]">
          {/* Left + center */}
          <div className="min-w-0">
            {/* stage header */}
            <div className="mb-4 flex items-center justify-between">
              <div className="min-w-0">
                <Kicker>VISUAL STAGE · 视觉演绎</Kicker>
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
                {view === 'graph' && <GraphView graph={graph} accent={accent} />}
                {view === 'presenter' && <PresenterView presentation={presentation} accent={accent} />}
                {view === 'qa' && <QAView paperId={paper!.id} accent={accent} />}
                {view === 'eval' && <EvalView evalData={evalData} accent={accent} />}
                {view === 'paper' && <PaperView detail={detail} />}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Evidence rail */}
          <div className="lg:pl-5">
            <EvidenceRail claim={claimDetail} detail={detail} accent={accent} />
          </div>
        </div>
      ) : null}

      {/* bottom timeline */}
      {detail && (
        <div className="sticky bottom-0 z-30 border-t border-[var(--line)] bg-[#060a13]/85 backdrop-blur-xl">
          <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-5 py-3">
            <div className="text-[11px] font-mono text-slate-500">NARRATIVE</div>
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
