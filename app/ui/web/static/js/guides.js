/* 参考线：每一边都可以有多条，位置是从那条边往里的毫米数。
   用独立的 canvas，避免和选框、分割线抢同一块画布。 */

import { pageEl } from './render.js';
import { pxPerPt, state } from './state.js';

const MM_TO_PT = 72 / 25.4;

/** 一边上的参考线位置。老配置里是标量，这里一并兜住。 */
function values(raw) {
  if (Array.isArray(raw)) return raw.filter((value) => Number.isFinite(value));
  return Number.isFinite(raw) ? [raw] : [];
}

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
}
