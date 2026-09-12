// 媒体查看器的**纯逻辑**（REFACTOR_PLAN M4）。
//
// 用户实测："很多图方向反了，要求点击图片展示时加旋转按钮。"
// 约束（任务书 P6）：旋转只存在于**视图层**（CSS transform），不改资产字节、不上传、
// 离开组件即复位 —— 这样既不污染数据，也不影响"原件"的可信度。
//
// 这里放不需要 DOM 的部分（角度归约、缩放边界、transform 串），便于零依赖单测。

export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 4;

/** 角度归约到 {0,90,180,270}（支持负数，如向左转）。 */
export function nextRotation(current: number, delta = 90): number {
  const step = ((Math.round(current / 90) * 90 + delta) % 360 + 360) % 360;
  return step;
}

/** 缩放夹到 [0.25, 4]；非法输入回落到 1。 */
export function clampZoom(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value));
}

/** 旋转 90/270 度时容器宽高要对调，否则图会被裁掉。 */
export function isQuarterTurn(rotation: number): boolean {
  return Math.abs(Math.round(rotation / 90)) % 2 === 1;
}

export function transformStyle(rotation: number, zoom: number): { transform: string } {
  return { transform: `rotate(${nextRotation(rotation, 0)}deg) scale(${clampZoom(zoom)})` };
}

/** 需要放大/旋转到某个尺寸时，容器的最大高度要跟着走（避免撑破弹窗）。 */
export function frameMaxHeight(basePx: number, rotation: number, zoom: number): number {
  const scaled = basePx * clampZoom(zoom);
  return isQuarterTurn(rotation) ? scaled * 1.1 : scaled;
}
