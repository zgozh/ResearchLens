// 唯一指标解析函数（REFACTOR_PLAN_R3 M8）。
//
// 为什么需要：实测 `GET /api/papers/7/evaluation` 明明返回真实值
// （source_asset_coverage 0.3571、anchor_page_accuracy 1.0、quote_exact_rate 1.0、
// support_precision 0.6667），界面却**全部显示"未评测"**。
// 根因：`EvalView` 优先读 `/exhibits` 里持久化的 canonical report，其 `metrics` 是
// `list[MetricEntry]`，每项 `entry.value` 是 `MetricValue` **对象**；旧代码把对象直接塞进
// "值为数字"的 map，再经 `toNumber()` → `Number({...})` = NaN → 全部按未评测渲染；
// 又因为该键已存在（非 undefined），legacy 的数字**不会覆盖**它。
//
// 本模块是**唯一**解析入口，吃四种输入形态：number / MetricValue 对象 /
// list[MetricEntry] / dict（legacy）。不可识别的形态**显式**标 `unparsable`，
// 绝不静默降级成"未评测"（那是把 bug 藏在数据里）。

export type MetricStatus = 'measured' | 'proxy' | 'not_evaluated' | 'unparsable';

export interface MetricView {
  name: string;
  value: number | null;
  status: MetricStatus;
  unit: string;
  /** `status=not_evaluated` 时的机器可读原因码。 */
  reason?: string;
  source: 'canonical' | 'legacy' | 'unparsable';
}

export interface OverallView {
  score: number | null;
  /**
   * 分数**来源**。产品里只有一种来源（AI 裁判 + 程序测量自动得出），
   * 契约值为 `'ai_generated'`；类型保留 `string` 是为了**原样透传**后端声明
   * （宁可显示一个我们不认识但真实的来源码，也不要把它硬改成我们知道的那个）。
   * 无值时一律 null —— 不谎称来源。
   */
  basis: string | null;
}

/** `metrics` 里属于**元信息**而非指标本身的键，不参与指标列表。 */
const META_KEYS = new Set([
  'not_evaluated',
  'not_evaluated_reasons',
  'proxy',
  'overall_score_available',
  'overall_score_canonical',
  'overall_score_basis',
  'ai_overall_score',
  'ai_overall_score_available',
  'golden_id',
  'version',
  'warnings',
  'note',
]);

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'boolean' || typeof value === 'object') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

interface Parsed {
  value: number | null;
  status: MetricStatus;
  unit: string;
  reason?: string;
}

/** 解析**单个**指标值；`null` 表示"认不出来"（调用方标 unparsable）。 */
export function parseMetricValue(raw: unknown, reasonHint?: string): Parsed | null {
  if (raw === null || raw === undefined) {
    return { value: null, status: 'not_evaluated', unit: 'ratio', reason: reasonHint };
  }
  if (typeof raw === 'number') {
    return { value: raw, status: 'measured', unit: 'ratio' };
  }
  if (typeof raw === 'string') {
    // 数字字符串允许（有些投影会把小数写成字符串）
    const n = toNumber(raw);
    return n === null ? null : { value: n, status: 'measured', unit: 'ratio' };
  }
  if (typeof raw === 'object' && !Array.isArray(raw)) {
    const obj = raw as Record<string, unknown>;
    const status = typeof obj.status === 'string' ? (obj.status as MetricStatus) : undefined;
    const hasValueKey = 'value' in obj;
    if (!status && !hasValueKey) return null; // 例如 {foo:1} —— 认不出来
    const value = toNumber(obj.value);
    const unit = typeof obj.unit === 'string' && obj.unit ? obj.unit : 'ratio';
    const reason = typeof obj.reason === 'string' && obj.reason ? obj.reason : reasonHint;
    const effective: MetricStatus =
      status ?? (value === null ? 'not_evaluated' : 'measured');
    // 纪律 1：not_evaluated 不许带数值；后端若给了值但状态是未评测，以"无值"为准但保留状态。
    if (effective === 'not_evaluated') {
      return { value: null, status: 'not_evaluated', unit, reason };
    }
    if (value === null) return null; // 声称 measured/proxy 却没有值 → 认不出来
    return { value, status: effective, unit, reason };
  }
  return null;
}

function isMetricEntryList(raw: unknown): raw is Array<Record<string, unknown>> {
  return (
    Array.isArray(raw) &&
    raw.length > 0 &&
    raw.every((item) => item && typeof item === 'object' && 'name' in (item as object))
  );
}

/**
 * 归一化：canonical（`list[MetricEntry]` 或 `MetricValue` dict）优先，
 * legacy（数字 dict）**只补 canonical 缺失的键**。
 *
 * 关键纪律：canonical 明确说 `not_evaluated` 的键，**不允许**被 legacy 的数字覆盖 ——
 * 语义由后端决定，前端不擅自"拯救"（那会造出后端从未声明的 measured）。
 */
export function buildMetricViews(canonical: unknown, legacy: unknown): MetricView[] {
  const views = new Map<string, MetricView>();
  const legacyReasons: Record<string, string> =
    legacy && typeof legacy === 'object' && !Array.isArray(legacy)
      ? (((legacy as Record<string, unknown>).not_evaluated_reasons as Record<string, string>) || {})
      : {};

  const put = (name: string, parsed: Parsed | null, source: 'canonical' | 'legacy') => {
    if (META_KEYS.has(name)) return;
    if (parsed === null) {
      if (!views.has(name)) {
        views.set(name, {
          name, value: null, status: 'unparsable', unit: 'ratio', source: 'unparsable',
        });
      }
      return;
    }
    views.set(name, {
      name, value: parsed.value, status: parsed.status, unit: parsed.unit,
      reason: parsed.reason, source,
    });
  };

  // 1) canonical：list[MetricEntry] 或 dict[name → MetricValue]
  if (isMetricEntryList(canonical)) {
    for (const entry of canonical) {
      const name = String(entry.name);
      put(name, parseMetricValue(entry.value, legacyReasons[name]), 'canonical');
    }
  } else if (canonical && typeof canonical === 'object') {
    for (const [name, raw] of Object.entries(canonical as Record<string, unknown>)) {
      put(name, parseMetricValue(raw, legacyReasons[name]), 'canonical');
    }
  }

  // 2) legacy 补"**没有值**"的键（canonical 有值的一律不覆盖）。
  //
  // 实测（paper 7 录制响应回放）：`/exhibits` 里**持久化的**报告有 10 项是
  // not_evaluated / 0-proxy（旧一轮跑的），而 `/evaluation` 现算的同一批指标有真值
  // （input_tokens 5213、quote_exact_rate 1.0、support_precision 0.6667 …）。
  // 若坚持"canonical 说什么就是什么"，面板会长期显示一片"未评测"——
  // 这正是用户看到的"说好了全部 AI 评测但还是全显示未评测"。
  // 因此：**有值优先**，同时用 findConflicts() 把"两个源不一致"显式告诉用户，
  // 不静默挑一个（谁是权威只有后端能定，前端负责把矛盾摆出来）。
  if (legacy && typeof legacy === 'object' && !Array.isArray(legacy)) {
    for (const [name, raw] of Object.entries(legacy as Record<string, unknown>)) {
      if (META_KEYS.has(name)) continue;
      const existing = views.get(name);
      if (existing && existing.value !== null) continue; // canonical 有值：权威
      put(name, parseMetricValue(raw, legacyReasons[name]), 'legacy');
    }
  }

  return [...views.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * **主分 = AI 质量评分（自动）**（R4-M5 / ADR D-105）。
 *
 * 为什么不再有 human/ai 双口径：用户拍板"取消一切跟人工有关的……把综合评分右边的
 * （人工真值口径）字段删掉"。人工确认在真实使用中永远不会发生，双口径的结果就是
 * 主位永远显示"未确认"、用户永远看不到分数。
 *
 * 但**来源标注纪律保留**：`basis` 必须能表达"这个分数是 AI 判定 + 程序测量自动得出的"，
 * 不是人工评审 —— 所以返回 `{ score, basis }` 而不是单一个数字。
 */
export interface OverallView {
  score: number | null;
  /**
   * 分数**来源**。产品里只有一种来源（AI 裁判 + 程序测量自动得出），
   * 契约值为 `'ai_generated'`；类型保留 `string` 是为了**原样透传**后端声明
   * （宁可显示一个我们不认识但真实的来源码，也不要把它硬改成我们知道的那个）。
   * 无值时一律 null —— 不谎称来源。
   */
  basis: string | null;
}

export function parseOverall(canonical: unknown, legacy: unknown): OverallView {
  const fromLegacy = (key: string): unknown =>
    legacy && typeof legacy === 'object' && !Array.isArray(legacy)
      ? (legacy as Record<string, unknown>)[key]
      : null;
  const fromCanonical = (key: string): number | null => {
    const views = buildMetricViews(canonical, null);
    return views.find((v) => v.name === key)?.value ?? null;
  };
  // 分数：canonical 主分优先，旧投影的 `overall_score` 兜底；
  // 再退到已废弃的 `ai_overall_score`（过渡期内它与主分同值）。
  const score =
    fromCanonical('overall_score')
    ?? toNumber(fromLegacy('overall_score'))
    ?? fromCanonical('ai_overall_score')
    ?? toNumber(fromLegacy('ai_overall_score'));
  if (score === null) return { score: null, basis: null };
  // 来源：优先读后端显式声明的 basis；缺失（旧报告）时按"这就是 AI 口径分"处理，
  // 因为决策 3 之后**不存在**人工口径的分了 —— 绝不谎称人工审核过。
  const declared = fromLegacy('overall_score_basis');
  const basis = typeof declared === 'string' && declared ? declared : 'ai_generated';
  return { score, basis };
}

/** 不可测（设计上测不了）与"暂时没有真值"是两件事，UI 要分开显示。 */
export const NOT_APPLICABLE_REASONS = new Set([
  'source_pdf_has_no_coordinate_rects',
]);

export interface MetricConflict {
  name: string;
  canonical: number | null;
  canonicalStatus: MetricStatus;
  legacy: number | null;
}

/**
 * 找出**两个数据源打架**的指标（M8 实测发现）。
 *
 * 实测（paper 7 录制响应回放）：`/exhibits` 里持久化的 canonical 报告说
 * `quote_exact_rate = not_evaluated`、`support_precision = 0(proxy)`，
 * 而 `/evaluation` 现算的 legacy 投影说它们分别是 `1.0` / `0.6667`。
 * 两份报告来自不同时间点的金标集/断言集，**谁是权威只有后端能定**。
 *
 * 前端纪律：不许静默挑一个显示 —— 必须把冲突**显式**告诉用户，
 * 否则"指标到底是多少"这个问题会被悄悄回答错。
 */
export function findConflicts(canonical: unknown, legacy: unknown): MetricConflict[] {
  const canonViews = buildMetricViews(canonical, null);
  const legacyViews = buildMetricViews(null, legacy);
  const legacyByName = new Map(legacyViews.map((v) => [v.name, v]));
  const out: MetricConflict[] = [];
  for (const c of canonViews) {
    const l = legacyByName.get(c.name);
    if (!l || l.value === null) continue;
    const same = c.value !== null && Math.abs(c.value - l.value) < 1e-9;
    const canonicalMissing = c.value === null;
    if (!same && (canonicalMissing || c.status !== 'measured')) {
      out.push({
        name: c.name,
        canonical: c.value,
        canonicalStatus: c.status,
        legacy: l.value,
      });
    } else if (!same) {
      out.push({
        name: c.name,
        canonical: c.value,
        canonicalStatus: c.status,
        legacy: l.value,
      });
    }
  }
  return out;
}

export function reasonText(code?: string): string {
  if (!code) return '原因未记录';
  return REASON_TEXT[code] ?? code;
}

export const REASON_TEXT: Record<string, string> = {
  no_independent_region_truth:
    '缺少独立的区域真值来源：锚点矩形与期望区域同源（都由引用块的 bbox 派生），'
    + '据此算 IoU 恒为 1.0，是自证的满分而不是测量',
  source_pdf_has_no_coordinate_rects:
    '该样本的原文块没有可用的坐标矩形（缺少 bbox 或单位未知）',
  usage_missing_in_answer_rows: '作答记录里没有 token / 时延用量',
  no_golden_truth: '缺少参考断言（AI 从原文构造或句子挑选均可）',
  no_ai_judge: 'AI 裁判本次未给出结论（不以 0 冒充）',
  no_prediction_samples: '本次没有可对比的预测样本',
  no_quote_spans: '没有可核对的引文跨度',
  no_navigation_checks: '没有导航校验样本',
  no_media_samples: '没有媒体样本',
  no_degradation_events: '没有发生降级事件',
  no_evaluation_report: '该 revision 尚无评测报告',
  metric_absent_in_report: '报告里没有这一项',
  metric_entry_unparsable: '指标条目不可解析',
  metric_input_missing: '本次输入未提供该指标所需数据',
  unspecified: '原因未归类',
};
