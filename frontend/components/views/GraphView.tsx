'use client';

import { useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Circle, GitBranch, FlaskConical, Target, FileSearch, Image as ImageIcon, X, Quote, ArrowRight } from 'lucide-react';
import type { GraphOut, GraphNode, ClaimOut } from '@/lib/types';
import { Badge, GlassCard, Kicker } from '@/components/ui';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';

const KIND_X: Record<string, number> = { problem: 0, method: 1, experiment: 2, claim: 3, evidence: 4, media: 5 };
const KIND_COLOR: Record<string, string> = {
  problem: '#F43F5E', method: '#6366F1', experiment: '#22D3EE', claim: '#34D399', evidence: '#F59E0B', media: '#A78BFA',
};

function KindIcon({ kind }: { kind: string }) {
  const map: Record<string, any> = { problem: Target, method: GitBranch, experiment: FlaskConical, claim: Circle, evidence: FileSearch, media: ImageIcon };
  const I = map[kind] || Circle;
  return <I className="h-3.5 w-3.5" />;
}

function LensNode({ data }: NodeProps) {
  const kind = (data?.kind ?? 'problem') as string;
  const color = KIND_COLOR[kind] || '#94A3B8';
  const props = (data?.props ?? {}) as Record<string, any>;
  const label = (data?.label ?? '') as string;
  const claimId = data?.claim_id as string | undefined;
  return (
    <div className="relative w-[190px] rounded-xl border bg-[#0c1830] p-3"
      style={{ borderColor: `${color}44`, boxShadow: `0 12px 30px -18px ${color}66` }}>
      <Handle type="target" position={Position.Left} className="!bg-slate-500 !border-transparent" />
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: `${color}22`, color }}>
          <KindIcon kind={kind} />
        </span>
        <span className="text-[12px] font-semibold uppercase tracking-wide" style={{ color }}>{label}</span>
      </div>
      {props.text && <p className="mt-2 text-[11px] leading-snug text-slate-300">{props.text as string}</p>}
      {claimId && (
        <div className="mt-2 inline-flex rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{claimId}</div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-slate-500 !border-transparent" />
    </div>
  );
}

const nodeTypes = { lens: LensNode };
const NODE_KIND_LABEL: Record<string, string> = { problem: '问题', method: '方法', experiment: '实验', claim: '断言', evidence: '证据', media: '图表' };

export function GraphView({ graph, accent, onClaimSelected, paperId }: {
  graph: GraphOut; accent: string; paperId?: number;
  onClaimSelected?: (claimId: string, evidenceIdx?: number) => void;
}) {
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [claimDetail, setClaimDetail] = useState<ClaimOut | null>(null);
  const [loadingClaim, setLoadingClaim] = useState(false);
  const [expandEv, setExpandEv] = useState(false);

  const nodes = useMemo<Node[]>(() => {
    const perKind: Record<string, number> = {};
    return graph.nodes.map((n) => {
      const kind = n.kind;
      const col = KIND_X[kind] ?? 1;
      const row = perKind[kind] ?? 0;
      perKind[kind] = row + 1;
      return {
        id: n.id, type: 'lens',
        position: { x: col * 250, y: row * 90 },
        data: { label: n.label, kind: n.kind, props: n.props, claim_id: n.props?.claim_id },
      };
    });
  }, [graph.nodes]);

  const edges = useMemo<Edge[]>(() => {
    return graph.edges.map((e) => ({
      id: e.id, source: e.source, target: e.target, label: e.label, animated: true,
      style: { stroke: `${accent}88`, strokeWidth: 1.4 },
      labelStyle: { fill: '#94A3B8', fontSize: 10 },
      labelBgStyle: { fill: '#0c1830', fillOpacity: 0.9 }, labelBgPadding: [4, 2] as [number, number], labelBgBorderRadius: 4,
    }));
  }, [graph.edges, accent]);

  const onNodeClick = (_: any, node: Node) => {
    const found = graph.nodes.find((n) => n.id === node.id) || null;
    setSelected(found);
    setExpandEv(false);
    // 断言节点：同步拉取完整证据，供图谱内直接弹看
    if (found?.kind === 'claim' && found.props?.claim_id && paperId) {
      setLoadingClaim(true);
      setClaimDetail(null);
      api.claim(paperId, found.props.claim_id as string)
        .then((c) => setClaimDetail(c))
        .catch(() => setClaimDetail(null))
        .finally(() => setLoadingClaim(false));
    } else {
      setClaimDetail(null);
    }
  };

  return (
    <GlassCard className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Kicker>研究图谱 · RESEARCH GRAPH</Kicker>
          <p className="mt-1 text-sm text-slate-400">问题 → 方法 → 实验 → 断言 → 证据 → 图表。点击节点查看详情。</p>
        </div>
        <div className="hidden items-center gap-3 font-mono text-[10px] text-slate-500 sm:flex">
          {['problem', 'method', 'experiment', 'claim', 'evidence', 'media'].map((k) => (
            <span key={k} className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: KIND_COLOR[k] }} />
              {k}
            </span>
          ))}
        </div>
      </div>
      <div className="h-[440px] overflow-hidden rounded-xl border border-[var(--line)] bg-[#081020]">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
          fitViewOptions={{ padding: 0.25 }} proOptions={{ hideAttribution: true }}
          onNodeClick={onNodeClick}>
          <Background color="#1e293b" gap={40} />
          <Controls />
          <MiniMap nodeColor={() => '#6366F1'} maskColor="rgba(6,10,19,0.7)" pannable zoomable />
        </ReactFlow>
      </div>

      {/* 节点详情 */}
      {selected ? (
        <div className="mt-4 rounded-2xl border border-[var(--line)] bg-white/[0.02] p-4">
          <div className="flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: `${KIND_COLOR[selected.kind] || accent}22`, color: KIND_COLOR[selected.kind] || accent }}>
              <KindIcon kind={selected.kind} />
            </span>
            <span className="text-sm font-semibold text-white">{selected.label}</span>
            <Badge tone="slate">{NODE_KIND_LABEL[selected.kind] || selected.kind}</Badge>
            <button onClick={() => setSelected(null)} className="ml-auto grid h-6 w-6 place-items-center rounded-md text-slate-500 hover:text-white">
              <X className="h-4 w-4" />
            </button>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-slate-300">{selected.props?.text || '—'}</p>
          {selected.kind === 'claim' && selected.props?.claim_id && (
            <div className="mt-3 space-y-3">
              {/* 图谱内直接弹出该断言的证据 */}
              {loadingClaim && <div className="text-[12px] text-slate-500">正在加载证据…</div>}
              {claimDetail && (
                <div className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <Badge tone="slate">该断言的证据</Badge>
                    <span className="font-mono text-[10px] text-slate-500">{claimDetail.evidence?.length || 0} 条</span>
                  </div>
                  <div className="space-y-2">
                    {claimDetail.evidence?.length === 0 && (
                      <p className="text-[11px] text-amber-300/80">该断言未绑定证据（Evidence Gate）。</p>
                    )}
                    {claimDetail.evidence?.map((e, i) => (
                      <div key={i} className="rounded-lg bg-white/[0.03] px-2.5 py-1.5">
                        <div className="flex items-center gap-2 text-[10px] text-slate-500">
                          <Quote className="h-3 w-3 text-slate-600" />
                          <span className="font-mono">p.{e.page} · {e.region}</span>
                        </div>
                        <p className={cn('mt-1 text-[11.5px] text-slate-300', !expandEv && 'line-clamp-2')}>{e.quote || e.text}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <button onClick={() => setExpandEv((v) => !v)}
                  className="rounded-md bg-white/[0.06] px-2.5 py-1 text-[11px] font-medium text-slate-300 transition hover:bg-white/10">
                  {expandEv ? '收起证据' : '在本页展开证据'}
                </button>
                {claimDetail && claimDetail.evidence?.length > 0 && (
                  <button onClick={() => onClaimSelected?.(selected.props!.claim_id as string, 0)}
                    className="inline-flex items-center gap-1 rounded-md bg-indigo-500/20 px-2.5 py-1 text-[11px] font-medium text-indigo-200 transition hover:bg-indigo-500/30">
                    <ArrowRight className="h-3 w-3" /> 定位到该证据
                  </button>
                )}
              </div>
            </div>
          )}
          {selected.kind === 'evidence' && selected.props?.claim_id && (
            <div className="mt-2 inline-flex items-center gap-2">
              <span className="inline-flex rounded-md bg-white/[0.05] px-2 py-1 font-mono text-[11px] text-slate-400">
                claim_id: {selected.props.claim_id}
              </span>
              <button onClick={() => onClaimSelected?.(selected.props!.claim_id as string)}
                className="rounded-md bg-indigo-500/20 px-2.5 py-1 text-[11px] font-medium text-indigo-200 transition hover:bg-indigo-500/30">
                查看该断言的证据 →
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="mt-4 rounded-2xl border border-dashed border-[var(--line)] p-3 text-center text-[12px] text-slate-600">
          点击任意节点，展开其详情与关联证据。
        </div>
      )}
    </GlassCard>
  );
}
