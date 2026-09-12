import type {
  AskResponse,
  ClaimOut,
  ClaimSummary,
  DemoPaperListItem,
  EvaluationOut,
  GraphOut,
  HealthOut,
  PaperDetail,
  PaperOut,
  PresentationOut,
} from './types';
import type {
  Anchor,
  Asset,
  DomainError,
  EvidenceExport,
  ExhibitBundle,
  Media,
  MediaViewPolicy,
  PageContent,
  PaperManifest,
  PageResult,
  PageSummary,
  RevisionId,
  ValidationReport,
  EvidenceRecord,
} from './contracts';
import {
  fixtureAnchor,
  fixtureExhibits,
  fixtureEvidence,
  fixtureEvidenceExport,
  fixtureManifest,
  fixtureMedia,
  fixturePageContent,
  fixturePages,
  fixturePolicy,
  fixtureAssets,
} from './fixtures';

const BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8002';

/**
 * 后端返回的受控资源地址是**相对路径**（如 `/api/assets/{id}`），
 * 而前端与后端通常是**不同源**（4002 vs 8002）且 `next.config.mjs` 没有 rewrite，
 * 直接把它当 `src` 会打到前端服务器上 → 404 → 图全空。
 * 所有 `<img src>`/`<a href>` 用到后端资源时都必须过这个函数。
 */
export function absoluteApiUrl(url: string | null | undefined): string {
  const raw = (url || '').trim();
  if (!raw) return '';
  if (/^https?:\/\//i.test(raw) || raw.startsWith('data:') || raw.startsWith('blob:')) {
    return raw;
  }
  return `${BASE}${raw.startsWith('/') ? '' : '/'}${raw}`;
}

/**
 * canonical 端点已在后端实现（§5.12）并端到端验证通过，因此**默认走真实接口**。
 * 仅在需要离线开发 / 后端不可用时，显式设 NEXT_PUBLIC_USE_FIXTURES=1 才切到静态 fixtures。
 *
 * 注意：旧默认值是 `!== '0'`（即默认为 true），会让生产构建永远读 fixtures，
 * 直接导致「页面能打开但看不到真实数据」——已修正为 opt-in。
 */
export const USE_FIXTURES =
  process.env.NEXT_PUBLIC_USE_FIXTURES === '1';

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    cache: 'no-store',
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let message = `API ${res.status}`;
    try {
      const j = JSON.parse(text);
      message = j?.detail || message;
    } catch {
      /* ignore */
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

const JSON_HEADERS: HeadersInit = { 'Content-Type': 'application/json' };

/** 把任意抛出转换为 DomainError（canonical 错误结构，供 hooks 的 LoadState/StreamState）。 */
export function toDomainError(e: unknown): DomainError {
  const message = e instanceof Error ? e.message : String(e);
  const isAbort = e instanceof DOMException && e.name === 'AbortError';
  return {
    code: isAbort ? 'CANCELLED' : 'INTERNAL_ERROR',
    message,
    retryable: false,
    request_id: '',
    field_errors: [],
    retry_after_ms: null,
  };
}

function q(params: Record<string, string | number | undefined | null>): string {
  const entries = Object.entries(params).filter(
    (kv): kv is [string, string | number] => kv[1] != null,
  );
  if (entries.length === 0) return '';
  const sp = new URLSearchParams(entries.map(([k, v]) => [k, String(v)]));
  return `?${sp.toString()}`;
}

export const api = {
  base: BASE,
  health: () => http<HealthOut>('/api/health'),
  demoList: () => http<DemoPaperListItem[]>('/api/demo'),
  demoLoad: (slug: string) =>
    http<PaperOut>('/api/demo/load', {
      method: 'POST',
      body: JSON.stringify({ slug }),
      headers: JSON_HEADERS,
    }),
  papers: () => http<PaperOut[]>('/api/papers'),
  paperDetail: (id: number) => http<PaperDetail>(`/api/papers/${id}`),
  claims: (id: number) => http<ClaimSummary[]>(`/api/papers/${id}/claims`),
  claim: (id: number, cid: string) =>
    http<ClaimOut>(`/api/papers/${id}/claims/${cid}`),
  graph: (id: number) => http<GraphOut>(`/api/papers/${id}/graph`),
  presentation: (id: number) =>
    http<PresentationOut>(`/api/papers/${id}/presentation`),
  qa: (id: number, question: string) =>
    http<AskResponse>(`/api/papers/${id}/qa`, {
      method: 'POST',
      body: JSON.stringify({ question }),
      headers: JSON_HEADERS,
    }),
  /** 断流恢复（REFACTOR_PLAN M6）：按 answer_id 取回**已落库**的回答。 */
  qaAnswer: (id: number, answerId: string) =>
    http<{
      status: 'streaming' | 'completed';
      answer_id: string;
      legacy?: AskResponse;
    }>(`/api/papers/${id}/qa/answers/${encodeURIComponent(answerId)}`),
  evaluation: (id: number) =>
    http<EvaluationOut>(`/api/papers/${id}/evaluation`),
  // --- live: upload + process ---
  uploadPaper: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return http<{ paper_id: number; job_id: number; status: string }>('/api/papers/upload', {
      method: 'POST',
      body: form,
    });
  },
  processPaper: (id: number) =>
    http<{ paper_id: number; job_id: number; status: string }>(`/api/papers/${id}/process`, {
      method: 'POST',
      body: JSON.stringify({}),
      headers: JSON_HEADERS,
    }),
  jobStatus: (id: number) =>
    http<{ job_id: number; stage: string; stage_label: string; status: string; paper_id: number }>(
      `/api/jobs/${id}`,
    ),
  // --- model selection (DashScope) ---
  models: () => http<{ models: string[]; active: string }>('/api/models'),
  setModel: (model: string) =>
    http<{ active: string }>('/api/models', { method: 'POST', body: JSON.stringify({ model }), headers: JSON_HEADERS }),
  // --- real paper by URL (background ingest) ---
  paperFromUrl: (url: string, title?: string) =>
    http<{ paper_id: number; status: string; slug: string }>('/api/papers/from-url', {
      method: 'POST',
      body: JSON.stringify({ url, title }),
      headers: JSON_HEADERS,
    }),
  // === 新增 canonical 资源接口（§5.12）——USE_FIXTURES 为 true 时走 fixtures ===
  getManifest: async (paperId: number, revisionId?: RevisionId): Promise<PaperManifest> => {
    if (USE_FIXTURES) return fixtureManifest(paperId);
    return http<PaperManifest>(`/api/papers/${paperId}/manifest${q({ revision_id: revisionId })}`);
  },
  getExhibitBundle: async (paperId: number, revisionId?: RevisionId): Promise<ExhibitBundle> => {
    if (USE_FIXTURES) return fixtureExhibits({ paper_id: paperId, revision_id: revisionId ?? 'fixture-revision' });
    return http<ExhibitBundle>(`/api/papers/${paperId}/exhibits${q({ revision_id: revisionId })}`);
  },
  getPages: async (paperId: number, revisionId?: RevisionId): Promise<PageResult<PageSummary>> => {
    if (USE_FIXTURES) return fixturePages();
    return http<PageResult<PageSummary>>(`/api/papers/${paperId}/pages${q({ revision_id: revisionId })}`);
  },
  getPage: async (paperId: number, pdfPageNo: number, revisionId?: RevisionId): Promise<PageContent> => {
    if (USE_FIXTURES) return fixturePageContent(pdfPageNo - 1);
    return http<PageContent>(`/api/papers/${paperId}/pages/${pdfPageNo}${q({ revision_id: revisionId })}`);
  },
  /** 页预览图片 URL（PDF.js 失败兜底用）。 */
  pagePreviewUrl: (paperId: number, pdfPageNo: number, revisionId?: RevisionId): string =>
    `${BASE}/api/papers/${paperId}/pages/${pdfPageNo}/preview${q({ revision_id: revisionId })}`,
  getMedia: async (
    paperId: number,
    mediaId: string,
    revisionId?: RevisionId,
  ): Promise<{ media: Media; assets: Asset[]; policy: MediaViewPolicy }> => {
    if (USE_FIXTURES) {
      const media = fixtureMedia(mediaId);
      return { media, assets: fixtureAssets, policy: fixturePolicy(media, fixtureAssets) };
    }
    return http<{ media: Media; assets: Asset[]; policy: MediaViewPolicy }>(
      `/api/papers/${paperId}/media/${mediaId}${q({ revision_id: revisionId })}`,
    );
  },
  getAnchor: async (paperId: number, anchorId: string, revisionId?: RevisionId): Promise<Anchor> => {
    if (USE_FIXTURES) return fixtureAnchor();
    return http<Anchor>(`/api/papers/${paperId}/anchors/${anchorId}${q({ revision_id: revisionId })}`);
  },
  getEvidence: async (
    paperId: number,
    evidenceId: string,
    revisionId?: RevisionId,
  ): Promise<{ evidence: EvidenceRecord; validation: ValidationReport }> => {
    if (USE_FIXTURES) {
      const evidence = fixtureEvidence({ paper_id: paperId, revision_id: revisionId ?? 'fixture-revision' });
      const validation = fixtureExhibits().statements[0]?.validation;
      return { evidence, validation: validation ?? (null as unknown as ValidationReport) };
    }
    return http<{ evidence: EvidenceRecord; validation: ValidationReport }>(
      `/api/papers/${paperId}/evidence/${evidenceId}${q({ revision_id: revisionId })}`,
    );
  },
  /** 原件 PDF 地址（react-pdf 用）。 */
  documentUrl: (paperId: number, revisionId?: RevisionId): string =>
    `${BASE}/api/papers/${paperId}/document${q({ revision_id: revisionId })}`,
  /** 下载/读取原 PDF 字节。 */
  getDocument: async (paperId: number, revisionId?: RevisionId): Promise<Blob> => {
    const res = await fetch(api.documentUrl(paperId, revisionId), { cache: 'no-store' });
    if (!res.ok) throw new Error(`document ${res.status}`);
    return res.blob();
  },
  getEvidenceExport: async (paperId: number, revisionId?: RevisionId): Promise<EvidenceExport> => {
    if (USE_FIXTURES) return fixtureEvidenceExport({ paper_id: paperId, revision_id: revisionId ?? 'fixture-revision' });
    return http<EvidenceExport>(`/api/papers/${paperId}/evidence-export${q({ revision_id: revisionId })}`);
  },
  /** QA 流式端点 URL（配合 lib/sse.ts 的 openSSE 使用）。 */
  qaStreamUrl: (paperId: number): string => `${BASE}/api/papers/${paperId}/qa/stream`,
  /** Job 事件流式端点 URL。 */
  jobEventsUrl: (jobId: number): string => `${BASE}/api/jobs/${jobId}/events`,
};

export function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}
