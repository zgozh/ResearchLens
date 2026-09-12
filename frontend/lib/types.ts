// Types mirroring the backend Pydantic schemas (app/schemas/schemas.py).

export interface HealthOut {
  status: string;
  demo_mode: boolean;
  version: string;
}

export interface PaperOut {
  id: number;
  slug: string;
  title: string;
  subtitle: string;
  authors: string[];
  year: number;
  domain: string;
  abstract: string;
  tags: string[];
  source_mode: string;
  status: string;
  map_summary: Record<string, string>;
  pdf_url?: string;
}

export interface SectionOut {
  heading: string;
  kind: string;
  page: number;
  summary: string;
  body: string;
  key_points: string[];
  /** 本节覆盖的物理页范围（canonical）；`page` = page_start，用于跳转到对应正文页。 */
  page_start?: number;
  page_end?: number;
}

export interface FigureOut {
  fig_no: number;
  caption: string;
  page: number;
  glyph_svg: string;
  image_b64: string;
  importance: string;
  description: string;
  /** 真实图资产 URL（canonical，/api/assets/{id}）；FigureImage 优先用它。 */
  image_url?: string;
  image_mime?: string;
  media_id?: string;
}

export interface TableOut {
  table_no: number;
  caption: string;
  page: number;
  content: string[][];
  table_html?: string;
  key_finding: string;
}

export interface MethodStep {
  id: string;
  label: string;
  phase?: string;
  detail?: string;
  text?: string;
  figure_ref?: number;
  color?: string;
}

export interface PaperDetail extends PaperOut {
  sections: SectionOut[];
  figures: FigureOut[];
  tables: TableOut[];
  method_steps: MethodStep[];
  pages?: { page_no: number; text: string }[];
  accent: string;
}

export interface EvidenceOut {
  id?: number;
  page: number;
  region: string;
  region_type: string;
  text: string;
  quote: string;
  confidence: number;
}

export interface ClaimSummary {
  claim_id: string;
  statement: string;
  type: string;
  confidence: number;
  status: string;
  evidence_count: number;
}

export interface ClaimOut {
  id?: number;
  claim_id: string;
  statement: string;
  type: string;
  confidence: number;
  status: string;
  rationale: string;
  evidence: EvidenceOut[];
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  props: Record<string, any>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
}

export interface GraphOut {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ScenedNarration {
  script?: string;
  tts_text?: string;
  subtitle?: string;
  audio_url?: string;
}

export interface SceneOut {
  order: number;
  title: string;
  kind: string;
  summary: string;
  steps: any[];
  evidence_refs: any[];
  figure_refs: number[];
  table_refs?: number[];
  narration: ScenedNarration;
  linked?: any[];
}

export interface PresentationOut {
  scenes: SceneOut[];
}

export interface AskResponse {
  answer: string;
  grounded: boolean;
  confidence: string;
  evidence: EvidenceOut[];
  note: string;
}

export interface EvaluationOut {
  overall_score: number;
  metrics: Record<string, any>;
}

export interface DemoPaperListItem {
  slug: string;
  title: string;
  subtitle: string;
  domain: string;
  year: number;
  tags: string[];
  abstract: string;
  accent: string;
  source_mode: string;
}

export type ViewMode =
  | 'map'
  | 'method'
  | 'claim'
  | 'graph'
  | 'presenter'
  | 'qa'
  | 'eval'
  | 'paper';
