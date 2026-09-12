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
  /** 步骤所属章节标题（后端按"方法/实验章归属"给出；同章步骤会相同）。 */
  phase?: string;
  detail?: string;
  text?: string;
  /** 兼容字段：第一个关联图。 */
  figure_ref?: number;
  /** **该步骤自己的**关联图/表编号（可能多个）——不再回退到"全篇第一张图"。 */
  figure_refs?: number[];
  table_refs?: number[];
  /** 图表编号 → 来源方法（`explicit_block_ref`/`caption_ref`/`page_proximity`）。
   *  `page_proximity` 是**位置推断**（同页/相邻页），UI 必须如实标注（ADR-0059）。 */
  figure_ref_methods?: Record<string, string>;
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
  // --- canonical 扩展（后端 `adapters.to_legacy_evidence` 已返回）---
  evidence_id?: string;
  anchor_id?: string;
  locator_status?: string;
  /** 证据的支撑结论：supports / contradicts / insufficient / unreviewed。 */
  verification_status?: string;
  media_ids?: string[];
  confidence_assessed?: boolean;
  confidence_method?: string;
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
  // --- canonical 扩展（后端 `adapters.to_legacy_claim` 已返回）---
  statement_id?: string;
  /** 断言的真实校验状态：verified / inference / contested / unverified / rejected。 */
  verification_status?: string;
  visibility?: string;
  revision_id?: string;
  confidence_assessed?: boolean;
  evidence_ids?: string[];
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
  /** 回答模式：generated/extractive/cached/abstained/general（ADR-0057）。
   *  ``general`` = 与论文无关的通用回答（未使用原文证据）。 */
  mode?: string;
}

export interface EvaluationOut {
  // 未评估时是 null，不是 0（ADR-0055）；AI 口径见 metrics.ai_overall_score（ADR-0056）
  overall_score: number | null;
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
