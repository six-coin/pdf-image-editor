/* 前端状态。
   业务数据只信后端快照；这里只放纯视图状态（缩放、已加载的页、主题）。 */

export const BASE_PX_PER_PT = 96 / 72;
export const MIN_ZOOM = 0.1;
export const MAX_ZOOM = 8;

export const state = {
  strings: {},
  data: null,
  generation: -1,
  view: {
    zoom: 1,
    dpr: window.devicePixelRatio || 1,
    dpi: 96,
    theme: 'light',
    // 手势进行中：任何快照都不能落地，否则正在拖的元素会被重建、位置被拉回。
    gesture: false,
    // 保存进行中：画布与快捷键一律不响应，避免改动落到正在重建的文档上。
    busy: false,
  },
  // 最近一次落地快照的版本号；更小的 rev 一律丢弃。
  rev: -1,
  // 手势期间丢掉了快照，结束时需要补一次。
  stale: false,
};

export function pxPerPt() {
  return state.view.zoom * BASE_PX_PER_PT;
}

/** 背景图该用多少 DPI：让图片像素正好等于屏幕设备像素，再多就浪费带宽。 */
export function dpiForZoom(zoom = state.view.zoom) {
  const raw = 96 * zoom * state.view.dpr;
  return Math.min(300, Math.max(72, Math.round(raw / 24) * 24));
}

export function clampZoom(zoom) {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

export function objectsOf(index) {
  if (!state.data) return [];
  // 按 z 升序：DOM 顺序就是视觉层级，稳定排序保证同 z 的相对次序不变。
  return state.data.objects.filter((o) => o.page === index).sort((a, b) => a.z - b.z);
}
