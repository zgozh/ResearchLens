'use client';

import { useMemo } from 'react';
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
import { Circle, GitBranch, FlaskConical, Target, FileSearch } from 'lucide-react';
import type { GraphOut } from '@/lib/types';
import { GlassCard, Kicker } from '@/components/ui';

const KIND_X: Record<string, number> = {
  problem: 0,
  method: 1,
  experiment: 2,
  claim: 3,
  evidence: 4,
};

const KIND_COLOR: Record<string, string> = {
  problem: '#F43F5E',
  method: '#6366F1',
  experiment: '#22D3EE',
  claim: '#34D399',
  evidence: '#F59E0B',
};

function KindIcon({ kind }: { kind: string }) {
  const map: Record<string, any> = {
    problem: Target,
    method: GitBranch,
    experiment: FlaskConical,
    claim: Circle,
    evidence: FileSearch,
  };
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
    <div
      className="relative w-[190px] rounded-xl border bg-[#0c1830] p-3"
      style={{ borderColor: `${color}44`, boxShadow: `0 12px 30px -18px ${color}66` }}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-500 !border-transparent" />
      <div className="flex items-center gap-2">
        <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: `${color}22`, color }}>
          <KindIcon kind={kind} />
        </span>
        <span className="text-[12px] font-semibold uppercase tracking-wide" style={{ color }}>
          {label}
        </span>
      </div>
      {props.text && <p className="mt-2 text-[11px] leading-snug text-slate-300">{props.text as string}</p>}
      {claimId && (
        <div className="mt-2 inline-flex rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
          {claimId}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-slate-500 !border-transparent" />
    </div>
  );
}

const nodeTypes = { lens: LensNode };

export function GraphView({ graph, accent }: { graph: GraphOut; accent: string }) {
  const nodes = useMemo<Node[]>(() => {
    const perKind: Record<string, number> = {};
    return graph.nodes.map((n) => {
      const kind = n.kind;
      const col = KIND_X[kind] ?? 1;
      const row = perKind[kind] ?? 0;
      perKind[kind] = row + 1;
      return {
        id: n.id,
        type: 'lens',
        position: { x: col * 250, y: row * 90 },
        data: { label: n.label, kind: n.kind, props: n.props, claim_id: n.props?.claim_id },
      };
    });
  }, [graph.nodes]);

  const edges = useMemo<Edge[]>(() => {
    return graph.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.label,
      animated: true,
      style: { stroke: `${accent}88`, strokeWidth: 1.4 },
      labelStyle: { fill: '#94A3B8', fontSize: 10 },
      labelBgStyle: { fill: '#0c1830', fillOpacity: 0.9 },
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 4,
    }));
  }, [graph.edges, accent]);

  return (
    <GlassCard className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Kicker>RESEARCH GRAPH · 研究图谱</Kicker>
          <p className="mt-1 text-sm text-slate-400">
            Problem → Method → Experiment → Claim → Evidence，每个断言绑定到具体证据。
          </p>
        </div>
        <div className="hidden items-center gap-3 font-mono text-[10px] text-slate-500 sm:flex">
          {['problem', 'method', 'experiment', 'claim', 'evidence'].map((k) => (
            <span key={k} className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: KIND_COLOR[k] }} />
              {k}
            </span>
          ))}
        </div>
      </div>
      <div className="h-[440px] overflow-hidden rounded-xl border border-[var(--line)] bg-[#081020]">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1e293b" gap={40} />
          <Controls />
          <MiniMap
            nodeColor={() => '#6366F1'}
            maskColor="rgba(6,10,19,0.7)"
            pannable
            zoomable
          />
        </ReactFlow>
      </div>
    </GlassCard>
  );
}
