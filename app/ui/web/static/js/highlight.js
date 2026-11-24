/* 荧光笔：横向的色带。

   视觉上用 CSS 的 mix-blend-mode: multiply 模拟「颜色叠加」——压在白纸上显色，
   压在纯黑上几乎看不出。PDF 那边对应的是 /ExtGState <</BM /Multiply>>，
   两边像素一致。

   色带只能挪位置、换颜色，没有手柄。 */

import { call } from './bridge.js';
import { apply, pageEl } from './render.js';
import { pxPerPt, state } from './state.js';

let bar = null;

function hexOf(key) {
  const list = ((state.data && state.data.palette) || {}).highlight || [];
  const hit = list.find((item) => item.key === key);
  return hit ? hit.hex : '#FFF066';
}

export function bandNode(obj, k) {
  const node = document.createElement('div');
  node.className = 'obj hl-band';
  node.dataset.id = obj.id;
  node.dataset.kind = 'highlight';
  node.style.left = `${obj.x * k}px`;
  node.style.top = `${obj.y * k}px`;
  node.style.width = `${obj.w * k}px`;
  node.style.height = `${obj.h * k}px`;
  node.style.background = obj.hex || hexOf(obj.color);
  if ((state.data.selection || []).includes(obj.id)) node.classList.add('selected');
  return node;
}

export async function createBand(pageIndex, x, y, width) {
  const snapshot = await call('create_highlight', pageIndex, x, y, width);
  if (snapshot) apply(snapshot);
}

/* ---------- 选中后的调色条 ---------- */

function hideBar() {
  if (bar) {
    bar.remove();
    bar = null;
  }
}

function selectedBand() {
  if (!state.data) return null;
  const ids = state.data.selection || [];
  if (ids.length !== 1) return null;
  const obj = state.data.objects.find((item) => item.id === ids[0]);
  return obj && obj.kind === 'highlight' ? obj : null;
}

function placeBar(obj) {
  if (!bar) return;
  const k = pxPerPt();
  const height = bar.offsetHeight || 32;
  const top = obj.y * k - height - 6;
  bar.style.left = `${Math.max(2, obj.x * k)}px`;
  bar.style.top = `${top >= 2 ? top : obj.y * k + obj.h * k + 6}px`;
}

async function recolor(obj, key) {
  const snapshot = await call('update_highlight', obj.id, key);
  if (snapshot) apply(snapshot);
}

export function syncBandBar() {
  const obj = selectedBand();
  if (!obj) {
    hideBar();
    return;
  }
  const page = pageEl(obj.page);
  if (!page) {
    hideBar();
    return;
  }
  if (bar && bar.dataset.id === obj.id) {
    placeBar(obj);
    return;
  }
  hideBar();
  const el = document.createElement('div');
  el.className = 'float-bar';
  el.dataset.id = obj.id;
  for (const color of ((state.data && state.data.palette) || {}).highlight || []) {
    const swatch = document.createElement('button');
    swatch.type = 'button';
    swatch.className = 'swatch' + (color.key === obj.color ? ' active' : '');
    swatch.style.background = color.hex;
    swatch.dataset.color = color.key;
    swatch.title = color.key;
    swatch.addEventListener('click', () => recolor(obj, color.key));
    el.appendChild(swatch);
  }
  page.appendChild(el);
  bar = el;
  placeBar(obj);
}

export function bindHighlight() {
  document.addEventListener('selection:changed', syncBandBar);
  document.addEventListener('layout:done', () => {
    const obj = selectedBand();
    if (obj) placeBar(obj);
  });
  document.addEventListener('pages:rebuilt', hideBar);
}
