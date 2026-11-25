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
  return linesOf((state.data && state.data.align) || {}, info);
}

function linesOf(raw, info) {
  const vertical = [];
  const horizontal = [];
  for (const mm of values(raw.left_mm)) vertical.push(mm * MM_TO_PT);
  for (const mm of values(raw.right_mm)) vertical.push(info.w - mm * MM_TO_PT);
  for (const mm of values(raw.top_mm)) horizontal.push(mm * MM_TO_PT);
  for (const mm of values(raw.bottom_mm)) horizontal.push(info.h - mm * MM_TO_PT);
  return {
    vertical: vertical.filter((x) => x > 0 && x < info.w),
    horizontal: horizontal.filter((y) => y > 0 && y < info.h),
  };
}

/** 缩放时两套线都认：常驻参考线和移动用的对齐线。 */
function resizeLines(info) {
  const align = alignLines(info);
  const reference = linesOf((state.data && state.data.reference) || {}, info);
  const merge = (a, b) => [
    ...new Set([...a, ...b].map((value) => Math.round(value * 1000) / 1000)),
  ];
  return {
    vertical: merge(align.vertical, reference.vertical),
    horizontal: merge(align.horizontal, reference.horizontal),
  };
}

function nearest(value, positions, threshold) {
  let best = null;
  for (const line of positions) {
    const distance = Math.abs(line - value);
    if (distance <= threshold && (!best || distance < best.distance)) {
      best = { distance, line };
    }
  }
  return best;
}

/**
 * 缩放吸附：只有正在移动的边参与。
 *
 * 角手柄会同时移动两条边；等比缩放时只吸更近的那一条，另一条按原比例
 * 跟随，避免为了贴线把长宽比拉坏。边手柄只动一条边，直接吸。
 *
 * 返回吸附后的矩形，以及吸中的两条线（没吸中为 null）。矩形不合格
 * （小于最小尺寸或出页）时退回原样，调用方据此不画绿线。
 */
export function snapResize(rect, corner, info, options = {}) {
  const { keepRatio = false, allowOutside = false, minW = 1, minH = 1 } = options;
  const lines = resizeLines(info);
  const threshold = SNAP_PX / pxPerPt();

  const movesLeft = corner === 'w' || corner === 'tl' || corner === 'bl';
  const movesRight = corner === 'e' || corner === 'tr' || corner === 'br';
  const movesTop = corner === 'n' || corner === 'tl' || corner === 'tr';
  const movesBottom = corner === 's' || corner === 'bl' || corner === 'br';

  const vertical = movesLeft
    ? nearest(rect.x, lines.vertical, threshold)
    : movesRight
      ? nearest(rect.x + rect.w, lines.vertical, threshold)
      : null;
  const horizontal = movesTop
    ? nearest(rect.y, lines.horizontal, threshold)
    : movesBottom
      ? nearest(rect.y + rect.h, lines.horizontal, threshold)
      : null;
  if (!vertical && !horizontal) {
    return { rect, vertical: null, horizontal: null };
  }

  let x = rect.x;
  let y = rect.y;
  let w = rect.w;
  let h = rect.h;
  let verticalMark = null;
  let horizontalMark = null;

  const applyVertical = (line) => {
    if (movesLeft) {
      const right = rect.x + rect.w;
      x = line;
      w = right - line;
    } else {
      w = line - rect.x;
    }
    verticalMark = line;
  };
  const applyHorizontal = (line) => {
    if (movesTop) {
      const bottom = rect.y + rect.h;
      y = line;
      h = bottom - line;
    } else {
      h = line - rect.y;
    }
    horizontalMark = line;
  };

  if (keepRatio) {
    const useVertical = vertical && (!horizontal || vertical.distance <= horizontal.distance);
    if (useVertical) {
      applyVertical(vertical.line);
      const ratio = rect.h > 0 ? rect.w / rect.h : 1;
      h = w / ratio;
      y = movesTop ? rect.y + rect.h - h : rect.y;
    } else {
      applyHorizontal(horizontal.line);
      const ratio = rect.w > 0 ? rect.w / rect.h : 1;
      w = h * ratio;
      x = movesLeft ? rect.x + rect.w - w : rect.x;
    }
  } else {
    if (vertical) applyVertical(vertical.line);
    if (horizontal) applyHorizontal(horizontal.line);
  }

  if (w < minW || h < minH) {
    return { rect, vertical: null, horizontal: null };
  }
  // 只吸一条边时，对面那条边本来就在页内，吸到页内的线上不会出页；
  // 等比缩放会按比例把另一条边也带大，这才需要再检查一次页面边界。
  if (!allowOutside && keepRatio && (x < 0 || y < 0 || x + w > info.w || y + h > info.h)) {
    return { rect, vertical: null, horizontal: null };
  }
  return { rect: { x, y, w, h }, vertical: verticalMark, horizontal: horizontalMark };
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
