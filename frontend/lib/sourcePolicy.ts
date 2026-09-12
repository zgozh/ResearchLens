// 统一来源策略（§3.4 / §5.3 / §5.13）。
// 纯函数 resolveMediaPolicy(media, assets) -> MediaViewPolicy；
// 展示层级：可验证 PDF 区域裁剪 → 同源 MinerU 裁剪 → 整页预览（标"整页"）→ 明示不可用。
// 真实 source 缺原图绝不允许回退 synthetic；示意 SVG 仅来自受控 seed。

import type {
  Asset,
  AssetId,
  Id,
  Media,
  MediaViewMode,
  MediaViewPolicy,
  Representation,
  Verification,
  Warning,
} from './contracts';

/** default_mode 展示标签映射（用于徽标 / 工具提示）。 */
export const MEDIA_MODE_LABELS: Record<MediaViewMode, string> = {
  original: '原件',
  extracted: '再排版 / 提取',
  synthetic: '示意',
  unavailable: '不可用',
};

/** provenance.representation 的展示标签。 */
export const REPRESENTATION_LABELS: Record<Representation, string> = {
  pdf_crop: 'PDF 区域裁剪',
  mineru_crop: 'MinerU 裁剪',
  extracted: '解析提取',
  synthetic: '受控示意',
};

/** provenance.verification 的展示标签。 */
export const VERIFICATION_LABELS: Record<Verification, string> = {
  source_bound: '同源可追溯',
  unverified: '未验证来源',
  synthetic: '示意资产',
};

/** HTML/KaTeX 提取视图的明确标签——不得标"原版"。 */
export const EXTRACTED_LABEL = '再排版 / 提取';

function warn(code: string, message: string): Warning {
  return { code, message, stage: 'media' };
}

/**
 * 计算某个 Media 的统一来源策略。
 * - original：存在 source_bound 的裁剪资产（pdf_crop 或可验证 mineru_crop）。
 * - 真实 source 缺原图：退回整页预览（fallback_page_ids，标"整页"），default_mode 仍为 original。
 * - extracted：只有 HTML/KaTeX 提取（标"再排版/提取"）。
 * - synthetic：provenance.verification=synthetic 的受控示意资产。
 * - unavailable：无任何可展示资产。
 */
export function resolveMediaPolicy(media: Media, assets: Asset[]): MediaViewPolicy {
  const byId = new Map<string, Asset>();
  for (const a of assets) byId.set(a.id, a);

  const originalIds = (media.original_asset_ids || []).filter((id) => byId.has(id));
  const provenance = media.provenance;
  const verification: Verification = provenance?.verification ?? 'unverified';
  const representation: Representation = provenance?.representation ?? 'extracted';
  const isSynthetic = verification === 'synthetic' || representation === 'synthetic';
  const hasSource = provenance?.source_document_id != null;

  const warnings: Warning[] = [];

  // 1) source_bound 裁剪 → 原件
  if (verification === 'source_bound' && originalIds.length > 0) {
    return {
      default_mode: 'original',
      original_asset_ids: originalIds,
      fallback_page_ids: [],
      label: MEDIA_MODE_LABELS.original,
      warnings,
    };
  }

  // 2) 受控示意（仅 seed 的 synthetic 资产）
  if (isSynthetic) {
    if (hasSource) {
      // 真实 source 声称 synthetic：非法，明示不可用，绝不回退示意
      warnings.push(warn('synthetic_on_real_source', '真实来源媒体被标记为示意资产，已拒绝展示。'));
      return {
        default_mode: 'unavailable',
        original_asset_ids: [],
        fallback_page_ids: [],
        label: MEDIA_MODE_LABELS.unavailable,
        warnings,
      };
    }
    return {
      default_mode: 'synthetic',
      original_asset_ids: originalIds,
      fallback_page_ids: [],
      label: MEDIA_MODE_LABELS.synthetic,
      warnings,
    };
  }

  // 3) 真实 source 有未验证的 mineru_crop / 无裁剪 → 整页预览兜底（标"整页"）
  if (hasSource) {
    const fallbackPages = (media.anchor_ids || [])
      .filter((id): id is string => typeof id === 'string');
    if (originalIds.length > 0) {
      // mineru_crop 未验证：可按"解析器提取图"查看，但不能标精确原件
      warnings.push(warn('unverified_crop', '裁剪资产未能验证与源 PDF 区域对齐，按提取图展示。'));
      return {
        default_mode: 'original',
        original_asset_ids: originalIds,
        fallback_page_ids: fallbackPages as Id[],
        label: '整页预览', // 未验证裁剪以整页兜底，明确"整页"
        warnings,
      };
    }
    if (fallbackPages.length > 0) {
      warnings.push(warn('no_crop_fallback_page', '缺少区域裁剪，退回整页预览。'));
      return {
        default_mode: 'original',
        original_asset_ids: [],
        fallback_page_ids: fallbackPages as Id[],
        label: '整页预览',
        warnings,
      };
    }
    // 有源但既无裁剪也无页 → 先看**有没有提取表示**（表格 HTML / 公式 LaTeX）：
    // 有就给"再排版 / 提取"，而不是"不可用"。
    // 为什么（实测）：表格与公式媒体本来就没有原图资产，旧逻辑直接判 unavailable，
    // 用户在图表节点上看到的就是"不可用的标签 + 未找到任何可展示原件资产"。
    if (media.extracted && (media.extracted.table_html || media.extracted.latex)) {
      warnings.push(warn('no_original_asset', '没有原件裁剪，改为展示解析提取的再排版表示。'));
      return {
        default_mode: 'extracted',
        original_asset_ids: [],
        fallback_page_ids: [],
        label: EXTRACTED_LABEL,
        warnings,
      };
    }
    warnings.push(warn('no_original_asset', '未找到任何可展示原件资产。'));
    return {
      default_mode: 'unavailable',
      original_asset_ids: [],
      fallback_page_ids: [],
      label: MEDIA_MODE_LABELS.unavailable,
      warnings,
    };
  }

  // 4) 无源（synthetic 之外的提取媒体，理论上不常见）→ 提取
  if (media.extracted && (media.extracted.table_html || media.extracted.latex)) {
    return {
      default_mode: 'extracted',
      original_asset_ids: [],
      fallback_page_ids: [],
      label: EXTRACTED_LABEL,
      warnings,
    };
  }

  return {
    default_mode: 'unavailable',
    original_asset_ids: [],
    fallback_page_ids: [],
    label: MEDIA_MODE_LABELS.unavailable,
    warnings: [warn('no_media', '媒体无原件也无提取表示。')],
  };
}

/** 从 assets 列表中查找给定 id 的资产（供 SourceMedia 定位 URL/MIME）。 */
export function findAsset(assets: Asset[], id: AssetId): Asset | undefined {
  return assets.find((a) => a.id === id);
}

/** 判断 policy 是否表示"有真实原件可打开"。 */
export function hasOriginal(policy: MediaViewPolicy): boolean {
  return policy.default_mode === 'original' && policy.original_asset_ids.length > 0;
}
