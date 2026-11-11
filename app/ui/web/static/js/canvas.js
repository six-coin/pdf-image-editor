/* 画布：页面可见性、背景图加载、缩放与滚动。
   背景位图按目标 DPI 由后端渲染，只在"进入加载窗口"或"DPI 档位变化"时重新拉取；
   中间的连续缩放只改 CSS 尺寸，不重传图片。 */

import { call } from './bridge.js';
import { BASE_PX_PER_PT, clampZoom, dpiForZoom, state } from './state.js';
import { layoutPages, pageEl, renderPageIndicator, renderZoom } from './render.js';
import { scheduleRefresh } from './sync.js';

// 加载窗口：本页 → 后一页 → 前一页 → 后两页。50 页的文档跳到第 30 页只拉这四页，
// 不会因为滚动经过而把前 29 页全渲染一遍。
const WINDOW = [0, 1, -1, 2];

const visible = new Set();
const inflight = new Set();
// 加载失败的页：同一个 (页, dpi) 不要在 pump 里原地重试，否则会变成死循环。
// 快照落地（layout:done）时清空——那时文档状态可能已经变了，值得再试一次。
const failed = new Set();
let observer = null;
let zoomTimer = 0;
let pumping = false;

function viewport() {
  return document.getElementById('viewport');
}

/* ---------- 可见性与加载 ---------- */

export function observePages() {
  if (observer) observer.disconnect();
  visible.clear();
  failed.clear();
  // 只观察视口本身：留 margin 等于提前加载屏幕外的页，窗口已经由 WINDOW 管了。
  observer = new IntersectionObserver(onIntersect, { root: viewport() });
  document.querySelectorAll('.page').forEach((el) => observer.observe(el));
  pump();
}

function onIntersect(entries) {
  for (const entry of entries) {
    const index = Number(entry.target.dataset.page);
    if (entry.isIntersecting) visible.add(index);
    else visible.delete(index);
  }
  pump();
}

/** 当前该加载哪些页：加载窗口 + 真正压在视口里的页（低倍缩放时可能超出窗口）。 */
function wantedPages() {
  const pages = state.data ? state.data.pages : [];
  if (!pages.length) return [];
  const current = currentPage();
  const wanted = new Set();
  for (const offset of WINDOW) {
    const index = current + offset;
    if (index >= 0 && index < pages.length) wanted.add(index);
  }
  for (const index of visible) wanted.add(index);
  return [...wanted];
}

/** 越小越先加载。窗口内按 WINDOW 的顺序，窗口外的可见页排在最后。 */
function priorityOf(index, current) {
  const rank = WINDOW.indexOf(index - current);
  return rank >= 0 ? rank : WINDOW.length + Math.abs(index - current);
}

/**
 * 逐个加载：同一时刻只发一个请求。
 *
 * 后端的 load_page 要拿同一把锁，并发发出去也只会在锁上排队；串行还能保证
 * 「当前页」一定第一个回来，不会出现先请求的远页堵住近页。
 */
function pump() {
  if (pumping || !state.data) return;
  pumping = true;

  const step = () => {
    const dpi = state.view.dpi;
    const current = currentPage();
    let best = null;
    let bestScore = Infinity;

    for (const index of wantedPages()) {
      if (inflight.has(index)) continue;
      if (failed.has(`${index}:${dpi}`)) continue;
      const el = pageEl(index);
      if (!el) continue;
      if (el.dataset.dpi === String(dpi) && el.dataset.loaded === '1') continue;
      const score = priorityOf(index, current);
      if (score < bestScore) {
        bestScore = score;
        best = index;
      }
    }

    if (best === null) {
      pumping = false;
      return;
    }

    inflight.add(best);
    loadPage(best, dpi).finally(() => {
      inflight.delete(best);
      step();
    });
  };

  step();
}

async function loadPage(index, dpi) {
  const el = pageEl(index);
  if (!el) return;

  const data = await call('load_page', index, dpi);
  if (!data || !data.ok) {
    failed.add(`${index}:${dpi}`);
    return;
  }
  if (state.view.dpi !== dpi) return; // 缩放档位已变，丢弃过期回包

  failed.delete(`${index}:${dpi}`);
  el.dataset.dpi = String(dpi);
  el.dataset.loaded = '1';

  const img = el.querySelector('.page-bg');
  if (img) img.src = data.url;
  el.classList.remove('loading');

  // 页面装载可能带来新对象，交给统一通道去拉快照，前端不自己拼模型。
  scheduleRefresh();
}

function reloadVisible() {
  pump();
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

/**
 * 适合宽度。
 *
 * `resetScroll` 只在打开新文件时传 true：那时视口还停在上一份文件的滚动位置，
 * 得回到顶部。点按钮、拖窗口大小都必须留在当前页——以前这里无条件
 * `scrollTop = 0`，在第 30 页点一下适合宽度就跳回第 1 页了。
 */
export function fitWidth(resetScroll = false) {
  const pages = state.data && state.data.pages;
  if (!pages || !pages.length) return;
  const box = viewport();
  const widest = Math.max(...pages.map((p) => p.w));
  // 左右各留 48px 的留白（.pages 的 padding），两边必须一样宽。
  const available = Math.max(80, box.clientWidth - 96);
  const zoom = clampZoom(available / (widest * BASE_PX_PER_PT));
  // setZoom 会把 fitWidth 清掉（它代表「用户手动缩放过」），所以缩完再置位。
  setZoom(zoom, null, true);
  state.view.fitWidth = true;
  if (resetScroll === true) box.scrollTop = 0;
}

export function resetZoom() {
  state.view.fitWidth = false;
  setZoom(1, null, true);
}

/** 把某一页滚到视口顶部。远距离直接跳：平滑滚动会一路经过中间页，每页都触发加载。 */
export function scrollToPage(index) {
  const box = viewport();
  const el = pageEl(index);
  if (!box || !el) return;
  const top = Math.max(0, el.offsetTop - 24);
  const far = Math.abs(top - box.scrollTop) > box.clientHeight * 1.5;
  box.scrollTo({ top, behavior: far ? 'auto' : 'smooth' });
  // 不等 IntersectionObserver 的下一帧，立刻按新位置排一次加载
  pump();
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

  // 快照落地会重新布局：文档状态可能变了（比如保存完成），失败过的页值得再试一次
  document.addEventListener('layout:done', () => {
    failed.clear();
    pump();
  });

  let scrollFrame = 0;
  box.addEventListener('scroll', () => {
    if (scrollFrame) return;
    scrollFrame = window.requestAnimationFrame(() => {
      scrollFrame = 0;
      renderPageIndicator(currentPage());
      // 当前页变了，加载窗口跟着挪；不停留在上一次的窗口上
      pump();
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
