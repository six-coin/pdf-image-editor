/* 指针手势：选中、拖动、四角缩放、框选、平移。
   拖动只改 transform 与 left/top，不重排布局；松手时一次性提交给后端。 */

import { call } from './bridge.js';
import { applySelection, objectEl, pageEl } from './render.js';
import { pxPerPt, state } from './state.js';
import { isSplitActive } from './split.js';

const THRESHOLD = 3;
const MIN_SIZE = 4;

let gesture = null;
let spaceHeld = false;

export function setSpaceHeld(value) {
  spaceHeld = Boolean(value);
}

export function isInteracting() {
  return gesture !== null;
}

function viewport() {
  return document.getElementById('viewport');
}

/* ---------- 坐标 ---------- */

function pagesBox() {
  return document.getElementById('pages');
}

function pageRectRel(index) {
  const el = pageEl(index);
  if (!el) return null;
  const base = pagesBox().getBoundingClientRect();
  const rect = el.getBoundingClientRect();
  return {
    left: rect.left - base.left,
    top: rect.top - base.top,
    width: rect.width,
    height: rect.height,
  };
}

function scenePoint(clientX, clientY) {
  const base = pagesBox().getBoundingClientRect();
  return { x: clientX - base.left, y: clientY - base.top };
}

function pageAt(sceneY) {
  if (!state.data) return null;
  let best = null;
  let bestDistance = Infinity;
  for (const info of state.data.pages) {
    const rect = pageRectRel(info.index);
    if (!rect) continue;
    if (sceneY >= rect.top && sceneY <= rect.top + rect.height) return info.index;
    const distance = Math.min(
      Math.abs(sceneY - rect.top),
      Math.abs(sceneY - (rect.top + rect.height))
    );
    if (distance < bestDistance) {
      bestDistance = distance;
      best = info.index;
    }
  }
  return best;
}

/* ---------- 与 core/geometry.py 同构的四角缩放 ---------- */

export function scaleFromCorner(rect, corner, dx, dy, keepRatio, minSize = MIN_SIZE) {
  const right = rect.x + rect.w;
  const bottom = rect.y + rect.h;
  const px = corner === 'tl' || corner === 'bl' ? rect.x + dx : right + dx;
  const py = corner === 'tl' || corner === 'tr' ? rect.y + dy : bottom + dy;

  let nx = rect.x;
  let ny = rect.y;
  let nw = rect.w;
  let nh = rect.h;

  if (corner === 'tl') {
    nx = px;
    ny = py;
    nw = right - px;
    nh = bottom - py;
  } else if (corner === 'tr') {
    ny = py;
    nw = px - rect.x;
    nh = bottom - py;
  } else if (corner === 'bl') {
    nx = px;
    nw = right - px;
    nh = py - rect.y;
  } else {
    nw = px - rect.x;
    nh = py - rect.y;
  }

  if (keepRatio && rect.h > 0 && rect.w > 0) {
    const ratio = rect.w / rect.h;
    const widthRatio = Math.abs(nw - rect.w) / rect.w;
    const heightRatio = Math.abs(nh - rect.h) / rect.h;
    if (widthRatio >= heightRatio) nh = nw / ratio;
    else nw = nh * ratio;
    const anchorX = corner === 'tl' || corner === 'bl' ? right : rect.x;
    const anchorY = corner === 'tl' || corner === 'tr' ? bottom : rect.y;
    nx = corner === 'tl' || corner === 'bl' ? anchorX - nw : anchorX;
    ny = corner === 'tl' || corner === 'tr' ? anchorY - nh : anchorY;
  }

  if (nw < minSize || nh < minSize) return { ...rect };
  return { x: nx, y: ny, w: nw, h: nh };
}

/* ---------- 事件 ---------- */

export function bindInteract() {
  const box = viewport();
  box.addEventListener('pointerdown', onDown);
  box.addEventListener('pointermove', onMove);
  box.addEventListener('pointerup', onUp);
  box.addEventListener('pointercancel', onUp);
}

function onDown(event) {
  if (!state.data || !state.data.doc.page_count) return;
  if (isSplitActive()) return;

  if (event.button === 1 || (event.button === 0 && spaceHeld)) {
    event.preventDefault();
    startPan(event);
    return;
  }
  if (event.button !== 0) return;

  const handle = event.target.closest('.handles i');
  const node = event.target.closest('.obj');
  const pageNode = event.target.closest('.page');

  if (handle && node) {
    startResize(event, node, handle.dataset.corner);
  } else if (node) {
    startMove(event, node);
  } else if (pageNode) {
    startMarquee(event, Number(pageNode.dataset.page));
  } else {
    applySelection([]);
    call('select', []);
  }
}

function capture(event) {
  try {
    viewport().setPointerCapture(event.pointerId);
  } catch (error) {
    /* 某些指针类型不支持捕获，退化为普通移动 */
  }
}

function release(event) {
  try {
    viewport().releasePointerCapture(event.pointerId);
  } catch (error) {
    /* 已经释放 */
  }
}

/* ---------- 拖动 ---------- */

function startMove(event, node) {
  const id = node.dataset.id;
  const current = (state.data.selection || []).slice();
  let ids = current.includes(id) ? current : [id];
  if (event.shiftKey) {
    ids = current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
  }
  if (!ids.length) {
    applySelection([]);
    return;
  }
  applySelection(ids);

  const k = pxPerPt();
  const items = [];
  for (const objectId of ids) {
    const obj = state.data.objects.find((o) => o.id === objectId);
    const el = objectEl(objectId);
    if (!obj || !el) continue;
    const origin = pageRectRel(obj.page);
    if (!origin) continue;
    items.push({
      id: objectId,
      obj,
      el,
      origin,
      mountedOn: obj.page,
      target: obj.page,
      before: { x: obj.x, y: obj.y, w: obj.w, h: obj.h, page: obj.page },
      scene: {
        left: origin.left + obj.x * k,
        top: origin.top + obj.y * k,
        width: obj.w * k,
        height: obj.h * k,
      },
      next: null,
    });
  }
  if (!items.length) return;

  gesture = {
    kind: 'move',
    pointerId: event.pointerId,
    start: scenePoint(event.clientX, event.clientY),
    items,
    moved: false,
    ids,
  };
  capture(event);
  event.preventDefault();
}

function moveItems(point) {
  const dx = point.x - gesture.start.x;
  const dy = point.y - gesture.start.y;

  for (const item of gesture.items) {
    const next = {
      left: item.scene.left + dx,
      top: item.scene.top + dy,
      width: item.scene.width,
      height: item.scene.height,
    };
    const target = pageAt(next.top + next.height / 2);
    const pageIndex = target === null ? item.obj.page : target;
    const rect = pageRectRel(pageIndex);
    if (!rect) continue;

    const maxLeft = rect.left + Math.max(0, rect.width - next.width);
    const maxTop = rect.top + Math.max(0, rect.height - next.height);
    next.left = Math.min(Math.max(next.left, rect.left), maxLeft);
    next.top = Math.min(Math.max(next.top, rect.top), maxTop);

    if (pageIndex !== item.mountedOn) {
      const box = pageEl(pageIndex) && pageEl(pageIndex).querySelector('.objects');
      if (box) {
        box.appendChild(item.el);
        item.mountedOn = pageIndex;
        item.origin = rect;
      }
    }
    item.target = pageIndex;
    item.next = next;
    item.el.style.left = `${next.left - item.origin.left}px`;
    item.el.style.top = `${next.top - item.origin.top}px`;
  }
}

/* ---------- 缩放 ---------- */

function startResize(event, node, corner) {
  const id = node.dataset.id;
  const obj = state.data.objects.find((o) => o.id === id);
  if (!obj) return;
  applySelection([id]);

  gesture = {
    kind: 'resize',
    pointerId: event.pointerId,
    start: scenePoint(event.clientX, event.clientY),
    corner,
    item: {
      id,
      el: node,
      before: { x: obj.x, y: obj.y, w: obj.w, h: obj.h, page: obj.page },
      next: null,
    },
    moved: false,
  };
  capture(event);
  event.preventDefault();
}

function resizeItem(point, freeRatio) {
  const k = pxPerPt();
  const item = gesture.item;
  const dx = (point.x - gesture.start.x) / k;
  const dy = (point.y - gesture.start.y) / k;
  const rect = scaleFromCorner(item.before, gesture.corner, dx, dy, !freeRatio);
  item.next = rect;
  item.el.style.left = `${rect.x * k}px`;
  item.el.style.top = `${rect.y * k}px`;
  item.el.style.width = `${rect.w * k}px`;
  item.el.style.height = `${rect.h * k}px`;
}

/* ---------- 框选 ---------- */

function startMarquee(event, pageIndex) {
  gesture = {
    kind: 'marquee',
    pointerId: event.pointerId,
    pageIndex,
    start: scenePoint(event.clientX, event.clientY),
    band: null,
  };
  capture(event);
  event.preventDefault();
}

function marqueeBand(point) {
  const rect = pageRectRel(gesture.pageIndex);
  const k = pxPerPt();
  const x0 = Math.min(gesture.start.x, point.x);
  const y0 = Math.min(gesture.start.y, point.y);
  const x1 = Math.max(gesture.start.x, point.x);
  const y1 = Math.max(gesture.start.y, point.y);
  return {
    x: (x0 - rect.left) / k,
    y: (y0 - rect.top) / k,
    w: (x1 - x0) / k,
    h: (y1 - y0) / k,
  };
}

function drawMarquee(band) {
  const el = pageEl(gesture.pageIndex);
  if (!el) return;
  const canvas = el.querySelector('.overlay');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const k = pxPerPt();
  const dpr = state.view.dpr;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(dpr * k, 0, 0, dpr * k, 0, 0);

  const styles = getComputedStyle(document.documentElement);
  ctx.fillStyle = styles.getPropertyValue('--marquee-fill').trim();
  ctx.strokeStyle = styles.getPropertyValue('--marquee-stroke').trim();
  ctx.lineWidth = 1 / k;
  ctx.fillRect(band.x, band.y, band.w, band.h);
  ctx.strokeRect(band.x, band.y, band.w, band.h);
}

function clearOverlay(pageIndex) {
  const el = pageEl(pageIndex);
  if (!el) return;
  const canvas = el.querySelector('.overlay');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function finishMarquee() {
  const band = gesture.band;
  clearOverlay(gesture.pageIndex);
  if (!band || band.w < 1 || band.h < 1) {
    applySelection([]);
    call('select', []);
    return;
  }
  const hits = state.data.objects
    .filter((obj) => obj.page === gesture.pageIndex)
    .filter(
      (obj) =>
        obj.x < band.x + band.w &&
        obj.x + obj.w > band.x &&
        obj.y < band.y + band.h &&
        obj.y + obj.h > band.y
    )
    .map((obj) => obj.id);
  applySelection(hits);
  call('select', hits);
}

/* ---------- 平移 ---------- */

function startPan(event) {
  const box = viewport();
  gesture = {
    kind: 'pan',
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: box.scrollLeft,
    scrollTop: box.scrollTop,
  };
  box.style.cursor = 'grabbing';
  capture(event);
}

function panTo(event) {
  const box = viewport();
  box.scrollLeft = gesture.scrollLeft - (event.clientX - gesture.startX);
  box.scrollTop = gesture.scrollTop - (event.clientY - gesture.startY);
}

/* ---------- 主循环 ---------- */

function onMove(event) {
  if (!gesture || gesture.pointerId !== event.pointerId) return;
  const point = scenePoint(event.clientX, event.clientY);

  if (gesture.kind === 'pan') {
    panTo(event);
    return;
  }

  if (!gesture.moved) {
    const dx = point.x - gesture.start.x;
    const dy = point.y - gesture.start.y;
    if (Math.hypot(dx, dy) < THRESHOLD) return;
    gesture.moved = true;
  }

  if (gesture.kind === 'move') moveItems(point);
  else if (gesture.kind === 'resize') resizeItem(point, event.altKey);
  else if (gesture.kind === 'marquee') {
    gesture.band = marqueeBand(point);
    drawMarquee(gesture.band);
  }
}

function onUp(event) {
  if (!gesture || gesture.pointerId !== event.pointerId) return;
  const current = gesture;
  gesture = null;
  release(event);

  if (current.kind === 'pan') {
    viewport().style.cursor = '';
    return;
  }
  if (current.kind === 'marquee') {
    finishMarquee();
    return;
  }
  if (current.kind === 'move') {
    if (!current.moved) {
      applySelection(current.ids);
      call('select', current.ids);
      return;
    }
    commitMove(current);
    return;
  }
  if (current.kind === 'resize') {
    if (current.moved && current.item.next) commitResize(current.item);
    else call('select', [current.item.id]);
  }
}

function commitMove(current) {
  const k = pxPerPt();
  const payload = [];
  for (const item of current.items) {
    if (!item.next) continue;
    const rect = pageRectRel(item.target);
    if (!rect) continue;
    payload.push({
      id: item.id,
      page: item.target,
      x: (item.next.left - rect.left) / k,
      y: (item.next.top - rect.top) / k,
      w: item.next.width / k,
      h: item.next.height / k,
    });
  }
  if (!payload.length) return;
  call('commit_transform', payload).then((snapshot) => snapshot && dispatch(snapshot));
}

function commitResize(item) {
  call('commit_transform', [
    {
      id: item.id,
      page: item.before.page,
      x: item.next.x,
      y: item.next.y,
      w: item.next.w,
      h: item.next.h,
    },
  ]).then((snapshot) => snapshot && dispatch(snapshot));
}

/** 延迟导入，避免 render 与 interact 之间的模块环。 */
function dispatch(snapshot) {
  import('./render.js').then((mod) => mod.apply(snapshot));
}

/* ---------- 键盘微调 ---------- */

export function nudge(dx, dy) {
  const ids = (state.data && state.data.selection) || [];
  if (!ids.length) return;
  const payload = [];
  for (const id of ids) {
    const obj = state.data.objects.find((o) => o.id === id);
    if (!obj) continue;
    payload.push({ id, page: obj.page, x: obj.x + dx, y: obj.y + dy, w: obj.w, h: obj.h });
  }
  if (!payload.length) return;
  call('commit_transform', payload).then((snapshot) => snapshot && dispatch(snapshot));
}
