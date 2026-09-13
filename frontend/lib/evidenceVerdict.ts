// 证据 verdict 四分类（REFACTOR_PLAN_R3 M2）。
//
// 为什么需要：paper 7 实测分布是 `verified 64 / unverified 6 / rejected 2 / contested 1`，
// 但界面上那 9 条非 verified 全都被写成"未支持" —— 用户看到的语义被压平了：
//   · 6 条其实是**系统主动排除的非研究发现**（参考文献 `[15] …`、Google 许可声明）；
//   · 1 条是**真矛盾**（原文 β₁=0.9，陈述写 0）；
//   · 2 条是**有支持但没通过其他检查**（semantic=supports 而 decision=rejected）。
// 把它们都叫"证据不足"是误导：用户会以为系统没能证明，实际上是系统**拒绝**收录那句话。
//
// 本模块是分类规则的**唯一真相**：输入后端 `validation{decision, semantic_status, reasons}`，
// 输出四类语义 + 标签 + 色调 + 可原样展开的 reasons。未知组合一律回落 `insufficient`
// 并且**原样保留 reasons**（不丢信息、不抛错）。

export type VerdictCategory = 'non_claim' | 'contradiction' | 'rejected_other' | 'insufficient';

export interface ReasonItem {
  code: string;
  message: string;
}

export interface EvidenceVerdictView {
  category: VerdictCategory;
  label: string;
  tone: 'slate' | 'rose' | 'amber' | 'stone';
  /** 一句话解释"这一类到底是什么意思"，直接显示给用户。 */
  explain: string;
  reasons: ReasonItem[];
}

const CATEGORY_META: Record<VerdictCategory, Omit<EvidenceVerdictView, 'category' | 'reasons'>> = {
  non_claim: {
    label: '非研究发现',
    tone: 'slate',
    explain: '这句话不是研究发现（参考文献 / 许可声明 / 页脚等），系统主动排除；不代表证据不足。',
  },
  contradiction: {
    label: '真矛盾',
    tone: 'rose',
    explain: '原文与陈述相互矛盾（结论相反、数值冲突），这是需要修陈述、不是缺证据。',
  },
  rejected_other: {
    label: '有支持但未通过其他检查',
    tone: 'amber',
    explain: '语义上证据是支持的，但还有别的检查没过（数字 / 适用条件 / 定位等），看下方理由。',
  },
  insufficient: {
    label: '证据不足',
    tone: 'stone',
    explain: '现有证据不足以支持这句话。',
  },
};

/** 非研究发现的信号词（与后端 `gate._is_non_claim_statement` 的 reasons 文案对应）。 */
const NON_CLAIM_HINTS = ['不是研究发现', '参考文献', '许可声明', '页脚', 'non_claim'];

export function parseReasons(raw: unknown): ReasonItem[] {
  if (!Array.isArray(raw)) return [];
  const out: ReasonItem[] = [];
  for (const item of raw) {
    if (typeof item === 'string') {
      // 裸字符串形态："码：文案" 或纯文案
      const idx = item.indexOf('：');
      if (idx > 0 && idx <= 40) {
        out.push({ code: item.slice(0, idx).trim(), message: item.slice(idx + 1).trim() });
      } else {
        out.push({ code: 'UNKNOWN', message: item });
      }
      continue;
    }
    if (item && typeof item === 'object') {
      const obj = item as Record<string, unknown>;
      const message = typeof obj.message === 'string' ? obj.message : String(obj.message ?? '');
      const code = typeof obj.code === 'string' && obj.code ? obj.code : 'UNKNOWN';
      out.push({ code, message });
    }
  }
  return out;
}

function hasNonClaimSignal(reasons: ReasonItem[]): boolean {
  return reasons.some(
    (r) =>
      NON_CLAIM_HINTS.some((h) => r.message.includes(h)) ||
      NON_CLAIM_HINTS.some((h) => r.code.includes(h)),
  );
}

/**
 * 分类（优先级自上而下）：
 * 1. 非研究发现（reasons 命中）→ `non_claim`
 * 2. 矛盾信号（`semantic_status=contradicts` 或 reasons 含 `contradiction`）→ `contradiction`
 * 3. `semantic_status=supports` 但 `decision=rejected` → `rejected_other`
 * 4. 其余（含未知组合、无 validation）→ `insufficient`
 *
 * 入参可空：无可渲染的 verdict 时返回 `null`（调用方不渲染徽标）。
 */
export function classifyVerdict(validation: unknown): EvidenceVerdictView | null {
  if (!validation || typeof validation !== 'object' || Array.isArray(validation)) return null;
  const v = validation as Record<string, unknown>;
  const decision = typeof v.decision === 'string' ? v.decision : '';
  const semantic = typeof v.semantic_status === 'string' ? v.semantic_status : '';
  const reasons = parseReasons(v.reasons);
  if (!decision && !semantic && reasons.length === 0) return null;
  // 已经是"支持"且通过 → 不该用本徽标（调用方应显示"有据可依"）
  if (decision === 'verified') return null;

  let category: VerdictCategory = 'insufficient';
  if (hasNonClaimSignal(reasons)) {
    category = 'non_claim';
  } else if (semantic === 'contradicts' || reasons.some((r) => r.code === 'contradiction')) {
    category = 'contradiction';
  } else if (semantic === 'supports' && decision === 'rejected') {
    category = 'rejected_other';
  }
  return { category, ...CATEGORY_META[category], reasons };
}

/** 是否属于"设计上不可测/不适用"的语义（M9 也用这条判断）。 */
export function isNotApplicable(category: VerdictCategory, reasons: ReasonItem[]): boolean {
  return category === 'insufficient' && reasons.length === 0;
}
