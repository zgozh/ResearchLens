// Static fixtures —— 组件层在 canonical 后端端点未就绪前用这些 mock 数据开发。
// 由 lib/contracts.ts 类型构造；api.ts 里 USE_FIXTURES 开关控制切换。

import type {
  Anchor,
  AnchorSegment,
  Asset,
  Block,
  Capability,
  ClaimRecord,
  DomainError,
  EvidenceExport,
  EvidenceRecord,
  ExhibitBundle,
  Hash,
  Id,
  JobEvent,
  JobRecord,
  Media,
  MediaViewPolicy,
  Page,
  PageContent,
  PageResult,
  PageSummary,
  PaperId,
  PaperManifest,
  QAStreamEvent,
  Revision,
  RevisionId,
  Scope,
  SourceDocument,
  StatementId,
  StructureArtifact,
  ValidationReport,
  VerifiedStatement,
} from './contracts';
import type { PaperOut } from './types';

export const FIXTURE_PAPER_ID: PaperId = 1;
export const FIXTURE_REVISION_ID: RevisionId = '00000000-0000-4000-8000-000000000001';
export const FIXTURE_SOURCE_ID: Id = '00000000-0000-4000-8000-000000000010';
export const FIXTURE_HASH: Hash = 'a'.repeat(64);
export const FIXTURE_ANCHOR_ID: Id = '00000000-0000-4000-8000-0000000000a1';
export const FIXTURE_MEDIA_FIG_ID: Id = '00000000-0000-4000-8000-0000000000b1';
export const FIXTURE_MEDIA_TAB_ID: Id = '00000000-0000-4000-8000-0000000000b2';
export const FIXTURE_EVIDENCE_ID: Id = '00000000-0000-4000-8000-0000000000e1';
export const FIXTURE_CLAIM_ID = 'claim_01';

export function makeScope(paperId: PaperId = FIXTURE_PAPER_ID, revisionId: RevisionId = FIXTURE_REVISION_ID): Scope {
  return { paper_id: paperId, revision_id: revisionId };
}

function iso(daysAgo = 0): string {
  return new Date(Date.now() - daysAgo * 86400000).toISOString();
}

function makeAsset(id: Id, kind: Asset['kind'], mime: string, label: string): Asset {
  return {
    id,
    paper_id: FIXTURE_PAPER_ID,
    revision_id: FIXTURE_REVISION_ID,
    sha256: FIXTURE_HASH,
    mime,
    byte_size: 1024,
    width_px: 1200,
    height_px: 800,
    kind,
    url: `/api/assets/${id}`,
    created_at: iso(1),
  };
}

export const fixtureAssets: Asset[] = [
  makeAsset('00000000-0000-4000-8000-0000000000c1', 'crop', 'image/png', 'fig crop'),
  makeAsset('00000000-0000-4000-8000-0000000000c2', 'thumbnail', 'image/png', 'fig thumb'),
  makeAsset('00000000-0000-4000-8000-0000000000c3', 'page_preview', 'image/png', 'page preview'),
];

function makePage(index: number, label: string | null): Page {
  return {
    ...makeScope(),
    id: `00000000-0000-4000-8000-0000000000p${index + 1}`,
    pdf_page_index: index,
    pdf_page_no: index + 1,
    page_label: label,
    label_status: label ? 'verified' : 'unknown',
    width_pt: 595,
    height_pt: 842,
    rotation: 0,
    cropbox_pdf: [0, 0, 595, 842],
    text: `第 ${index + 1} 页原文（fixture）。`,
    text_origin: 'source_extraction',
    preview_asset_id: '00000000-0000-4000-8000-0000000000c3',
    extraction_quality: 'text',
  };
}

function makeAnchorSegment(pageIndex: number, rect: [number, number, number, number] | null): AnchorSegment {
  const quads: [number, number][][] = rect
    ? [
        [
          [rect[0], rect[1]],
          [rect[2], rect[1]],
          [rect[2], rect[3]],
          [rect[0], rect[3]],
        ],
      ]
    : [];
  return {
    page_id: `00000000-0000-4000-8000-0000000000p${pageIndex + 1}`,
    pdf_page_index: pageIndex,
    page_label: pageIndex === 0 ? '3' : null,
    rect,
    quads,
    block_ids: [],
    quote_spans: [],
  };
}

export function fixtureAnchor(): Anchor {
  return {
    ...makeScope(),
    id: FIXTURE_ANCHOR_ID,
    source_document_id: FIXTURE_SOURCE_ID,
    precision: 'region',
    segments: [makeAnchorSegment(0, [0.12, 0.2, 0.6, 0.5])],
    transform: null,
    raw_ref: null,
    created_at: iso(1),
  };
}

export function fixtureMedia(mediaId: Id = FIXTURE_MEDIA_FIG_ID): Media {
  return {
    ...makeScope(),
    id: mediaId,
    kind: 'figure',
    original_label: '图 2',
    legacy_no: 2,
    caption: '示例图：可追溯的 PDF 区域裁剪。',
    anchor_ids: [FIXTURE_ANCHOR_ID],
    original_asset_ids: ['00000000-0000-4000-8000-0000000000c1'],
    thumbnail_asset_id: '00000000-0000-4000-8000-0000000000c2',
    extracted: null,
    provenance: {
      representation: 'pdf_crop',
      source_document_id: FIXTURE_SOURCE_ID,
      source_sha256: FIXTURE_HASH,
      raw_asset_id: null,
      transform: 'crop',
      renderer_version: '1.0',
      verification: 'source_bound',
    },
    excluded: false,
    exclusion_reason: null,
  };
}

export function fixtureTableMedia(): Media {
  return {
    ...makeScope(),
    id: FIXTURE_MEDIA_TAB_ID,
    kind: 'table',
    original_label: '表 1',
    legacy_no: 1,
    caption: '示例表：保留 rowspan/colspan。',
    anchor_ids: [FIXTURE_ANCHOR_ID],
    original_asset_ids: [],
    thumbnail_asset_id: null,
    extracted: {
      table_html: '<table><thead><tr><th>方法</th><th>指标</th></tr></thead><tbody><tr><td rowspan="2">A</td><td>0.91</td></tr><tr><td>0.87</td></tr></tbody></table>',
      table_cells: [
        { row: 0, col: 0, rowspan: 1, colspan: 1, text: '方法', is_header: true, anchor_id: null },
        { row: 0, col: 1, rowspan: 1, colspan: 1, text: '指标', is_header: true, anchor_id: null },
        { row: 1, col: 0, rowspan: 2, colspan: 1, text: 'A', is_header: false, anchor_id: null },
        { row: 1, col: 1, rowspan: 1, colspan: 1, text: '0.91', is_header: false, anchor_id: null },
        { row: 2, col: 1, rowspan: 1, colspan: 1, text: '0.87', is_header: false, anchor_id: null },
      ],
      latex: null,
      equation_label: null,
      origin: 'source_extraction',
      warnings: [],
    },
    provenance: {
      representation: 'mineru_crop',
      source_document_id: FIXTURE_SOURCE_ID,
      source_sha256: FIXTURE_HASH,
      raw_asset_id: null,
      transform: 'crop',
      renderer_version: '1.0',
      verification: 'source_bound',
    },
    excluded: false,
    exclusion_reason: null,
  };
}

export function fixturePolicy(media: Media, assets: Asset[] = fixtureAssets): MediaViewPolicy {
  const originalIds = media.original_asset_ids.filter((id) => assets.some((a) => a.id === id));
  return {
    default_mode: originalIds.length > 0 ? 'original' : 'extracted',
    original_asset_ids: originalIds,
    fallback_page_ids: [],
    label: originalIds.length > 0 ? '原件' : '再排版 / 提取',
    warnings: [],
  };
}

function makeBlock(id: Id, kind: Block['kind'], text: string, pageIndex: number): Block {
  return {
    ...makeScope(),
    id,
    page_id: `00000000-0000-4000-8000-0000000000p${pageIndex + 1}`,
    ordinal: 0,
    kind,
    text,
    origin: 'source_extraction',
    anchor_id: FIXTURE_ANCHOR_ID,
    media_id: null,
    section_path: ['方法'],
    raw_ref: { asset_id: '', record_path: 'fixture', native_id: null, bbox_values: null, bbox_units: 'unknown', coordinate_frame: null },
    language: 'zh',
    content_hash: FIXTURE_HASH,
  };
}

export function fixtureEvidence(scope: Scope = makeScope()): EvidenceRecord {
  return {
    ...scope,
    id: FIXTURE_EVIDENCE_ID,
    legacy_id: null,
    claim_id: FIXTURE_CLAIM_ID,
    source_document_id: FIXTURE_SOURCE_ID,
    anchor_id: FIXTURE_ANCHOR_ID,
    source_page: 3,
    source_region: [makeAnchorSegment(0, [0.12, 0.2, 0.6, 0.5])],
    source_text: '该方法的准确率达到 0.91。',
    quote_spans: [],
    media_ids: [FIXTURE_MEDIA_FIG_ID],
    confidence: 0.92,
    confidence_method: 'model_score',
    locator_status: 'exact',
    support_status: 'supports',
    validation_id: '00000000-0000-4000-8000-0000000000v1',
  };
}

function makeStatement(id: StatementId, text: string, display: VerifiedStatement['display_class']): VerifiedStatement {
  return {
    ...makeScope(),
    id,
    claim_id: FIXTURE_CLAIM_ID,
    text,
    kind: 'fact',
    citations: [],
    qualifiers: [],
    validation: {
      ...makeScope(),
      id: `v-${id}`,
      statement_id: id,
      locator_valid: true,
      quote_valid: true,
      scope_valid: true,
      semantic_status: 'supports',
      numeric_status: 'pass',
      qualifier_status: 'pass',
      decision: 'verified',
      evidence: [fixtureEvidence()],
      reasons: [{ code: 'passed', message: 'fixture', block_ids: [] }],
      assessor: 'model',
      assessor_version: '1.0',
      confidence: 0.92,
      created_at: iso(1),
    },
    evidence_ids: [FIXTURE_EVIDENCE_ID],
    origin: 'generated',
    display_class: display,
  };
}

export function fixtureClaim(): ClaimRecord {
  return {
    ...makeScope(),
    id: '00000000-0000-4000-8000-0000000000cl1',
    legacy_id: null,
    claim_id: FIXTURE_CLAIM_ID,
    statement_id: '00000000-0000-4000-8000-0000000000st1',
    type: 'RESULT',
    status: 'verified',
    rationale: '依据原文区域裁剪与精确引用。',
    evidence_ids: [FIXTURE_EVIDENCE_ID],
    confidence: 0.92,
    visibility: 'exhibit',
  };
}

export function fixtureRevision(): Revision {
  return {
    id: FIXTURE_REVISION_ID,
    paper_id: FIXTURE_PAPER_ID,
    source_document_id: FIXTURE_SOURCE_ID,
    kind: 'source',
    state: 'published',
    parser_name: 'mineru',
    parser_version: '1.0',
    normalizer_version: '1.0',
    prompt_version: '1.0',
    model_snapshot_id: null,
    artifact_digest: FIXTURE_HASH,
    quality: 'complete',
    warnings: [],
    created_at: iso(1),
  };
}

export function fixtureSource(): SourceDocument {
  return {
    id: FIXTURE_SOURCE_ID,
    paper_id: FIXTURE_PAPER_ID,
    sha256: FIXTURE_HASH,
    asset_id: '00000000-0000-4000-8000-0000000000c0',
    byte_size: 102400,
    mime: 'application/pdf',
    page_count: 3,
    source_url: null,
    original_filename: 'sample.pdf',
    acquisition: 'seed',
    created_at: iso(1),
  };
}

export function fixturePaperOut(): PaperOut {
  return {
    id: FIXTURE_PAPER_ID,
    slug: 'fixture-paper',
    title: '示例论文（fixture）',
    subtitle: '',
    authors: ['示例作者'],
    year: 2026,
    domain: '人工智能',
    abstract: '这是 fixture 论文摘要。',
    tags: ['fixture'],
    source_mode: 'demo',
    status: 'ready',
    map_summary: {},
    pdf_url: `/api/papers/${FIXTURE_PAPER_ID}/document`,
  };
}

export function fixtureManifest(paperId: PaperId = FIXTURE_PAPER_ID): PaperManifest {
  const capabilities: Capability[] = [
    { name: 'pdf', state: 'ready', reason: null },
    { name: 'media', state: 'ready', reason: null },
    { name: 'claims', state: 'ready', reason: null },
    { name: 'graph', state: 'ready', reason: null },
    { name: 'presentation', state: 'ready', reason: null },
    { name: 'qa', state: 'ready', reason: null },
    { name: 'evaluation', state: 'ready', reason: null },
    { name: 'text', state: 'ready', reason: null },
  ];
  return {
    paper: fixturePaperOut(),
    revision: fixtureRevision(),
    provenance_class: 'source_document',
    source: fixtureSource(),
    page_count: 3,
    section_index: [{ id: 's1', heading: '方法', anchor_ids: [FIXTURE_ANCHOR_ID] }],
    media_index: [
      { id: FIXTURE_MEDIA_FIG_ID, kind: 'figure', label: '图 2', thumbnail_asset_id: '00000000-0000-4000-8000-0000000000c2' },
      { id: FIXTURE_MEDIA_TAB_ID, kind: 'table', label: '表 1', thumbnail_asset_id: null },
    ],
    assets: fixtureAssets,
    capabilities,
    active_job: null,
    warnings: [],
  };
}

export function fixtureExhibits(scope: Scope = makeScope()): ExhibitBundle {
  const structure: StructureArtifact = {
    ...scope,
    sections: [
      {
        ...scope,
        id: 'sec1',
        heading: '方法',
        kind: 'method',
        source_block_ids: [],
        anchor_ids: [FIXTURE_ANCHOR_ID],
        summary: { text: '方法概述', spans: [] },
        key_points: [],
      },
    ],
    map: { ...scope, id: 'map1', items: [] },
    method_steps: [],
  };
  return {
    scope,
    structure,
    claims: [fixtureClaim()],
    statements: [makeStatement('00000000-0000-4000-8000-0000000000st1', '该方法的准确率达到 0.91。', 'verified_fact')],
    graph: { ...scope, id: 'g1', nodes: [], edges: [] },
    presentation: { ...scope, id: 'pres1', scenes: [], warnings: [] },
    evaluation: {
      ...scope,
      id: 'eval1',
      version: '1.0',
      overall_score: null,
      metrics: [],
      golden_id: null,
      computed_at: iso(1),
      warnings: [],
    },
    capabilities: [{ name: 'claims', state: 'ready', reason: null }],
  };
}

export function fixtureQAEvents(scope: Scope, question: string): QAStreamEvent[] {
  const evidence = fixtureEvidence(scope);
  const statement = makeStatement('00000000-0000-4000-8000-0000000000st1', '该方法的准确率达到 0.91。', 'verified_fact');
  const requestId = '00000000-0000-4000-8000-0000000000q1';
  return [
    { event_id: 1, request_id: requestId, type: 'meta', data: { scope, answer_id: '00000000-0000-4000-8000-0000000000a1', deadline_at: new Date(Date.now() + 30000).toISOString() } },
    { event_id: 2, request_id: requestId, type: 'status', data: { stage: 'retrieving', message: '检索原文中' } },
    { event_id: 3, request_id: requestId, type: 'status', data: { stage: 'verifying', message: '逐句校验中' } },
    { event_id: 4, request_id: requestId, type: 'citation', data: { evidence } },
    { event_id: 5, request_id: requestId, type: 'sentence', data: { statement } },
    {
      event_id: 6,
      request_id: requestId,
      type: 'final',
      data: {
        legacy: { answer: '该方法的准确率达到 0.91。', grounded: true, confidence: 'High', evidence: [], note: '' },
        answer: {
          ...scope,
          id: '00000000-0000-4000-8000-0000000000a1',
          question,
          text: { text: '该方法的准确率达到 0.91。', spans: [] },
          statements: [statement],
          evidence: [evidence],
          grounded: true,
          confidence: 'High',
          note: '',
          mode: 'generated',
          model_snapshot_id: null,
          usage: { input_tokens: 100, output_tokens: 20, elapsed_ms: 3000 },
          warnings: [],
        },
      },
    },
  ];
}

export function fixtureJobEvents(jobId: number): JobEvent[] {
  const data = (stage: JobRecord['stage'], progress: number, message: string) => ({
    stage,
    progress,
    message,
    tool: null,
    artifact_ids: [],
    elapsed_ms: null,
    usage: null,
    error: null,
  });
  return [
    { event_id: 1, job_id: jobId, occurred_at: iso(1), type: 'stage_started', data: data('acquire', 0.05, '获取源 PDF') },
    { event_id: 2, job_id: jobId, occurred_at: iso(1), type: 'stage_finished', data: data('acquire', 0.1, '源 PDF 已保存') },
    { event_id: 3, job_id: jobId, occurred_at: iso(1), type: 'stage_started', data: data('parse', 0.2, 'MinerU 解析中') },
    { event_id: 4, job_id: jobId, occurred_at: iso(1), type: 'stage_finished', data: data('parse', 0.4, '解析完成') },
    { event_id: 5, job_id: jobId, occurred_at: iso(1), type: 'stage_started', data: data('claims', 0.6, '提取断言') },
    { event_id: 6, job_id: jobId, occurred_at: iso(1), type: 'stage_finished', data: data('claims', 0.8, '断言已生成') },
    { event_id: 7, job_id: jobId, occurred_at: iso(1), type: 'completed', data: data('publish', 1.0, '已完成') },
  ];
}

export function fixtureEvidenceExport(scope: Scope = makeScope()): EvidenceExport {
  return {
    schema_version: 'rl.contract/1',
    scope,
    source_sha256: FIXTURE_HASH,
    claims: [fixtureClaim()],
    statements: [makeStatement('00000000-0000-4000-8000-0000000000st1', '该方法的准确率达到 0.91。', 'verified_fact')],
    evidence: [fixtureEvidence(scope)],
    media: [fixtureMedia()],
    validations: [],
    generated_at: iso(0),
  };
}

export function fixturePage(index = 0): Page {
  return makePage(index, index === 0 ? '3' : null);
}

export function fixturePageContent(index = 0): PageContent {
  return {
    page: makePage(index, index === 0 ? '3' : null),
    blocks: [makeBlock('00000000-0000-4000-8000-0000000000bl1', 'paragraph', '示例正文块。', index)],
    anchors: [fixtureAnchor()],
  };
}

export function fixturePages(): PageResult<PageSummary> {
  const pages = [0, 1, 2].map((i) => {
    const p = makePage(i, i === 0 ? '3' : null);
    const { text: _text, ...summary } = p;
    return summary;
  });
  return { items: pages, next_cursor: null, total: pages.length };
}

export function makeDomainError(message: string): DomainError {
  return {
    code: 'NOT_FOUND',
    message,
    retryable: false,
    request_id: '00000000-0000-4000-8000-0000000000req',
    field_errors: [],
    retry_after_ms: null,
  };
}
