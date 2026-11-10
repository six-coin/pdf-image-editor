/* 画布：页面可见性、背景图加载、缩放与滚动。
   背景位图按目标 DPI 由后端渲染，只在"进入视野"或"DPI 档位变化"时重新拉取；
   中间的连续缩放只改 CSS 尺寸，不重传图片。 */

import { call } from './bridge.js';
import {
  BASE_PX_PER_PT,
  clampZoom,
  dpiForZoom,
  mergeObjects,
  state,
} from './state.js';
import { layoutPages, pageEl, renderObjects, renderZoom } from './render.js';

const visible = new Set();
const inflight = new Map();
let observer = null;
let zoomTimer = 0;

function viewport() {
  return document.getElementById('viewport');
}

/* ---------- 可见性与加载 ---------- */

export function observePages() {
  if (observer) observer.disconnect();
  visible.clear();
  observer = new IntersectionObserver(onIntersect, {
    root: viewport(),
    rootMargin: '120% 0px',
  });
  document.querySelectorAll('.page').forEach((el) => observer.observe(el));
}

function onIntersect(entries) {
  for (const entry of entries) {
    const index = Number(entry.target.dataset.page);
    if (entry.isIntersecting) {
      visible.add(index);
      loadPage(index);
    } else {
      visible.delete(index);
    }
  }
}

async function loadPage(index) {
  if (!state.data) return;
  const el = pageEl(index);
  if (!el) return;
  const dpi = state.view.dpi;
  if (el.dataset.dpi === String(dpi) && el.dataset.loaded === '1') return;
  if (inflight.get(index) === dpi) return;

  inflight.set(index, dpi);
  const data = await call('load_page', index, dpi);
  inflight.delete(index);
  if (!data || !data.ok) return;
  if (state.view.dpi !== dpi) return; // 缩放档位已变，丢弃过期回包

  el.dataset.dpi = String(dpi);
  el.dataset.loaded = '1';

  const img = el.querySelector('.page-bg');
  if (img) img.src = data.url;
  el.classList.remove('loading');

  if (data.objects && data.objects.length) {
    mergeObjects(data.objects);
    renderObjects(index);
  }
}

function reloadVisible() {
  for (const index of visible) loadPage(index);
}

/* ---------- 缩放 ---------- */

export function setZoom(zoom, anchor = null, force = false) {
  const next = clampZoom(zoom);
  const dpiChanged = dpiForZoom(next) !== state.view.dpi;
  if (next === state.view.zoom && !force && !dpiChanged) return;

  const box = viewport();
  const rect = box.getBoundingClientRect();
  const ax = anchor ? anchor.x : rect.width / 2;
  const ay = anchor ? anchor.y : rect.height / 2;
  const before = state.view.zoom * BASE_PX_PER_PT;
  const sceneX = (box.scrollLeft + ax) / before;
  const sceneY = (box.scrollTop + ay) / before;

  state.view.zoom = next;
  state.view.dpi = dpiForZoom(next);
  state.view.fitWidth = false;

  layoutPages();
  renderZoom();

  const after = next * BASE_PX_PER_PT;
  box.scrollLeft = sceneX * after - ax;
  box.scrollTop = sceneY * after - ay;

  if (dpiChanged) reloadVisible();
}

export function zoomBy(factor, anchor = null) {
  setZoom(state.view.zoom * factor, anchor);
}

export function fitWidth() {
  const pages = state.data && state.data.pages;
  if (!pages || !pages.length) return;
  const box = viewport();
  const widest = Math.max(...pages.map((p) => p.w));
  const available = Math.max(80, box.clientWidth - 48);
  const zoom = clampZoom(available / (widest * BASE_PX_PER_PT));
  state.view.fitWidth = true;
  setZoom(zoom, null, true);
  box.scrollTop = 0;
}

export function resetZoom() {
  state.view.fitWidth = false;
  setZoom(1, null, true);
}

/** 视口中心落在哪一页。粘贴图片时用它决定落到哪页。 */
export function currentPage() {
  if (!state.data || !state.data.pages.length) return 0;
  const box = viewport();
  const rect = box.getBoundingClientRect();
  const centre = rect.top + rect.height / 2;

  let best = 0;
  let bestDistance = Infinity;
  for (const info of state.data.pages) {
    const el = pageEl(info.index);
    if (!el) continue;
    const bounds = el.getBoundingClientRect();
    if (centre >= bounds.top && centre <= bounds.bottom) return info.index;
    const distance = Math.min(Math.abs(centre - bounds.top), Math.abs(centre - bounds.bottom));
    if (distance < bestDistance) {
      bestDistance = distance;
      best = info.index;
    }
  }
  return best;
}

/* ---------- 事件绑定 ---------- */

export function bindCanvas() {
  const box = viewport();

  box.addEventListener(
    'wheel',
    (event) => {
      if (!event.ctrlKey) return; // 普通滚轮交给浏览器，deltaMode 由它处理
      event.preventDefault();
      const rect = box.getBoundingClientRect();
      const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
      zoomBy(factor, { x: event.clientX - rect.left, y: event.clientY - rect.top });
    },
    { passive: false }
  );

  window.addEventListener('resize', () => {
    const dpr = window.devicePixelRatio || 1;
    if (dpr !== state.view.dpr) {
      state.view.dpr = dpr;
      state.view.dpi = dpiForZoom();
      layoutPages();
      reloadVisible();
      return;
    }
    if (state.view.fitWidth) {
      clearTimeout(zoomTimer);
      zoomTimer = window.setTimeout(fitWidth, 120);
    }
  });
}
