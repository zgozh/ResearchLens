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
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status} ${path}: ${body}`);
  }
  return (await res.json()) as T;
}

export const api = {
  base: BASE,
  health: () => http<HealthOut>('/api/health'),
  demoList: () => http<DemoPaperListItem[]>('/api/demo'),
  demoLoad: (slug: string) =>
    http<PaperOut>('/api/demo/load', {
      method: 'POST',
      body: JSON.stringify({ slug }),
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
    }),
  evaluation: (id: number) =>
    http<EvaluationOut>(`/api/papers/${id}/evaluation`),
};
