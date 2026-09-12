// M8 图谱分层布局单元测试（与 richtext 同一套零依赖 runner，见 tests/richtext.spec.ts 注释）。
//
// 运行：npm run test:graph

import assert from 'assert';
import { layoutGraph, nodeBoxesOverlap, type LayoutEdgeInput, type LayoutNodeInput } from '../lib/graphLayout';

let passed = 0;
const failures: string[] = [];

function check(name: string, fn: () => void) {
  try {
    fn();
    passed += 1;
    console.log(`  ok  ${name}`);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    failures.push(`${name}: ${msg}`);
    console.log(`FAIL  ${name}\n      ${msg}`);
  }
}

/** 复刻实测形态：6 类 kind、39 节点、33 边（paper 7 的量级）。 */
function chainGraph(kinds: string[], perKind: number): { nodes: LayoutNodeInput[]; edges: LayoutEdgeInput[] } {
  const nodes: LayoutNodeInput[] = [];
  const edges: LayoutEdgeInput[] = [];
  kinds.forEach((kind, ki) => {
    for (let i = 0; i < perKind; i += 1) {
      const id = `${kind}-${i}`;
      nodes.push({ id, kind });
      if (ki > 0) {
        edges.push({ id: `e-${id}`, source: `${kinds[ki - 1]}-${i % perKind}`, target: id, label: 'rel' });
      }
    }
  });
  return { nodes, edges };
}

console.log('graphLayout 测试');

check('1. 同列节点不重叠（旧实现行距 90 < 节点高 ~104）', () => {
  const { nodes, edges } = chainGraph(['problem', 'method', 'experiment', 'claim', 'evidence', 'media'], 7);
  const r = layoutGraph(nodes, edges);
  assert.strictEqual(nodeBoxesOverlap(r.positions), false, '存在节点包围盒重叠');
});

check('2. 真实量级 39 节点 / 33 边不重叠', () => {
  const nodes: LayoutNodeInput[] = [];
  const edges: LayoutEdgeInput[] = [];
  const kinds = ['problem', 'method', 'experiment', 'claim', 'evidence', 'media'];
  const counts = [6, 6, 7, 7, 6, 7]; // 合计 39，复刻实测规模
  kinds.forEach((k, ki) => {
    for (let i = 0; i < counts[ki]!; i += 1) nodes.push({ id: `${k}-${i}`, kind: k });
  });
  for (let i = 0; i < 33; i += 1) {
    const a = nodes[i % nodes.length]!;
    const b = nodes[(i * 7 + 3) % nodes.length]!;
    if (a.id !== b.id) edges.push({ id: `e${i}`, source: a.id, target: b.id, label: `l${i}` });
  }
  const r = layoutGraph(nodes, edges);
  assert.strictEqual(nodes.length, 39);
  assert.strictEqual(nodeBoxesOverlap(r.positions), false);
});

check('3. 100 节点仍不重叠且列数 = kind 数', () => {
  const { nodes, edges } = chainGraph(['a', 'b', 'c', 'd', 'e'], 20);
  const r = layoutGraph(nodes, edges);
  assert.strictEqual(nodes.length, 100);
  assert.strictEqual(r.lanes.length, 5);
  assert.strictEqual(nodeBoxesOverlap(r.positions), false);
});

check('4. 布局确定性：同输入两次调用完全一致', () => {
  const { nodes, edges } = chainGraph(['p', 'm', 'e'], 5);
  const a = layoutGraph(nodes, edges);
  const b = layoutGraph(nodes, edges);
  assert.deepStrictEqual(a, b);
});

check('5. 含环图不死循环且有位置', () => {
  const nodes: LayoutNodeInput[] = [
    { id: 'a', kind: 'x' }, { id: 'b', kind: 'x' }, { id: 'c', kind: 'y' },
  ];
  const edges: LayoutEdgeInput[] = [
    { id: 'e1', source: 'a', target: 'b' },
    { id: 'e2', source: 'b', target: 'a' },
    { id: 'e3', source: 'b', target: 'c' },
    { id: 'e4', source: 'c', target: 'a' },
  ];
  const r = layoutGraph(nodes, edges);
  assert.strictEqual(Object.keys(r.positions).length, 3);
  assert.ok(Object.values(r.positions).every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)));
});

check('6. 层号沿拓扑递增（同列内相关节点相邻）', () => {
  const nodes: LayoutNodeInput[] = [
    { id: 'a', kind: 'm' }, { id: 'b', kind: 'm' }, { id: 'c', kind: 'm' },
  ];
  const edges: LayoutEdgeInput[] = [{ id: 'e', source: 'a', target: 'c' }];
  const r = layoutGraph(nodes, edges);
  assert.ok(r.positions['a']!.layer < r.positions['c']!.layer, 'c 应在 a 之后');
  assert.ok(r.positions['a']!.y < r.positions['c']!.y, 'c 应排在 a 下方');
});

check('7. 边标签与节点包围盒不相交（避不开的标 hidden）', () => {
  const { nodes, edges } = chainGraph(['p', 'm', 'e', 'c'], 6);
  const r = layoutGraph(nodes, edges);
  const nw = 190;
  const nh = 104;
  const boxes = Object.entries(r.positions).map(([, p]) => ({
    x1: p.x, y1: p.y, x2: p.x + nw, y2: p.y + nh,
  }));
  let visible = 0;
  for (const [, l] of Object.entries(r.edgeLabels)) {
    if (l.hidden) continue;
    visible += 1;
    const x1 = l.x - 36, x2 = l.x + 36, y1 = l.y - 9, y2 = l.y + 9;
    for (const b of boxes) {
      assert.ok(
        !(x1 < b.x2 && b.x1 < x2 && y1 < b.y2 && b.y1 < y2),
        `边标签 (${l.x},${l.y}) 压在节点上`,
      );
    }
  }
  assert.ok(visible > 0, '所有边标签都被隐藏了，等于没有关系名字');
});

check('8. 100 节点布局耗时 < 200ms', () => {
  const { nodes, edges } = chainGraph(['a', 'b', 'c', 'd', 'e'], 20);
  const t0 = Date.now();
  layoutGraph(nodes, edges);
  const dt = Date.now() - t0;
  assert.ok(dt < 200, `耗时 ${dt}ms`);
});

check('9. bounds 覆盖全部节点', () => {
  const { nodes, edges } = chainGraph(['p', 'm'], 4);
  const r = layoutGraph(nodes, edges);
  for (const p of Object.values(r.positions)) {
    assert.ok(p.x + 190 <= r.bounds.width + 1, '节点超出 bounds 宽度');
    assert.ok(p.y + 104 <= r.bounds.height + 1, '节点超出 bounds 高度');
  }
});

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
