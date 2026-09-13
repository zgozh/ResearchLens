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
import { Circle, GitBranch, FlaskConical, Target, FileSearch, Image as ImageIcon, X, Quote, ArrowRight, Loader2 } from 'lucide-react';
import type { GraphOut, GraphNode, ClaimOut } from '@/lib/types';
import { Badge, GlassCard, Kicker } from '@/components/ui';
import { api } from '@/lib/api';
import { SourceMedia } from '@/components/source/SourceMedia';
import { MathText } from '@/components/MathText';
import { VerdictBadge } from '@/components/evidence/VerdictBadge';
import { layoutGraph } from '@/lib/graphLayout';
import { cn } from '@/lib/cn';

// D29 修复：此前只写死 problem/method/experiment/claim/evidence/media 六类，
// 而后端实际会给 `limitation`/`result`/`intro` 等 kind（claim 节点按断言类型命名），
// 未命中的 kind 会全部落进第 1 列且共用灰色 —— 看起来就是"节点不全、连线不齐"。
// 现在**按图中真实出现的 kind 动态生成列位/配色/中文名**，任何新 kind 都有位置。
const BASE_COLOR: Record<string, string> = {
  problem: '#F43F5E', method: '#6366F1', experiment: '#22D3EE', claim: '#34D399',
  evidence: '#F59E0B', media: '#A78BFA', limitation: '#FB923C', result: '#34D399',
  intro: '#A78BFA', body: '#94A3B8', conclusion: '#64748B', context: '#38BDF8',
};
const PALETTE = ['#6366F1', '#22D3EE', '#34D399', '#F59E0B', '#A78BFA', '#F43F5E', '#FB923C', '#38BDF8'];
const KIND_LABEL_CN: Record<string, string> = {
  problem: '问题', method: '方法', experiment: '实验', claim: '断言', evidence: '证据',
  media: '图表', limitation: '局限', result: '结果', intro: '背景', body: '正文',
  conclusion: '结论', context: '上下文',
};

function KindIcon({ kind }: { kind: string }) {
  const map: Record<string, any> = { problem: Target, method: GitBranch, experiment: FlaskConical, claim: Circle, evidence: FileSearch, media: ImageIcon, limitation: Target };
  const I = map[kind] || Circle;
  return <I className="h-3.5 w-3.5" />;
}

function LensNode({ data }: NodeProps) {
  const kind = (data?.kind ?? 'problem') as string;
  const color = (data?.color as string) || BASE_COLOR[kind] || '#94A3B8';
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
      {props.text && <MathText text={props.text as string} className="mt-2 block text-[11px] leading-snug text-slate-300" />}
      {!props.text && label && <p className="mt-2 line-clamp-2 text-[11px] leading-snug text-slate-400">{label}</p>}
      {claimId && (
        <div className="mt-2 inline-flex rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{claimId}</div>
      )}
      <Handle type="source" position={Position.Right} className="!bg-slate-500 !border-transparent" />
    </div>
  );
}

const nodeTypes = { lens: LensNode };

export function GraphView({ graph, accent, onClaimSelected, paperId, onNavigate, scope }: {
  graph: GraphOut; accent: string; paperId?: number;
  onClaimSelected?: (claimId: string, evidenceIdx?: number) => void;
  /** 定位到原文（图表/证据节点要用：ADR-0058） */
  onNavigate?: (target: { anchor_id: string; segment_index?: number }) => void;
  scope?: { paper_id: number; revision_id: string };
}) {
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [claimDetail, setClaimDetail] = useState<ClaimOut | null>(null);
  const [loadingClaim, setLoadingClaim] = useState(false);
  const [expandEv, setExpandEv] = useState(false);
  // 图表节点：按需取**这张图本身**（assets 与视图策略都在这个接口里）
  const [mediaDetail, setMediaDetail] = useState<any | null>(null);
  const [loadingMedia, setLoadingMedia] = useState(false);
  // 只有**确实有可展开的长证据**时才显示"展开证据"（否则点了没任何变化）。
  const hasLongEvidence = useMemo(() => {
    const list = claimDetail?.evidence ?? [];
    return list.some((e: any) => ((e?.quote || e?.text || '') as string).length > 60);
  }, [claimDetail]);

  // 按图中真实出现的 kind 生成列位/配色/中文名（新 kind 自动有位有颜色）
  const kindMeta = useMemo(() => {
    const order: string[] = [];
    for (const n of graph.nodes) if (n.kind && !order.includes(n.kind)) order.push(n.kind);
    const x: Record<string, number> = {};
    const color: Record<string, string> = {};
    const label: Record<string, string> = {};
    order.forEach((k, i) => {
      x[k] = i;
      color[k] = BASE_COLOR[k] ?? PALETTE[i % PALETTE.length];
      label[k] = KIND_LABEL_CN[k] ?? k;
    });
    return { order, x, color, label };
  }, [graph.nodes]);

  // M8：分层布局只算一次（泳道 + 拓扑层 + 保证不重叠），节点位置与边标签共用结果。
  // 旧实现是 `col*250, row*90` 的手写网格 —— 行距 90 小于节点实际高度（~104），
  // 同列节点互相压住，连线与关系名字都被盖掉（用户反馈"全堆在一起、看不到关系名字"）。
  const layout = useMemo(
    () =>
      layoutGraph(
        graph.nodes.map((n) => ({ id: n.id, kind: n.kind })),
        graph.edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
      ),
    [graph.nodes, graph.edges],
  );

  const nodes = useMemo<Node[]>(
    () =>
      graph.nodes.map((n) => {
        const kind = n.kind;
        const pos = layout.positions[n.id] ?? { x: 0, y: 0, lane: kind, layer: 0 };
        return {
          id: n.id, type: 'lens',
          position: { x: pos.x, y: pos.y },
          data: {
            label: n.label, kind, props: n.props, claim_id: n.props?.claim_id,
            color: kindMeta.color[kind],
          },
        };
      }),
    [graph.nodes, kindMeta, layout],
  );

  const edges = useMemo<Edge[]>(() => {
    return graph.edges.map((e) => {
      // 关系名字只在**不压节点**时显示（避不开就宁可不显示，不可遮挡）
      const lp = layout.edgeLabels[e.id];
      const label = e.label && lp && !lp.hidden ? e.label : undefined;
      return {
        id: e.id, source: e.source, target: e.target, label, animated: true,
        style: { stroke: `${accent}88`, strokeWidth: 1.4 },
        labelStyle: { fill: '#94A3B8', fontSize: 10 },
        labelBgStyle: { fill: '#0c1830', fillOpacity: 0.92 },
        labelBgPadding: [4, 2] as [number, number], labelBgBorderRadius: 4,
      };
    });
  }, [graph.edges, accent, layout]);

  const onNodeClick = (_: any, node: Node) => {
    const found = graph.nodes.find((n) => n.id === node.id) || null;
    setSelected(found);
    setExpandEv(false);
    setMediaDetail(null);
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
    // 图表节点：取出**具体这张图/表**（此前只显示一个 id 片段，用户反馈"没有给具体的图表"）
    if (found?.kind === 'media' && found.props?.media_id && paperId) {
      setLoadingMedia(true);
      api.getMedia(paperId, String(found.props.media_id), scope?.revision_id)
        .then((m) => setMediaDetail(m))
        .catch(() => setMediaDetail(null))
        .finally(() => setLoadingMedia(false));
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
          {kindMeta.order.length === 0 ? (
            <span>暂无节点</span>
          ) : kindMeta.order.map((k) => (
            <span key={k} className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: kindMeta.color[k] }} />
              {kindMeta.label[k]}
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
            <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: `${kindMeta.color[selected.kind] || accent}22`, color: kindMeta.color[selected.kind] || accent }}>
              <KindIcon kind={selected.kind} />
            </span>
            <span className="text-sm font-semibold text-white">{selected.label}</span>
            <Badge tone="slate">{kindMeta.label[selected.kind] || selected.kind}</Badge>
            <button onClick={() => setSelected(null)} className="ml-auto grid h-6 w-6 place-items-center rounded-md text-slate-500 hover:text-white">
              <X className="h-4 w-4" />
            </button>
          </div>
          {/* D29 修复：此前读 props.text（后端从不产出该键）→ 恒显示 "—"。
              改为按节点类型给出真实内容：断言节点展示陈述正文，其余展示可用属性。 */}
          {selected.kind === 'claim' && claimDetail?.statement ? (
            <p className="mt-2 text-sm leading-relaxed text-slate-300">{claimDetail.statement}</p>
          ) : selected.kind === 'claim' && loadingClaim ? (
            <p className="mt-2 text-sm text-slate-500">正在加载断言内容…</p>
          ) : (
            (() => {
              const facts = Object.entries(selected.props || {}).filter(([k, v]) => {
                if (k === 'claim_id') return false;
                if (v === null || v === undefined || v === '') return false;
                if (Array.isArray(v)) return v.length > 0;
                return true;
              });
              if (facts.length === 0) {
                return <p className="mt-2 text-sm text-slate-500">该节点没有附加属性。</p>;
              }
              return (
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-slate-400">
                  {facts.map(([k, v]) => (
                    <span key={k}>
                      {k} · {Array.isArray(v) ? `${v.length} 项` : String(v)}
                    </span>
                  ))}
                </div>
              );
            })()
          )}
          {selected.kind === 'claim' && selected.props?.claim_id && (
            <div className="mt-3 space-y-3">
              {/* 图谱内直接弹出该断言的证据 */}
              {loadingClaim && <div className="text-[12px] text-slate-500">正在加载证据…</div>}
              {!loadingClaim && !claimDetail && (
                <p className="text-[11px] text-amber-300/80">读取该断言详情失败，可点下方按钮在左侧证据链中查看。</p>
              )}
              {claimDetail && (
                <div className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <Badge tone="slate">该断言的证据</Badge>
                    <span className="font-mono text-[10px] text-slate-500">{claimDetail.evidence?.length || 0} 条</span>
                    {claimDetail.verification_status && (
                      <span className="ml-auto font-mono text-[10px] text-slate-500">
                        {claimDetail.verification_status}
                      </span>
                    )}
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
                          {/* 证据的**支撑结论**要如实显示：此前任何非 supports 都不显示状态 */}
                          <span className="font-mono">
                            {e.verification_status === 'supports' ? '· 支持'
                              : e.verification_status === 'contradicts' ? '· 反驳'
                                : e.verification_status === 'insufficient' ? '· 证据不足'
                                  : e.verification_status ? `· ${e.verification_status}` : ''}
                          </span>
                        </div>
                        <MathText
                          text={e.quote || e.text}
                          className={cn('mt-1 block whitespace-pre-wrap text-[11.5px] leading-5 text-slate-300',
                            !expandEv && hasLongEvidence && 'line-clamp-2')}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                {/* 只有**确实有可展开内容**时才给这个按钮：此前无条件渲染，
                    证据本身不足两行时点了没有任何变化（用户反馈"点了没反应"）。 */}
                {claimDetail && hasLongEvidence && (
                  <button onClick={() => setExpandEv((v) => !v)}
                    className="rounded-md bg-white/[0.06] px-2.5 py-1 text-[11px] font-medium text-slate-300 transition hover:bg-white/10">
                    {expandEv ? '收起证据' : '在本页展开证据'}
                  </button>
                )}
                {claimDetail && claimDetail.evidence?.length > 0 && (
                  <button onClick={() => onClaimSelected?.(selected.props!.claim_id as string, 0)}
                    className="inline-flex items-center gap-1 rounded-md bg-indigo-500/20 px-2.5 py-1 text-[11px] font-medium text-indigo-200 transition hover:bg-indigo-500/30">
                    <ArrowRight className="h-3 w-3" /> 定位到该证据
                  </button>
                )}
                <button onClick={() => onClaimSelected?.(selected.props!.claim_id as string, 0)}
                  className="inline-flex items-center gap-1 rounded-md bg-white/[0.06] px-2.5 py-1 text-[11px] font-medium text-slate-300 transition hover:bg-white/10">
                  <FileSearch className="h-3 w-3" /> 在证据链中打开
                </button>
              </div>
            </div>
          )}
          {selected.kind !== 'claim' && (
            <div className="mt-3 space-y-3">
              {/* 图表节点：显示**这张图表本身**（图片 + 编号 + caption），
                  此前只有一个 media id 片段（用户反馈"没有给出具体的图表"）。 */}
              {selected.kind === 'media' && (
                <div className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-3">
                  <div className="mb-2 flex items-center gap-2 text-[11px] text-slate-400">
                    <ImageIcon className="h-3.5 w-3.5" />
                    <span className="font-medium text-slate-200">
                      {selected.props?.media_kind === 'table' ? '表' : '图'}
                      {selected.props?.legacy_no != null ? ` ${selected.props.legacy_no}` : ''}
                    </span>
                    {selected.props?.caption && (
                      <MathText text={String(selected.props.caption).slice(0, 60)} className="truncate text-slate-500" />
                    )}
                  </div>
                  {loadingMedia ? (
                    <div className="flex h-24 items-center justify-center text-[11px] text-slate-500">
                      <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> 正在取图表…
                    </div>
                  ) : mediaDetail?.media ? (
                    // **用应用里统一的来源媒体组件**（ADR-0062）：它按视图策略决定展示层级 ——
                    // 有原图给原图、表格/公式走提取表示、缺原件回退整页预览、都没有就**明确说明**。
                    // 此前这里直接 `<img src=assets[0].id>`，而 assets[0] 常常是
                    // ``kind="source_pdf"``（实测 paper 1 的表媒体 original_asset_ids 为空），
                    // 于是把 PDF 塞进 <img> → 用户看到的"什么都没有的断裂图"。
                    <div className="text-slate-900">
                      <SourceMedia
                        media={mediaDetail.media}
                        assets={mediaDetail.assets ?? []}
                        onOpen={() => {}}
                        onNavigate={(t) => onNavigate?.({
                          anchor_id: t.anchor_id, segment_index: t.segment_index ?? 0,
                        })}
                      />
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-500">未能取到该图表资产。</p>
                  )}
                </div>
              )}
              {/* 证据节点：显示**判定 + 原文引文 + 页码**，并真的能定位过去。
                  此前只有一个"可定位锚点 1 个"的标签（用户反馈"说不出任何内容"）。 */}
              {selected.kind === 'evidence' && (
                <div className="rounded-xl border border-[var(--line)] bg-white/[0.02] p-3">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px]">
                    <span className={cn('rounded-md px-1.5 py-0.5 font-medium',
                      selected.props?.support_status === 'supports'
                        ? 'bg-emerald-500/15 text-emerald-300'
                        : selected.props?.support_status === 'contradicts'
                          ? 'bg-rose-500/15 text-rose-300'
                          : 'bg-amber-500/15 text-amber-300')}>
                      {selected.props?.support_status === 'supports' ? '支持'
                        : selected.props?.support_status === 'contradicts' ? '反驳'
                          : selected.props?.support_status === 'insufficient' ? '证据不足'
                            : '未判定'}
                    </span>
                    {/* R4-M9：四分类徽标（与证据链/抽屉**同源**，可展开看后端理由）。
                        此前图谱上只有"支持/反驳/证据不足/未判定"这一个词，
                        用户看不到**为什么** —— `support_status` 说不出成因。 */}
                    <VerdictBadge validation={selected.props?.validation} />
                    {selected.props?.page ? (
                      <span className="font-mono text-slate-400">原文第 {selected.props.page} 页</span>
                    ) : null}
                  </div>
                  <p className="whitespace-pre-wrap text-[11.5px] leading-5 text-slate-300">
                    {selected.props?.quote || selected.label || '（该证据没有留下原文片段）'}
                  </p>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                {/* 证据/图表/方法节点此前只有一行 props 事实，没有"能去哪儿"的动作 */}
                {(selected.props?.claim_id) && (
                  <button
                    onClick={() => onClaimSelected?.((selected.props?.claim_id) as string)}
                    className="inline-flex items-center gap-1 rounded-md bg-indigo-500/20 px-2.5 py-1 text-[11px] font-medium text-indigo-200 transition hover:bg-indigo-500/30">
                    <ArrowRight className="h-3 w-3" /> 查看所属断言的证据
                  </button>
                )}
                {/* **真的能定位**：锚点 → 阅读器跳页（此前只是个静态标签） */}
                {(selected.props?.anchor_id || (selected.props?.anchor_ids?.length ?? 0) > 0) && onNavigate && (
                  <button
                    onClick={() => {
                      const anchorId = String(
                        selected.props?.anchor_id || selected.props?.anchor_ids?.[0] || '',
                      );
                      if (anchorId) onNavigate({ anchor_id: anchorId, segment_index: 0 });
                    }}
                    className="inline-flex items-center gap-1 rounded-md bg-white/[0.06] px-2.5 py-1 text-[11px] font-medium text-slate-200 transition hover:bg-white/10">
                    <FileSearch className="h-3 w-3" />
                    在原文中定位{selected.props?.page ? `（第 ${selected.props.page} 页）` : ''}
                  </button>
                )}
                {selected.kind === 'media' && selected.props?.media_id && (
                  <span className="rounded-md bg-white/[0.05] px-2 py-1 font-mono text-[10px] text-slate-500">
                    media: {String(selected.props.media_id).slice(0, 8)}…
                  </span>
                )}
              </div>
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
