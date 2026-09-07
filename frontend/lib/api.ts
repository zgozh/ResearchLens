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

const BASE =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
};

export function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}
