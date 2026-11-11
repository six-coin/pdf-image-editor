/* 画布：页面可见性、背景图加载、缩放与滚动。
   背景位图按目标 DPI 由后端渲染，只在"进入视野"或"DPI 档位变化"时重新拉取；
   中间的连续缩放只改 CSS 尺寸，不重传图片。 */

import { call } from './bridge.js';
import { BASE_PX_PER_PT, clampZoom, dpiForZoom, state } from './state.js';
import { layoutPages, pageEl, renderPageIndicator, renderZoom } from './render.js';
import { scheduleRefresh } from './sync.js';

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

  // 页面装载可能带来新对象，交给统一通道去拉快照，前端不自己拼模型。
  scheduleRefresh();
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
  // 左右各留 48px 的留白（.pages 的 padding），两边必须一样宽。
  const available = Math.max(80, box.clientWidth - 96);
  const zoom = clampZoom(available / (widest * BASE_PX_PER_PT));
  state.view.fitWidth = true;
  setZoom(zoom, null, true);
  box.scrollTop = 0;
}

export function resetZoom() {
  state.view.fitWidth = false;
  setZoom(1, null, true);
}

/** 把某一页滚到视口顶部。 */
export function scrollToPage(index) {
  const box = viewport();
  const el = pageEl(index);
  if (!box || !el) return;
  box.scrollTo({ top: Math.max(0, el.offsetTop - 24), behavior: 'smooth' });
}

/** 属性栏底部那个"跳转到第 N 页"。 */
export function pageJump() {
  const input = document.getElementById('pageJump');
  if (!input || !state.data) return;
  const total = state.data.pages.length;
  if (!total) return;
  const raw = Number.parseInt(input.value, 10);
  if (!Number.isFinite(raw)) {
    input.value = '';
    return;
  }
  scrollToPage(Math.min(total, Math.max(1, raw)) - 1);
  input.value = '';
  input.blur();
}

/** 缩放百分比输入框：接受 "150"、"150%" 两种写法。 */
function commitZoomInput() {
  const input = document.getElementById('zoomValue');
  if (!input) return;
  const percent = Number.parseFloat(String(input.value).replace(/[^\d.]/g, ''));
  if (!Number.isFinite(percent) || percent <= 0) {
    renderZoom();
    return;
  }
  setZoom(percent / 100, null, true);
  renderZoom();
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

  let scrollFrame = 0;
  box.addEventListener('scroll', () => {
    if (scrollFrame) return;
    scrollFrame = window.requestAnimationFrame(() => {
      scrollFrame = 0;
      renderPageIndicator(currentPage());
    });
  });

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

  // 缩放百分比可以直接输入
  const zoomInput = document.getElementById('zoomValue');
  if (zoomInput) {
    zoomInput.addEventListener('focus', () => zoomInput.select());
    zoomInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        commitZoomInput();
        zoomInput.blur();
      } else if (event.key === 'Escape') {
        event.preventDefault();
        zoomInput.value = `${Math.round(state.view.zoom * 100)}%`;
        zoomInput.blur();
      }
    });
    zoomInput.addEventListener('blur', commitZoomInput);
  }

  const jumpInput = document.getElementById('pageJump');
  if (jumpInput) {
    jumpInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        pageJump();
      }
    });
  }

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
