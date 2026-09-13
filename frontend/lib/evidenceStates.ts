// 证据载入状态（R4-M1，需求 A）—— 零依赖纯函数，便于在 node 里单测。
//
// 为什么要有这个模块：证据抽屉此前有两种"把信息抹平"的行为。
//
// 1. **`Promise.all` + `.catch(() => setEvidence([]))`**：任意一条证据请求失败就把
//    **已经取回的证据全部清空**，界面显示"暂无证据" —— 一个网络抖动被伪装成
//    "这条断言没有证据"。这是**信息丢失**，不是降级。
// 2. **空态只有一句"暂无证据"**：它至少压着三种成因（尚未抽取 / 该断言确无关联证据 /
//    拉取失败），用户完全看不出该等、该换断言、还是该重试。
//
// 本模块把这两件事变成可测的纯逻辑：逐条降级 + 空态成因可分辨。

import type { EvidenceRecord } from './contracts';
import { parseReasons, type ReasonItem } from './evidenceVerdict';

/** 单条证据的载入结果（**逐条**降级，绝不因为一条失败清空整体）。 */
export interface EvidenceSlot {
  id: string;
  evidence: EvidenceRecord | null;
  /**
   * 该证据的**校验报告**（后端 `GET /evidence/{id}` 本来就返回它，前端以前丢掉了）。
   * R4-M1 用它渲染四分类徽标与"未判定"的成因细分 —— 与 ClaimView 列表**同源**。
   */
  validation: unknown;
  /** 非 null 表示**这一条**拉取失败（其余条目不受影响）。 */
  error: string | null;
}

/**
 * 把 `Promise.allSettled` 的结果整理成逐条槽位。
 *
 * 关键：失败的条目**留在列表里**并带 error，而不是被过滤掉 ——
 * 用户要看到"这条我没取回来"，而不是看到"这里什么都没有"。
 */
export function settleEvidence(
  ids: string[],
  results: PromiseSettledResult<{ evidence: EvidenceRecord; validation?: unknown }>[],
): EvidenceSlot[] {
  return ids.map((id, i) => {
    const r = results[i];
    if (!r || r.status === 'rejected') {
      const reason = r && r.status === 'rejected' ? r.reason : undefined;
      const message =
        reason instanceof Error && reason.message
          ? reason.message
          : '取回失败';
      return { id, evidence: null, validation: null, error: message };
    }
    return { id, evidence: r.value.evidence, validation: r.value.validation ?? null, error: null };
  });
}

/** 流水线分域状态（来自 `manifest.capabilities[].state`）。 */
export type CapabilityState = 'pending' | 'ready' | 'unavailable' | 'unknown';

export type EmptyCause = 'not_extracted_yet' | 'no_linked_evidence' | 'fetch_failed';

export interface EmptyExplanation {
  cause: EmptyCause;
  title: string;
  detail: string;
}

/**
 * 「暂无证据」的三种成因（R4-M1 目标 3）。
 *
 * 优先级：**拉取失败 > 尚未抽取 > 确无关联证据**。
 * 为什么这个顺序：拉取失败与"确无证据"在用户眼里长得一样，但前者可以重试、
 * 后者只能换断言；把前者说成后者等于让用户白等。
 */
export function explainEmptyEvidence(opts: {
  /** 该断言关联的证据 id 列表是否为空 */
  hasIds: boolean;
  /** 是否至少有一条请求失败 */
  fetchFailed: boolean;
  /** `manifest.capabilities` 里 claims 域的状态（拿不到就是 unknown） */
  claimsState?: CapabilityState;
}): EmptyExplanation {
  if (opts.fetchFailed) {
    return {
      cause: 'fetch_failed',
      title: '证据拉取失败',
      detail: '这条断言的证据没能取回来（多为网络或服务端瞬时问题），可以重试。',
    };
  }
  if (!opts.hasIds) {
    if (opts.claimsState === 'pending' || opts.claimsState === 'unknown') {
      return {
        cause: 'not_extracted_yet',
        title: '正在抽取证据…',
        detail: '这篇论文的断言与证据还在生成中，完成后会自动出现。',
      };
    }
    return {
      cause: 'no_linked_evidence',
      title: '该断言暂无关联证据',
      detail: '抽取已完成，但这条断言没有通过校验的证据可展示。',
    };
  }
  // 有 id、没失败、却仍然为空：只能如实说"没取到内容"
  return {
    cause: 'no_linked_evidence',
    title: '该断言暂无关联证据',
    detail: '请求已返回，但没有可展示的证据记录。',
  };
}

/**
 * 「未判定」的成因细分（R4-M1 目标 2）—— 与后端 reason code 对齐。
 *
 * 后端 `gate.semantic_unavailable_code` 把成因分成
 * `semantic_unavailable`（未配置模型）/ `semantic_timeout`（超时）/
 * `semantic_failed`（调用失败或输出非法）/ `external_unavailable`（旧数据兜底）。
 * 这里把它们翻成用户能**据此行动**的话：
 * 未配置 → 去配 Key；超时/失败 → 重试；兜底 → 看理由。
 */
export function unreviewedDetail(reasons: ReasonItem[]): string {
  const codes = new Set((reasons || []).map((r) => r.code));
  if (codes.has('semantic_unavailable')) return '未配置语义判定模型（配置后可自动重跑）';
  if (codes.has('semantic_timeout')) return '语义判定超时（可重试）';
  if (codes.has('semantic_failed')) return '语义判定未返回结论（调用失败或输出非法）';
  return '语义判定未返回结论（原因未细分，见下方理由）';
}

/** `unreviewed` 的展示文案：把成因拼成一行，供抽屉的副标题使用。 */
export function unreviewedLabel(validation: unknown): string | null {
  if (!validation || typeof validation !== 'object') return null;
  const v = validation as Record<string, unknown>;
  if (v.semantic_status !== 'unreviewed') return null;
  return unreviewedDetail(parseReasons(v.reasons));
}

/** 统计有多少条拉取失败（用于空态判断与告警）。 */
export function failureCount(slots: EvidenceSlot[]): number {
  return slots.filter((s) => s.error !== null).length;
}
