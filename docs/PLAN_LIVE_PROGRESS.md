# 方案：导入过程中的进度动画闪烁 + 解析结果不实时上屏

> 状态：**待确认**（用户要求"先定个方案"）
> 触发：真实导入解析正常，但
> ① 解析过程动画**一闪一闪**（一会显示一会又没了）；
> ② 解析成功的内容**不会实时推送**，仍需手动刷新。

---

## 一、根因（三条，逐条有代码证据）

### R1 —— 进度卡的可见性绑在「轮询自己会重置的状态」上 → 按轮询周期闪烁

`frontend/app/paper/[slug]/page.tsx:304-309`：

```ts
const notReady = progress.phase !== 'ready' && (
  !exhibits
  || workspace.exhibits.status === 'pending'
  || workspace.exhibits.status === 'loading'      // ← 问题在这
);
```

而 `frontend/hooks/usePaperWorkspace.ts` 的 `refresh()` **每次开头**都：

```ts
setManifest((s) => ({ ...s, status: 'loading', error: null }));
setExhibits((s) => ({ ...s, status: 'loading', error: null }));   // ← 每个 tick 都重置
```

于是每个轮询周期必然发生一次：

```
tick → exhibits='loading' → notReady=true  → 进度卡出现（内容被顶下去）
refresh 返回 → exhibits='ready' → notReady=false → 进度卡消失（内容跳回来）
下个 tick → 又出现 …
```

**这就是"一闪一闪"**：不是动画本身抖，而是**卡片在按轮询间隔反复挂载/卸载**，
每次还会把下方内容顶上顶下（布局抖动）。轮询间隔 1–5s，视觉上非常明显。

### R2 —— 只刷新了 canonical（manifest/exhibits），没刷新 legacy 派生数据

`page.tsx:213-234`：

```ts
const loadLegacy = useCallback(async () => {
  ...
  setDetail(await api.paperDetail(resolvedPaperId));      // 地图/方法/阅读/证据链右栏
  setGraph(await api.graph(resolvedPaperId));             // 研究图谱
  setPresentation(await api.presentation(resolvedPaperId));// 讲解分镜
  setEvalData(await api.evaluation(resolvedPaperId));      // 自动评测
}, [resolvedPaperId]);

useEffect(() => { loadLegacy(); }, [loadLegacy]);          // ← 只在 resolvedPaperId 变化时跑
```

`loadLegacy` **只有这一个调用点**，依赖只有 `resolvedPaperId` —— 也就是**整篇论文只跑一次**。
而轮询调的是 `workspace.refresh()`（**只**刷新 manifest + exhibits）。

各视图的数据来源（`page.tsx` 渲染段实测）：

| 视图 | 读什么 | 会被轮询更新吗 |
|---|---|---|
| 论文地图 MapView | `detail` | ❌ |
| 方法动画 MethodView | `detail` | ❌ |
| 证据链 ClaimView | `claims`（来自 exhibits ✅）+ **右栏 `detail.tables/figures`** | 半 ✅ 半 ❌ |
| 研究图谱 GraphView | `graph` | ❌ |
| 讲解 PresenterView | `presentation` | ❌ |
| 证据问答 QAView | `scope` + `detail` | 半 |
| 自动评测 EvalView | `evalData` + `exhibits.evaluation` | 半 |
| 论文阅读 PaperView | `detail` | ❌ |

**结论**：解析完成后，图谱/讲解/评测/图表这些**永远不会自动出现**，只能手动刷新 ——
正是用户说的"解析成功的内容不会实时推送上去直接覆盖"。

### R3 —— `changeView` 丢掉 `job_id` → 切视图即断流

`page.tsx`：

```ts
const changeView = useCallback((v: ViewMode) => {
  setView(v);
  const qs = pid ? `paper_id=${pid}&view=${v}` : `view=${v}`;   // ← 没有 job_id
  if (slug) router.replace(`/paper/${slug}?${qs}`, { scroll: false });
}, [slug, resolvedPaperId, router]);
```

`jobId` 来自 `searchParams`，URL 一改就变 `null` →
`useJobEvents({ job_id: 0 })` 命中 `if (!job_id || job_id <= 0) { setEvents([]) }` →
**阶段列表被清空、退回通用转圈**。这是第二次"闪"（"阶段列表 ↔ 转圈"来回跳），
而且切换后**再也接不上进度流**。

---

## 二、改法（4 个模块，每步可独立验证）

### M1 静默刷新 —— 消除 R1

- `usePaperWorkspace.refresh({ silent = false })`：
  - `silent: false`（默认，仅首次加载）：行为不变，置 `loading`；
  - `silent: true`：**不动 status**，直接替换 data（保留已有内容，失败也不清空）。
- 轮询一律 `workspace.refresh({ silent: true })`。
- `notReady` **只由进度真相决定**，不再看 `exhibits.status`：

  ```ts
  const notReady = progress.phase !== 'ready';
  ```

- 进度卡用 `AnimatePresence` 做**一次淡出**（phase 变 `ready` 后），而不是反复挂载/卸载。

**验收**：① 纯函数测试 —— `silent` 刷新不改 status；② `notReady` 只看 phase；
③ 手工：导入全程进度卡**只出现一次**，从出现到淡出无中断、下方内容不上下跳。

### M2 分域就绪 → 只拉对应派生数据 —— 消除 R2

- 维护上一次的 `capabilities` 快照；每轮算出**新变为 ready 的域**（状态跃迁），
  只在跃迁时拉取对应数据，**不是每 tick 全拉**：

  | 新 ready 的域 | 重取 |
  |---|---|
  | `claims` | `detail`（地图/方法/证据链右栏/阅读都吃它） |
  | `graph` | `api.graph` |
  | `presentation` | `api.presentation` |
  | `evaluation` | `api.evaluation` |

- 全部走 **silent**（不动 `loading`、不闪骨架、失败保留旧数据并记 warning）。
- 首帧仍走原有 `loadLegacy()`（不变），保证首屏行为与今天一致。

**验收**：新导入一篇论文，**全程不刷新页面**，图谱/讲解/评测/图表在对应域 ready 后
**依次自动出现**；且每个域**只拉一次**（可在网络面板核对）。

### M3 保住 `job_id` —— 消除 R3

- `changeView` 保留 `job_id`：从一个 `baseQuery`（含 `paper_id` + `job_id`）派生 URL。
- 更稳的做法（推荐）：把 `jobId` 在**首次解析后存进组件 state**，URL 只当入口；
  这样即便 URL 被改也不影响 SSE。

**验收**：解析期间切换任意视图，阶段列表**不丢**、不退回通用转圈。

### M4 进度区的"稳定呈现"

- 阶段列表与通用转圈**不要互斥切换**：SSE 未到时显示通用提示，事件一到就在**同一容器内**
  换成阶段列表（同一 `key`，淡入），避免"列表 ↔ 转圈"来回跳。
- 完成（`completed`）后**保留 1.5s** 再淡出，让用户看到"完成"而不是瞬间消失。

**验收**：整个导入过程**只出现一个进度容器**，内部从提示过渡到阶段列表，无中断。

---

## 三、验收与回归

1. **纯函数测试**（`frontend/tests/`，零依赖 runner）：
   - `silent` 刷新不改 status；
   - `newlyReadyDomains(prev, next)` 只在状态跃迁时返回、幂等；
   - `notReady` 只由 phase 决定（给定 loading 状态不影响）。
2. **前端全量**：`tsc` 干净 + `npm run test:lib` 全绿（当前 133 项）。
3. **端到端**：新增 `scripts/acceptance/verify_live_progress.py`（或并入
   `verify_upload_progress.py` 的深档）：触发一次真实导入，断言
   capabilities 从 pending 渐进到 ready、且**各派生端点开始返回非空**
   （不依赖浏览器刷新）。无解析凭据时退出码 2（沿用既有语义）。
4. **人工判据（必须人眼看，我做不了）**：
   - 导入过程中进度卡**不闪**、内容不被上下顶动；
   - 解析完成后**不刷新**，图谱/讲解/评测/图表依次出现；
   - 解析期间切视图，阶段列表不丢。

---

## 四、风险与对策

| 风险 | 对策 |
|---|---|
| `detail` 是较重聚合端点，频繁重取会拖慢前端 | 只在**状态跃迁**时拉，每域最多一次 |
| silent 刷新失败把已有内容清空 | silent 路径**失败保留旧数据**，只记 warning |
| 乐观更新与用户操作冲突 | 本页无编辑态，风险低；仍保留"失败回滚到旧数据" |
| `job_id` 存 state 后 URL 分享失效 | URL 仍带 `job_id`（M3 的第一种做法），state 只是兜底 |

---

## 五、改动面（预估）

| 文件 | 改动 |
|---|---|
| `frontend/hooks/usePaperWorkspace.ts` | `refresh({silent})` |
| `frontend/lib/paperProgress.ts` | 新增 `newlyReadyDomains(prev, next)` 纯函数 |
| `frontend/app/paper/[slug]/page.tsx` | 轮询改 silent；`notReady` 只看 phase；分域跃迁拉派生数据；`changeView` 保 `job_id`；进度区稳定呈现 |
| `frontend/tests/paperProgress.spec.ts` | 新增跃迁与 silent 的断言 |
| `scripts/acceptance/verify_live_progress.py` | 新增（可先做成深档） |
| `docs/DECISIONS.md` | 新增 ADR（记录三条根因与改法） |

**不进 M1–M4 的东西**（避免顺手扩大范围）：不改后端接口、不改 `JobProgress` 的阶段定义、
不动 `AgentTrace`。
