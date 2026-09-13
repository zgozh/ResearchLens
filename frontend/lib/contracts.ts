// Canonical DTO 类型 —— 精确镜像 docs/REFACTOR_SPEC.md §5.1–5.9 / §5.12。
// 规格版本 rl.contract/1。时间统一 UTC ISO8601，前端按用户时区显示。
// 旧 lib/types.ts（legacy DTO）保留接口名与调用签名；本文件只增不改。

import type { PaperOut } from './types';

/* ============ §5.1 全局规则与基础类型 ============ */

/** UUID 字符串；后端可用 DB UUID 或 String(36)。不从图号/列表下标生成。 */
export type Id = string;
/** 正整数，保留已有 int 身份。 */
export type PaperId = number;
export type JobId = number;
export type LegacyEvidenceId = number;
/** 各自语义的 Id，不可混用。 */
export type RevisionId = Id;
export type AssetId = Id;
export type AnchorId = Id;
export type BlockId = Id;
export type MediaId = Id;
export type StatementId = Id;
/** 非空 ASCII 字符串，长度 ≤32；(paper_id, revision_id) 内唯一。 */
export type PublicClaimId = string;
/** 小写 SHA256 十六进制 64 位。 */
export type Hash = string;
/** 有限 float，0..1；NaN/Infinity 拒绝；未评估必须 null（由字段声明 `Score|null`）。 */
export type Score = number;

export interface Scope {
  paper_id: PaperId;
  revision_id: RevisionId;
}

export type Point = [number, number];
export type Rect = [number, number, number, number];
/** 四点数组，归一化 0..1，不自交。 */
export type Quad = Point[];

export type Origin = 'source_extraction' | 'generated' | 'synthetic';

export type ArtifactKind =
  | 'claim'
  | 'statement'
  | 'section'
  | 'method_step'
  | 'scene'
  | 'graph_node'
  | 'graph_edge'
  | 'answer';

export interface ArtifactRef {
  kind: ArtifactKind;
  id: string;
}

export interface Warning {
  code: string;
  message: string;
  stage: string | null;
}

export interface PageResult<T> {
  items: T[];
  next_cursor: string | null;
  total: number;
}

export interface FieldError {
  path: string;
  reason: string;
}

export type ErrorCode =
  | 'NOT_FOUND'
  | 'INVALID_INPUT'
  | 'CONFLICT'
  | 'REVISION_MISMATCH'
  | 'AMBIGUOUS_REFERENCE'
  | 'UNSUPPORTED_MEDIA'
  | 'PAYLOAD_TOO_LARGE'
  | 'FORBIDDEN'
  | 'RATE_LIMITED'
  | 'DEPENDENCY_UNAVAILABLE'
  | 'DEADLINE_EXCEEDED'
  | 'INTERNAL_ERROR'
  | 'CANCELLED'
  | 'EVIDENCE_REJECTED';

export interface DomainError {
  code: ErrorCode;
  message: string;
  retryable: boolean;
  request_id: Id;
  field_errors: FieldError[];
  retry_after_ms: number | null;
}

/* ============ §5.2 文档、页码、块与定位 ============ */

export type SourceMode = 'demo' | 'real' | 'upload';
export type ProvenanceClass = 'synthetic' | 'source_document';

export interface PaperRecord {
  id: PaperId;
  slug: string; // ≤64
  title: string;
  source_mode: SourceMode;
  provenance_class: ProvenanceClass;
  status: 'pending' | 'processing' | 'ready' | 'failed';
  published_revision_id: RevisionId | null;
  readable_revision_id: RevisionId | null;
  created_at: string;
  updated_at: string;
}

export type Acquisition = 'upload' | 'url' | 'seed';

export interface SourceDocument {
  id: Id;
  paper_id: PaperId;
  sha256: Hash;
  asset_id: AssetId;
  byte_size: number;
  mime: 'application/pdf';
  page_count: number;
  source_url: string | null; // 去除访问凭据
  original_filename: string | null;
  acquisition: Acquisition;
  created_at: string;
}

export interface Revision {
  id: RevisionId;
  paper_id: PaperId;
  source_document_id: Id | null;
  kind: 'source' | 'legacy' | 'synthetic';
  state: 'staging' | 'readable' | 'published' | 'superseded' | 'failed';
  parser_name: string;
  parser_version: string;
  normalizer_version: string;
  prompt_version: string;
  model_snapshot_id: Id | null;
  artifact_digest: Hash | null;
  quality: 'complete' | 'partial' | 'source_only';
  warnings: Warning[];
  created_at: string;
}

export interface Page extends Scope {
  id: Id;
  pdf_page_index: number; // ≥0
  pdf_page_no: number; // ≥1
  page_label: string | null;
  label_status: 'verified' | 'candidate' | 'ambiguous' | 'unknown';
  width_pt: number; // >0
  height_pt: number; // >0
  rotation: 0 | 90 | 180 | 270;
  cropbox_pdf: [number, number, number, number];
  text: string;
  text_origin: 'source_extraction';
  preview_asset_id: AssetId | null;
  extraction_quality: 'text' | 'ocr' | 'image_only' | 'empty';
}

export interface PageLabelMapping extends Scope {
  id: Id;
  page_label: string;
  pdf_page_index: number;
  method: 'pdf_metadata' | 'printed_ocr' | 'manual';
  status: 'verified' | 'candidate' | 'ambiguous';
  source_block_ids: BlockId[];
  confidence: Score | null;
  review_id: Id | null;
}

export type BlockKind =
  | 'heading'
  | 'paragraph'
  | 'caption'
  | 'table'
  | 'equation'
  | 'image'
  | 'header'
  | 'footer'
  | 'page_number'
  | 'other';

export interface RawRef {
  asset_id: AssetId;
  record_path: string; // 受控解析索引
  native_id: string | null;
  bbox_values: number[] | null;
  bbox_units: 'pixel' | 'point' | 'normalized' | 'unknown';
  coordinate_frame: string | null;
}

export interface Block extends Scope {
  id: BlockId;
  page_id: Id;
  ordinal: number;
  kind: BlockKind;
  text: string;
  origin: 'source_extraction';
  anchor_id: AnchorId | null;
  media_id: MediaId | null;
  section_path: string[];
  raw_ref: RawRef;
  language: string;
  content_hash: Hash;
}

export interface CoordinateTransform {
  raw_to_canonical: number[]; // 3×3 仿射/齐次矩阵，float[9]
  canonical_to_pdf_unrotated: number[]; // float[9]
  adapter_version: string;
}

export interface QuoteSpan {
  block_id: BlockId;
  start_cp: number; // ≥0，Unicode code point 半开区间
  end_cp: number; // >start_cp
  source_text: string;
  match_method: 'exact' | 'normalized';
  normalizer_version: string | null;
}

export interface AnchorSegment {
  page_id: Id;
  pdf_page_index: number;
  page_label: string | null;
  rect: Rect | null; // page-only 必须 null
  quads: Quad[];
  block_ids: BlockId[];
  quote_spans: QuoteSpan[];
}

export interface Anchor extends Scope {
  id: AnchorId;
  source_document_id: Id;
  precision: 'region' | 'page';
  segments: AnchorSegment[];
  transform: CoordinateTransform | null;
  raw_ref: RawRef | null;
  created_at: string;
}

export interface NavigationTarget extends Scope {
  anchor_id: AnchorId;
  segment_index: number; // ≥0
}

export interface NavigationResult {
  target: NavigationTarget;
  status: 'region_highlighted' | 'page_opened' | 'unavailable';
  reason: string | null;
}

/* ============ §5.3 资产与图表公式 ============ */

export type AssetKind =
  | 'source_pdf'
  | 'parser_raw'
  | 'crop'
  | 'thumbnail'
  | 'page_preview'
  | 'extracted_html'
  | 'synthetic_svg';

export interface Asset {
  id: AssetId;
  paper_id: PaperId;
  revision_id: RevisionId | null;
  sha256: Hash;
  mime: string;
  byte_size: number;
  width_px: number | null;
  height_px: number | null;
  kind: AssetKind;
  url: string; // 后端受控资源地址
  created_at: string;
}

export type MediaKind = 'figure' | 'table' | 'equation' | 'page_preview';

export type Representation =
  | 'pdf_crop'
  | 'mineru_crop'
  | 'extracted'
  | 'synthetic';

export type Verification = 'source_bound' | 'unverified' | 'synthetic';

export interface MediaProvenance {
  representation: Representation;
  source_document_id: Id | null;
  source_sha256: Hash | null;
  raw_asset_id: AssetId | null;
  transform: 'crop' | 'resize' | 'none';
  renderer_version: string | null;
  verification: Verification;
}

export interface TableCell {
  row: number; // ≥0
  col: number; // ≥0
  rowspan: number; // ≥1
  colspan: number; // ≥1
  text: string;
  is_header: boolean;
  anchor_id: AnchorId | null;
}

export interface ExtractedMedia {
  table_html: string | null; // 不可信提取 HTML，不预设已安全
  table_cells: TableCell[];
  latex: string | null;
  equation_label: string | null;
  origin: 'source_extraction';
  warnings: Warning[];
}

export interface Media extends Scope {
  id: MediaId;
  kind: MediaKind;
  original_label: string | null;
  legacy_no: number | null;
  caption: string;
  anchor_ids: AnchorId[];
  original_asset_ids: AssetId[];
  thumbnail_asset_id: AssetId | null;
  extracted: ExtractedMedia | null;
  provenance: MediaProvenance;
  excluded: boolean;
  exclusion_reason: string | null;
}

export type MediaViewMode = 'original' | 'extracted' | 'synthetic' | 'unavailable';

export interface MediaViewPolicy {
  default_mode: MediaViewMode;
  original_asset_ids: AssetId[];
  fallback_page_ids: Id[];
  label: string;
  warnings: Warning[];
}

export interface MediaLinkCandidate {
  media_id: MediaId;
  via_anchor_ids: AnchorId[];
  method: 'explicit_block_ref' | 'caption_ref' | 'same_page' | 'legacy_regex';
  score: Score | null;
  reason: string;
}

/* ============ §5.4 Evidence-first、断言与生成产物 ============ */

export type StatementKind = 'fact' | 'inference' | 'quote' | 'transition';

export interface CitationCandidate {
  block_id: BlockId;
  proposed_quote: string;
  media_id: MediaId | null;
}

export interface StatementDraft extends Scope {
  id: StatementId;
  claim_id: PublicClaimId;
  text: string;
  kind: StatementKind;
  citations: CitationCandidate[];
  qualifiers: string[];
}

export interface EvidenceRecord extends Scope {
  id: Id;
  legacy_id: LegacyEvidenceId | null;
  claim_id: PublicClaimId;
  source_document_id: Id;
  anchor_id: AnchorId;
  source_page: number; // ≥1
  source_region: AnchorSegment[];
  source_text: string;
  quote_spans: QuoteSpan[];
  media_ids: MediaId[];
  confidence: Score | null;
  confidence_method: string | null;
  locator_status: 'exact' | 'page_only';
  support_status: 'supports' | 'contradicts' | 'insufficient' | 'unreviewed';
  validation_id: Id;
}

export type ValidationReasonCode =
  | 'missing_source'
  | 'wrong_scope'
  | 'quote_mismatch'
  | 'ambiguous_page'
  | 'coordinate_missing'
  | 'unsupported_entailment'
  | 'numeric_mismatch'
  | 'qualifier_missing'
  | 'contradiction'
  | 'budget_exhausted'
  | 'external_unavailable'
  | 'passed';

export interface ValidationReason {
  code: ValidationReasonCode;
  message: string;
  block_ids: BlockId[];
}

export type DisplayClass =
  | 'verified_fact'
  | 'attributed_quote'
  | 'inference'
  | 'unverified'
  | 'transition';

export interface ValidationReport extends Scope {
  id: Id;
  statement_id: StatementId;
  locator_valid: boolean;
  quote_valid: boolean;
  scope_valid: boolean;
  semantic_status: 'supports' | 'contradicts' | 'insufficient' | 'unreviewed';
  numeric_status: 'pass' | 'fail' | 'not_applicable' | 'unreviewed';
  qualifier_status: 'pass' | 'fail' | 'unreviewed';
  decision: 'verified' | 'inference' | 'contested' | 'unverified' | 'rejected';
  evidence: EvidenceRecord[];
  reasons: ValidationReason[];
  assessor: 'rule' | 'model' | 'human';
  assessor_version: string;
  confidence: Score | null;
  created_at: string;
}

export interface VerifiedStatement extends StatementDraft {
  validation: ValidationReport;
  evidence_ids: Id[];
  origin: 'generated' | 'source_extraction';
  display_class: DisplayClass;
}

export type ClaimType = 'RESULT' | 'METHOD' | 'LIMITATION' | 'CONTEXT';

export interface ClaimRecord extends Scope {
  id: Id;
  legacy_id: number | null;
  claim_id: PublicClaimId;
  statement_id: StatementId;
  type: ClaimType;
  status: 'verified' | 'inference' | 'contested' | 'unverified' | 'rejected';
  rationale: string;
  evidence_ids: Id[];
  confidence: Score | null;
  visibility: 'exhibit' | 'answer_only';
}

export type SourceRefKind = 'evidence' | 'media' | 'anchor' | 'block';

export interface SourceRef {
  kind: SourceRefKind;
  id: Id;
}

export interface Binding extends Scope {
  id: Id;
  from: ArtifactRef;
  to: ArtifactRef | SourceRef;
  relation: 'supports' | 'contradicts' | 'illustrates' | 'mentions';
  method:
    | 'explicit_block_ref'
    | 'caption_ref'
    | 'verified_claim_join'
    | 'manual'
    | 'legacy_candidate';
  validation_id: Id | null;
  state: 'verified' | 'candidate' | 'rejected';
  reason: string;
  score: Score | null;
  created_at: string;
}

export interface StatementSpan {
  start_cp: number;
  end_cp: number;
  statement_id: StatementId;
}

export interface ArtifactText {
  text: string;
  spans: StatementSpan[];
}

export interface SectionRecord extends Scope {
  id: Id;
  heading: string;
  kind: string;
  source_block_ids: BlockId[];
  anchor_ids: AnchorId[];
  summary: ArtifactText;
  key_points: ArtifactText[];
}

export type MapItemKind = 'problem' | 'method' | 'result' | 'limitation';

export interface MapItem {
  id: Id;
  kind: MapItemKind;
  text: ArtifactText;
  claim_ids: PublicClaimId[];
  anchor_ids: AnchorId[];
}

export interface MapArtifact extends Scope {
  id: Id;
  items: MapItem[];
}

export interface MethodStepRecord extends Scope {
  id: Id;
  order: number;
  label: ArtifactText;
  detail: ArtifactText;
  phase: string | null;
  claim_ids: PublicClaimId[];
  media_ids: MediaId[];
  binding_ids: Id[];
}

/* ============ §5.5 图谱、场景与讲解 ============ */

export type GraphNodeKind =
  | 'problem'
  | 'method'
  | 'experiment'
  | 'claim'
  | 'evidence'
  | 'limitation';

export interface GraphNodeRecord {
  id: Id;
  kind: GraphNodeKind;
  label: ArtifactText;
  claim_id: PublicClaimId | null;
  evidence_id: Id | null;
  anchor_ids: AnchorId[];
  status: 'verified' | 'inference' | 'contested' | 'unverified';
}

export interface GraphEdgeRecord {
  id: Id;
  source: Id;
  target: Id;
  relation: 'supports' | 'contradicts' | 'illustrates' | 'depends_on' | 'mentions';
  label: ArtifactText;
  binding_ids: Id[];
  status: 'verified' | 'candidate';
}

export interface GraphArtifact extends Scope {
  id: Id;
  nodes: GraphNodeRecord[];
  edges: GraphEdgeRecord[];
}

export interface SubtitleCue {
  id: Id;
  start_ms: number | null;
  end_ms: number | null;
  text: ArtifactText;
}

export interface NarrationRecord {
  script: ArtifactText;
  tts_text: ArtifactText;
  subtitle_cues: SubtitleCue[];
  audio_url: string | null;
}

export interface SceneRecord extends Scope {
  id: Id;
  order: number;
  title: ArtifactText;
  kind: string;
  summary: ArtifactText;
  step_ids: Id[];
  statement_ids: StatementId[];
  claim_ids: PublicClaimId[];
  binding_ids: Id[];
  media_ids: MediaId[];
  narration: NarrationRecord;
}

export interface PresentationArtifact extends Scope {
  id: Id;
  scenes: SceneRecord[];
  warnings: Warning[];
}

/* ============ §5.6 AI 与检索 ============ */

export interface ModelSnapshot {
  id: Id;
  provider: 'dashscope';
  base_url: string;
  chat_model: string;
  embedding_model: string | null;
  embedding_dimension: number | null;
  capability_version: string;
  temperature: number;
  created_at: string;
}

export interface ModelCapabilities {
  model: string;
  purposes: ('chat' | 'embedding')[];
  json_schema: boolean | null;
  json_object: boolean | null;
  streaming: boolean | null;
  embedding_dimension: number | null;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface Usage {
  input_tokens: number | null;
  output_tokens: number | null;
  elapsed_ms: number;
}

export interface Chunk extends Scope {
  id: Id;
  block_ids: BlockId[];
  anchor_ids: AnchorId[];
  text: string;
  section_path: string[];
  media_ids: MediaId[];
  content_hash: Hash;
  token_estimate: number;
  embedding_space: string | null;
}

export interface RetrievalRequest {
  scope: Scope;
  query: string;
  top_k: number; // 1..20，默认 5
  mode: 'lexical' | 'hybrid'; // 默认 hybrid
  max_context_tokens: number;
  rerank: boolean;
}

export interface RetrievalHit {
  chunk_id: Id;
  block_ids: BlockId[];
  anchor_ids: AnchorId[];
  media_ids: MediaId[];
  text: string;
  lexical_score: number | null;
  vector_score: number | null;
  rrf_score: number;
  rerank_score: number | null;
  rank: number;
}

export interface RetrievalResult {
  scope: Scope;
  hits: RetrievalHit[];
  mode_used: 'lexical' | 'hybrid';
  warnings: Warning[];
  elapsed_ms: number;
}

export interface IndexResult {
  scope: Scope;
  chunk_count: number;
  vector_count: number;
  embedding_space: string | null;
  status: 'ready' | 'lexical_only' | 'failed';
  warnings: Warning[];
}

/* ============ §5.7 问答与流式协议 ============ */

export interface QARequest {
  question: string; // 1..2000
  top_k: number; // 1..20，默认 5
  revision_id?: RevisionId;
}

export type AnswerMode = 'generated' | 'extractive' | 'cached' | 'abstained';

export interface AnswerRecord extends Scope {
  id: Id;
  question: string;
  text: ArtifactText;
  statements: VerifiedStatement[];
  evidence: EvidenceRecord[];
  grounded: boolean;
  confidence: 'High' | 'Medium' | 'Low';
  note: string;
  mode: AnswerMode;
  model_snapshot_id: Id | null;
  usage: Usage;
  warnings: Warning[];
}

export interface QAMeta {
  scope: Scope;
  answer_id: Id;
  deadline_at: string;
}

export interface QAStatus {
  stage: 'retrieving' | 'reranking' | 'drafting' | 'verifying' | 'degraded';
  message: string;
}

export interface QACitation {
  evidence: EvidenceRecord;
}

export interface QASentence {
  statement: VerifiedStatement;
}

export interface QAFinal {
  legacy: unknown; // AskResponse（旧 DTO，见 lib/types.ts）
  answer: AnswerRecord;
}

export interface QAError {
  error: DomainError;
  partial: boolean;
}

export type QAEventData = QAMeta | QAStatus | QACitation | QASentence | QAFinal | QAError;

export interface QAStreamEvent {
  event_id: number; // ≥1
  request_id: Id;
  type: 'meta' | 'status' | 'citation' | 'sentence' | 'final' | 'error';
  data: QAEventData;
}

/* ============ §5.8 持久任务、Agent 工具与事件 ============ */

export type Stage =
  | 'acquire'
  | 'parse'
  | 'normalize'
  | 'media'
  | 'index'
  | 'claims'
  | 'verify'
  | 'exhibits'
  | 'qa_bank'
  | 'evaluate'
  | 'publish';

export type SourceInput =
  | { kind: 'stored'; source_document_id: Id }
  | { kind: 'pending_upload'; asset_id: AssetId }
  | { kind: 'url'; url: string; title: string };

export interface JobRecord {
  id: JobId;
  paper_id: PaperId;
  revision_id: RevisionId | null;
  state: 'queued' | 'running' | 'retry_wait' | 'succeeded' | 'partial' | 'failed' | 'cancelled';
  stage: Stage;
  progress: number; // 0..1
  attempt: number;
  lease_owner: string | null;
  lease_until: string | null;
  fence: number;
  cancel_requested: boolean;
  error: DomainError | null;
  model_snapshot: ModelSnapshot;
  created_at: string;
  updated_at: string;
}

export interface StageResult {
  stage: Stage;
  status: 'succeeded' | 'partial' | 'failed' | 'skipped';
  artifact_ids: Id[];
  artifact_digest: Hash | null;
  usage: Usage;
  warnings: Warning[];
  error: DomainError | null;
}

export interface JobLease {
  job_id: JobId;
  worker_id: string;
  fence: number;
  expires_at: string;
}

export type ToolName =
  | 'retrieve_blocks'
  | 'get_blocks'
  | 'get_media'
  | 'validate_statement'
  | 'submit_candidate';

export interface JobEventData {
  stage: Stage;
  progress: number;
  message: string;
  tool: ToolName | null;
  artifact_ids: Id[];
  elapsed_ms: number | null;
  usage: Usage | null;
  error: DomainError | null;
}

export interface JobEvent {
  event_id: number; // ≥1
  job_id: JobId;
  occurred_at: string;
  type:
    | 'stage_started'
    | 'stage_finished'
    | 'tool_started'
    | 'tool_finished'
    | 'retry_scheduled'
    | 'degraded'
    | 'completed'
    | 'failed'
    | 'cancelled';
  data: JobEventData;
}

export type ToolArgs = Record<string, unknown>;

export interface ToolCall {
  id: Id;
  role: 'analyst' | 'verifier' | 'presenter';
  name: ToolName;
  args: ToolArgs;
}

export interface ToolResult {
  call_id: Id;
  status: 'ok' | 'rejected' | 'error';
  payload: unknown;
  error: DomainError | null;
}

export type SupervisorAction = 'accept' | 'retrieve_more' | 'repair' | 'abstain';

export interface SupervisorDecision {
  action: SupervisorAction;
  statement_id: StatementId;
  reason_code: ValidationReasonCode;
  next_query: string | null;
}

/* ============ §5.9 评估、复核与导出 ============ */

export interface MetricValue {
  value: number | null;
  unit: 'ratio' | 'percent' | 'count' | 'ms' | 'tokens';
  numerator: number | null;
  denominator: number | null;
  sample_size: number;
  method: string;
  status: 'measured' | 'proxy' | 'not_evaluated';
}

export interface MetricEntry {
  name: string;
  value: MetricValue;
}

export interface NavigationCheck {
  anchor_id: AnchorId;
  page_correct: boolean;
  region_iou: Score | null;
  latency_ms: number;
}

export interface GoldenClaim {
  id: string;
  scope: Scope;
  text: string;
  expected_support: 'supports' | 'contradicts' | 'insufficient';
  acceptable_block_ids: BlockId[];
}

export interface GoldenQuestion {
  id: string;
  scope: Scope;
  question: string;
  answerable: boolean;
  required_points: string[];
  acceptable_block_ids: BlockId[];
}

export interface GoldenAnchor {
  id: string;
  scope: Scope;
  expected_page_index: number;
  expected_rect: Rect | null;
  source_label: string;
}

export interface GoldenSet {
  id: string;
  version: string;
  source_hashes: Hash[];
  claims: GoldenClaim[];
  questions: GoldenQuestion[];
  anchors: GoldenAnchor[];
}

export interface EvaluationInput {
  scope: Scope;
  statements: VerifiedStatement[];
  media: Media[];
  bindings: Binding[];
  answers: AnswerRecord[];
  navigation_checks: NavigationCheck[];
  golden: GoldenSet | null;
}

export interface EvaluationReport extends Scope {
  id: Id;
  version: string;
  overall_score: number | null;
  metrics: MetricEntry[];
  golden_id: string | null;
  computed_at: string;
  warnings: Warning[];
}

export type ReviewDecision = 'confirm' | 'reject' | 'correct_page_label';

export interface ReviewRequest {
  scope: Scope;
  target: ArtifactRef | SourceRef;
  decision: ReviewDecision;
  reason: string;
  corrected_page_index: number | null;
  page_label: string | null;
  expected_validation_id: Id | null;
}

export interface ReviewRecord {
  id: Id;
  request: ReviewRequest;
  reviewer: string;
  created_at: string;
  applied_revision_id: RevisionId | null;
  job_id: JobId | null;
}

export interface EvidenceExport {
  schema_version: 'rl.contract/1';
  scope: Scope;
  source_sha256: Hash | null;
  claims: ClaimRecord[];
  statements: VerifiedStatement[];
  evidence: EvidenceRecord[];
  media: Media[];
  validations: ValidationReport[];
  generated_at: string;
}

/* ============ §5.12 新增 HTTP API ============ */

/** Page 去掉 text，保留 extraction_quality/preview_asset_id。 */
export type PageSummary = Omit<Page, 'text'>;

export interface PageContent {
  page: Page;
  blocks: Block[];
  anchors: Anchor[];
}

export interface Capability {
  name: 'pdf' | 'text' | 'media' | 'claims' | 'graph' | 'presentation' | 'qa' | 'evaluation';
  state: 'ready' | 'partial' | 'pending' | 'unavailable';
  reason: string | null;
}

export interface SectionIndexEntry {
  id: Id;
  heading: string;
  anchor_ids: AnchorId[];
}

export interface MediaIndexEntry {
  id: MediaId;
  kind: MediaKind;
  label: string | null;
  thumbnail_asset_id: AssetId | null;
}

export interface PaperManifest {
  paper: PaperOut; // 旧 DTO 字段类型；map_summary/method_steps 为空，由 exhibits 承载
  revision: Revision | null;
  provenance_class: ProvenanceClass;
  source: SourceDocument | null;
  page_count: number;
  section_index: SectionIndexEntry[];
  media_index: MediaIndexEntry[];
  assets: Asset[];
  capabilities: Capability[];
  active_job: JobRecord | null;
  warnings: Warning[];
}

export interface StructureArtifact extends Scope {
  sections: SectionRecord[];
  map: MapArtifact;
  method_steps: MethodStepRecord[];
}

export interface ExhibitBundle {
  scope: Scope;
  structure: StructureArtifact;
  claims: ClaimRecord[];
  statements: VerifiedStatement[];
  graph: GraphArtifact;
  presentation: PresentationArtifact;
  evaluation: EvaluationReport;
  capabilities: Capability[];
}

/* ============ §5.13 前端运行时状态类型 ============ */

export type LoadStateStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface LoadState<T> {
  status: LoadStateStatus;
  data: T | null;
  error: DomainError | null;
}

export type StreamState =
  | 'idle'
  | 'connecting'
  | 'streaming'
  | 'completed'
  | 'failed'
  | 'cancelled'
  /**
   * R4-M4：**流读完了但没有 `final`**。
   *
   * 以前这种情况被无条件写成 `completed`，于是"没有结果"看起来像"有结果"，
   * 调用方把它渲染成「回答被中断 · 置信度 Low」——一个像业务结论的连接层异常。
   * 现在它是一个独立状态：调用方走恢复链（按 answer_id 取回 → 非流式兜底 → 如实报错）。
   */
  | 'recovering';
