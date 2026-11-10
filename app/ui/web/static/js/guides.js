/* 参考线：按页边距画四条线。
   用独立的 canvas，避免和选框、分割线抢同一块画布。 */

import { pageEl } from './render.js';
import { pxPerPt, state } from './state.js';

const MM_TO_PT = 72 / 25.4;

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

    const left = (reference.left_mm || 0) * MM_TO_PT;
    const top = (reference.top_mm || 0) * MM_TO_PT;
    const right = info.w - (reference.right_mm || 0) * MM_TO_PT;
    const bottom = info.h - (reference.bottom_mm || 0) * MM_TO_PT;
    if (right <= left || bottom <= top) continue;

    ctx.setTransform(dpr * k, 0, 0, dpr * k, 0, 0);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1 / k;
    ctx.beginPath();
    ctx.moveTo(left, 0);
    ctx.lineTo(left, info.h);
    ctx.moveTo(right, 0);
    ctx.lineTo(right, info.h);
    ctx.moveTo(0, top);
    ctx.lineTo(info.w, top);
    ctx.moveTo(0, bottom);
    ctx.lineTo(info.w, bottom);
    ctx.stroke();
  }
}

export function bindGuides() {
  document.addEventListener('layout:done', drawGuides);
}
