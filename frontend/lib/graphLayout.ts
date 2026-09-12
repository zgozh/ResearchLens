// 研究图谱分层布局（REFACTOR_PLAN M8）。
//
// 为什么要重写：旧实现是 `x: col*250, y: row*90` 的**手写网格**——列间距 250、行间距 90，
// 而节点实际高度约 96–120px（190 宽、带内边距与两三行文字）。于是同一列里的节点**纵向重叠**，
// 连线被节点盖住、边标签也看不见；实测一篇论文 39 节点/33 边时整个图是一团。
//
// 本模块是**纯函数 + 零依赖**（不引 ELK/dagre/cytoscape，遵守 REFACTOR_PLAN §2.2）：
//   1. 泳道（lane）：按 kind 分列，列宽 = 节点宽 + laneGap，**列间永不相交**；
//   2. 层（layer）：按边的拓扑序取最长路径深度，层内再按原始顺序，
//      同列节点按 (layer, 原序) 排列 —— 相关节点挨在一起，连线更短；
//   3. 位置：y = 行号 × (节点高 + nodeGap)，**行距大于节点高** → 全局无重叠（有测试断言）；
//   4. 边标签：放连线中点；与任何节点包围盒相交时沿纵向逐级避让，避不开就标记 hidden
//      （宁可不显示，也不让文字压在节点上）。
//
// 确定性：同输入同输出（无随机、无时间），便于快照测试。

export interface LayoutNodeInput {
  id: string;
  kind: string;
  width?: number;
  height?: number;
}

export interface LayoutEdgeInput {
  id: string;
  source: string;
  target: string;
  label?: string | null;
}

export interface LayoutOptions {
  nodeWidth?: number;
  nodeHeight?: number;
  /** 泳道（列）间距。 */
  laneGap?: number;
  /** 同列内节点纵向间距。 */
  nodeGap?: number;
}

export interface LayoutPosition {
  x: number;
  y: number;
  lane: string;
  layer: number;
}

export interface LayoutResult {
  positions: Record<string, LayoutPosition>;
  edgeLabels: Record<string, { x: number; y: number; hidden: boolean }>;
  lanes: string[];
  bounds: { width: number; height: number };
}

const DEFAULTS = { nodeWidth: 190, nodeHeight: 104, laneGap: 80, nodeGap: 28 };
/** 边标签的近似包围盒（宽 × 高）。 */
const LABEL_W = 72;
const LABEL_H = 18;
/** 标签避让的纵向候选偏移（像素）。 */
const LABEL_OFFSETS = [0, 24, -24, 48, -48, 72, -72, 96, -96];

function resolve(opts: LayoutOptions) {
  return {
    nodeWidth: opts.nodeWidth ?? DEFAULTS.nodeWidth,
    nodeHeight: opts.nodeHeight ?? DEFAULTS.nodeHeight,
    laneGap: opts.laneGap ?? DEFAULTS.laneGap,
    nodeGap: opts.nodeGap ?? DEFAULTS.nodeGap,
  };
}

/** 拓扑分层：Kahn 最长路径；有环时剩余节点按当前层号兜底（不死循环）。 */
function topoLayers(ids: string[], edges: LayoutEdgeInput[]): Map<string, number> {
  const layer = new Map<string, number>();
  const indeg = new Map<string, number>();
  const out = new Map<string, string[]>();
  for (const id of ids) {
    indeg.set(id, 0);
    out.set(id, []);
  }
  for (const e of edges) {
    if (!indeg.has(e.source) || !indeg.has(e.target) || e.source === e.target) continue;
    out.get(e.source)!.push(e.target);
    indeg.set(e.target, indeg.get(e.target)! + 1);
  }
  const queue = ids.filter((id) => indeg.get(id) === 0);
  queue.forEach((id) => layer.set(id, 0));
  let head = 0;
  let maxLayer = 0;
  while (head < queue.length) {
    const id = queue[head++];
    const base = layer.get(id) ?? 0;
    maxLayer = Math.max(maxLayer, base);
    for (const next of out.get(id)!) {
      layer.set(next, Math.max(layer.get(next) ?? 0, base + 1));
      const left = indeg.get(next)! - 1;
      indeg.set(next, left);
      if (left === 0) queue.push(next);
    }
  }
  // 环里的节点（没进过队列）：按出现顺序依次加一层，保证不重叠即可
  let tail = maxLayer + 1;
  for (const id of ids) {
    if (!layer.has(id)) layer.set(id, tail++);
  }
  return layer;
}

export function layoutGraph(
  nodes: LayoutNodeInput[],
  edges: LayoutEdgeInput[],
  opts: LayoutOptions = {},
): LayoutResult {
  const cfg = resolve(opts);
  const lanes: string[] = [];
  for (const n of nodes) if (!lanes.includes(n.kind)) lanes.push(n.kind);

  const layer = topoLayers(nodes.map((n) => n.id), edges);
  const order = new Map(nodes.map((n, i) => [n.id, i]));

  const byLane = new Map<string, LayoutNodeInput[]>();
  for (const n of nodes) {
    if (!byLane.has(n.kind)) byLane.set(n.kind, []);
    byLane.get(n.kind)!.push(n);
  }

  const positions: Record<string, LayoutPosition> = {};
  let rows = 0;
  lanes.forEach((kind, laneIndex) => {
    const list = byLane.get(kind) ?? [];
    list.sort(
      (a, b) =>
        (layer.get(a.id)! - layer.get(b.id)!) || (order.get(a.id)! - order.get(b.id)!),
    );
    list.forEach((n, row) => {
      positions[n.id] = {
        x: laneIndex * (cfg.nodeWidth + cfg.laneGap),
        y: row * (cfg.nodeHeight + cfg.nodeGap),
        lane: kind,
        layer: layer.get(n.id) ?? 0,
      };
    });
    rows = Math.max(rows, list.length);
  });

  // ---- 边标签：中点 + 节点避让
  const boxes = Object.entries(positions).map(([id, p]) => ({
    id,
    x1: p.x,
    y1: p.y,
    x2: p.x + cfg.nodeWidth,
    y2: p.y + cfg.nodeHeight,
  }));
  const hits = (x: number, y: number) => {
    const lx1 = x - LABEL_W / 2;
    const ly1 = y - LABEL_H / 2;
    const lx2 = x + LABEL_W / 2;
    const ly2 = y + LABEL_H / 2;
    return boxes.some((b) => lx1 < b.x2 && b.x1 < lx2 && ly1 < b.y2 && b.y1 < ly2);
  };

  const edgeLabels: Record<string, { x: number; y: number; hidden: boolean }> = {};
  for (const e of edges) {
    const a = positions[e.source];
    const b = positions[e.target];
    if (!a || !b) {
      edgeLabels[e.id] = { x: 0, y: 0, hidden: true };
      continue;
    }
    const midX = (a.x + cfg.nodeWidth / 2 + b.x + cfg.nodeWidth / 2) / 2;
    const midY = (a.y + cfg.nodeHeight / 2 + b.y + cfg.nodeHeight / 2) / 2;
    // 同一对节点间可能有多条边：按边序错开，避免标签互相压住
    const placed = LABEL_OFFSETS.map((dy) => ({ x: midX, y: midY + dy })).find(
      (p) => !hits(p.x, p.y),
    );
    edgeLabels[e.id] = placed
      ? { x: placed.x, y: placed.y, hidden: false }
      : { x: midX, y: midY, hidden: true };
  }

  return {
    positions,
    edgeLabels,
    lanes,
    bounds: {
      width: Math.max(1, lanes.length * (cfg.nodeWidth + cfg.laneGap) - cfg.laneGap),
      height: Math.max(1, rows * (cfg.nodeHeight + cfg.nodeGap) - cfg.nodeGap),
    },
  };
}

/** 供测试/调用方复用的包围盒相交判定（节点级）。 */
export function nodeBoxesOverlap(
  positions: Record<string, LayoutPosition>,
  nodeWidth = DEFAULTS.nodeWidth,
  nodeHeight = DEFAULTS.nodeHeight,
  pad = 0,
): boolean {
  const list = Object.values(positions);
  for (let i = 0; i < list.length; i += 1) {
    for (let j = i + 1; j < list.length; j += 1) {
      const a = list[i]!;
      const b = list[j]!;
      if (
        a.x < b.x + nodeWidth - pad &&
        b.x < a.x + nodeWidth - pad &&
        a.y < b.y + nodeHeight - pad &&
        b.y < a.y + nodeHeight - pad
      ) {
        return true;
      }
    }
  }
  return false;
}
