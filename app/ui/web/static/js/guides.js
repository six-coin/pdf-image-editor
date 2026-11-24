/* 参考线与对齐线。
   参考线：每一边都可以有多条，位置是从那条边往里的毫米数，常驻显示。
   对齐线：同样的存法，但平时不画；移动元素时用来吸附，吸上了才画一条绿色提示线。
   两者都用独立的 canvas / 图层，避免和选框、分割线抢同一块画布。 */

import { pageEl } from './render.js';
import { pxPerPt, state } from './state.js';

const MM_TO_PT = 72 / 25.4;
// 吸附半径（屏幕像素）。换算成 pt 再比较，缩放后手感一致。
const SNAP_PX = 6;

/** 一边上的线位置。老配置里是标量，这里一并兜住。 */
function values(raw) {
  if (Array.isArray(raw)) return raw.filter((value) => Number.isFinite(value));
  return Number.isFinite(raw) ? [raw] : [];
}

/** 某页上所有对齐线的位置（pt），分成竖直与水平两组。 */
export function alignLines(info) {
  const align = (state.data && state.data.align) || {};
  const vertical = [];
  const horizontal = [];
  for (const mm of values(align.left_mm)) vertical.push(mm * MM_TO_PT);
  for (const mm of values(align.right_mm)) vertical.push(info.w - mm * MM_TO_PT);
  for (const mm of values(align.top_mm)) horizontal.push(mm * MM_TO_PT);
  for (const mm of values(align.bottom_mm)) horizontal.push(info.h - mm * MM_TO_PT);
  return {
    vertical: vertical.filter((x) => x > 0 && x < info.w),
    horizontal: horizontal.filter((y) => y > 0 && y < info.h),
  };
}

/**
 * 算一次吸附。
 *
 * ``bounds`` 是元素（或整组）在页面坐标系里的矩形，单位 pt。元素的左边、
 * 竖直中线、右边都参与竖直吸附；上边、水平中线、下边参与水平吸附。
 * 返回需要补的位移（pt）和吸中的那条线（没吸中为 null）。
 */
export function snapOffset(bounds, info) {
  const lines = alignLines(info);
  const threshold = SNAP_PX / pxPerPt();

  const pick = (targets, positions) => {
    let best = null;
    for (const line of positions) {
      for (const value of targets) {
        const distance = Math.abs(line - value);
        if (distance <= threshold && (!best || distance < best.distance)) {
          best = { distance, delta: line - value, line };
        }
      }
    }
    return best;
  };

  const vertical = pick(
    [bounds.x, bounds.x + bounds.w / 2, bounds.x + bounds.w],
    lines.vertical
  );
  const horizontal = pick(
    [bounds.y, bounds.y + bounds.h / 2, bounds.y + bounds.h],
    lines.horizontal
  );

  return {
    dx: vertical ? vertical.delta : 0,
    dy: horizontal ? horizontal.delta : 0,
    vertical: vertical ? vertical.line : null,
    horizontal: horizontal ? horizontal.line : null,
  };
}

/* ---------- 吸附时的绿色提示线 ---------- */

let layer = null;
let layerPage = null;

function makeLayer(page) {
  const wrap = document.createElement('div');
  wrap.className = 'snap-guides';
  const vertical = document.createElement('i');
  vertical.className = 'snap-line v';
  const horizontal = document.createElement('i');
  horizontal.className = 'snap-line h';
  wrap.append(vertical, horizontal);
  page.appendChild(wrap);
  return { wrap, vertical, horizontal };
}

/** 在某一页上显示吸附线。``marks`` 里的 null 表示那个方向没吸中。 */
export function showSnap(pageIndex, marks) {
  const page = pageEl(pageIndex);
  if (!page) {
    hideSnap();
    return;
  }
  if (!layer || layerPage !== pageIndex || !layer.wrap.isConnected) {
    hideSnap();
    layer = makeLayer(page);
    layerPage = pageIndex;
  }
  const k = pxPerPt();
  if (marks.vertical === null) {
    layer.vertical.style.display = 'none';
  } else {
    layer.vertical.style.display = '';
    layer.vertical.style.left = `${marks.vertical * k}px`;
  }
  if (marks.horizontal === null) {
    layer.horizontal.style.display = 'none';
  } else {
    layer.horizontal.style.display = '';
    layer.horizontal.style.top = `${marks.horizontal * k}px`;
  }
}

export function hideSnap() {
  if (layer) {
    layer.wrap.remove();
    layer = null;
    layerPage = null;
  }
}

/* ---------- 参考线 ---------- */

export function drawGuides() {
  if (!state.data) return;
  const visible = Boolean(state.data.show_guides);
  const reference = state.data.reference || {};
  const k = pxPerPt();
  const dpr = state.view.dpr;
  const styles = getComputedStyle(document.documentElement);
  const color = styles.getPropertyValue('--guide').trim();

  for (const info of state.data.pages) {
    const el = pageEl(info.index);
    if (!el) continue;
    const canvas = el.querySelector('.guides');
    if (!canvas) continue;

    const width = Math.max(1, Math.round(info.w * k * dpr));
    const height = Math.max(1, Math.round(info.h * k * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    canvas.style.width = '100%';
    canvas.style.height = '100%';

    const ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!visible) continue;

    ctx.setTransform(dpr * k, 0, 0, dpr * k, 0, 0);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1 / k;
    ctx.beginPath();
    for (const mm of values(reference.left_mm)) {
      const x = mm * MM_TO_PT;
      if (x <= 0 || x >= info.w) continue;
      ctx.moveTo(x, 0);
      ctx.lineTo(x, info.h);
    }
    for (const mm of values(reference.right_mm)) {
      const x = info.w - mm * MM_TO_PT;
      if (x <= 0 || x >= info.w) continue;
      ctx.moveTo(x, 0);
      ctx.lineTo(x, info.h);
    }
    for (const mm of values(reference.top_mm)) {
      const y = mm * MM_TO_PT;
      if (y <= 0 || y >= info.h) continue;
      ctx.moveTo(0, y);
      ctx.lineTo(info.w, y);
    }
    for (const mm of values(reference.bottom_mm)) {
      const y = info.h - mm * MM_TO_PT;
      if (y <= 0 || y >= info.h) continue;
      ctx.moveTo(0, y);
      ctx.lineTo(info.w, y);
    }
    ctx.stroke();
  }
}

export function bindGuides() {
  document.addEventListener('layout:done', drawGuides);
  document.addEventListener('pages:rebuilt', hideSnap);
}
