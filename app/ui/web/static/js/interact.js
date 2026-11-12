/* 指针手势：选中、拖动、手柄缩放、组框缩放、框选、平移。
   拖动只改 left/top，不重排布局；松手时一次性提交给后端。

   手势期间禁止任何快照落地（见 state.view.gesture）：重建 DOM 会把正在拖的
   节点换掉，表现就是"元素突然被拉回原位"。 */

import { call, T, toast } from './bridge.js';
import {
  apply,
  applySelection,
  objectEl,
  pageEl,
  selectedObjects,
  selectionBounds,
  setGroupBoxVisible,
} from './render.js';
import { pxPerPt, state } from './state.js';
import { scheduleRefresh } from './sync.js';
import { isSplitActive } from './split.js';

const THRESHOLD = 3;
const MIN_SIZE = 4;

let gesture = null;
let spaceHeld = false;

export function setSpaceHeld(value) {
  spaceHeld = Boolean(value);
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

/** 指针落在哪一页上，以及它在该页内的 pt 坐标；不在任何页内返回 null。 */
function pagePointAt(clientX, clientY) {
  if (!state.data) return null;
  const k = pxPerPt();
  for (const info of state.data.pages) {
    const el = pageEl(info.index);
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    if (
      clientX < rect.left ||
      clientX > rect.right ||
      clientY < rect.top ||
      clientY > rect.bottom
    ) {
      continue;
    }
    return {
      index: info.index,
      info,
      x: (clientX - rect.left) / k,
      y: (clientY - rect.top) / k,
    };
  }
  return null;
}

/** 相对某一页的 pt 坐标，指针移出页面也照样换算。 */
function pointInPage(clientX, clientY, index) {
  const el = pageEl(index);
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  const k = pxPerPt();
  return { x: (clientX - rect.left) / k, y: (clientY - rect.top) / k };
}

/* ---------- 手势生命周期 ---------- */

function beginGesture(detail) {
  state.view.gesture = true;
  gesture = detail;
  // 组框只给组缩放用；其它手势期间藏起来，免得挡住实时位置。
  if (detail.kind !== 'group') setGroupBoxVisible(false);
}

function endGesture() {
  state.view.gesture = false;
  gesture = null;
  setGroupBoxVisible(true);
  // 手势期间被丢弃的快照不作数，这里重新拉一份最新的。
  if (state.stale) {
    state.stale = false;
    scheduleRefresh(0);
  }
}

/* ---------- 与 core/geometry.py 同构的手柄缩放 ---------- */

const CORNER_HANDLES = ['tl', 'tr', 'bl', 'br'];
const VERTICAL_HANDLES = ['n', 's'];
const HORIZONTAL_HANDLES = ['w', 'e'];

export function scaleFromCorner(rect, corner, dx, dy, keepRatio, minSize = MIN_SIZE) {
  const right = rect.x + rect.w;
  const bottom = rect.y + rect.h;

  // 边手柄只动一个方向，本来就是为了改长宽比，keepRatio 对它们没有意义。
  if (corner === 'n' || corner === 's') {
    const y = corner === 'n' ? rect.y + dy : rect.y;
    const h = corner === 'n' ? bottom - y : rect.h + dy;
    if (h < minSize) return { ...rect };
    return { x: rect.x, y, w: rect.w, h };
  }
  if (corner === 'w' || corner === 'e') {
    const x = corner === 'w' ? rect.x + dx : rect.x;
    const w = corner === 'w' ? right - x : rect.w + dx;
    if (w < minSize) return { ...rect };
    return { x, y: rect.y, w, h: rect.h };
  }

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
    // 只用长边驱动（与 core/geometry.py 同名函数同构）：宽图竖着拖、
    // 竖图横着拖都不改变尺寸，避免短边一动就让另一条边成倍跳。
    if (rect.w >= rect.h) {
      nh = nw / ratio;
    } else {
      nw = nh * ratio;
    }
    const anchorX = corner === 'tl' || corner === 'bl' ? right : rect.x;
    const anchorY = corner === 'tl' || corner === 'tr' ? bottom : rect.y;
    nx = corner === 'tl' || corner === 'bl' ? anchorX - nw : anchorX;
    ny = corner === 'tl' || corner === 'tr' ? anchorY - nh : anchorY;
  }

  if (nw < minSize || nh < minSize) return { ...rect };
  return { x: nx, y: ny, w: nw, h: nh };
}

/* 手柄的命名分两套：角是 tl/tr/bl/br（t=上 b=下 l=左 r=右），边是 n/s/w/e。
   判断"往哪边长"必须两套都认，否则 tl 会被当成向右下长，锚点整个反掉。 */

function anchorOf(rect, corner) {
  return {
    x: corner.includes('w') || corner.includes('l') ? rect.x + rect.w : rect.x,
    y: corner.includes('n') || corner.includes('t') ? rect.y + rect.h : rect.y,
  };
}

/** 沿手柄方向最多能放大到多少倍——再大对应的那条边就出页了。 */
function limitScale(corner, anchor, w, h, pageW, pageH) {
  return {
    maxSx:
      corner.includes('w') || corner.includes('l') ? anchor.x / w : (pageW - anchor.x) / w,
    maxSy:
      corner.includes('n') || corner.includes('t') ? anchor.y / h : (pageH - anchor.y) / h,
  };
}

/**
 * 把缩放结果夹进页内，再按锚点重建矩形。
 *
 * ``scaleFromCorner`` 只认指针位移，不知道页面边界；超出页面的部分会被后端的
 * ``clamp_rect_to_page`` 按边裁掉，长宽比就变了。所以这里先按锚点到页边的距离
 * 算出最大倍率，再统一作用到每张图上——组缩放靠这一步保证整组同比例且不出页。
 */
function clampScale(before, corner, scaled, keepRatio, pageW, pageH, minSx = 0, minSy = 0) {
  const anchor = anchorOf(before, corner);
  const { maxSx, maxSy } = limitScale(corner, anchor, before.w, before.h, pageW, pageH);
  let sx = before.w ? scaled.w / before.w : 1;
  let sy = before.h ? scaled.h / before.h : 1;

  // 边手柄只驱动一个方向，另一条边保持原样——那里算出来的 max 没有意义。
  const drivesX = !VERTICAL_HANDLES.includes(corner);
  const drivesY = !HORIZONTAL_HANDLES.includes(corner);

  if (keepRatio) {
    const s = Math.min(Math.max(sx, minSx, minSy), maxSx, maxSy);
    sx = s;
    sy = s;
  } else if (drivesX && drivesY) {
    sx = Math.min(Math.max(sx, minSx), maxSx);
    sy = Math.min(Math.max(sy, minSy), maxSy);
  } else if (drivesX) {
    sx = Math.min(Math.max(sx, minSx), maxSx);
    sy = 1;
  } else {
    sx = 1;
    sy = Math.min(Math.max(sy, minSy), maxSy);
  }

  return {
    sx,
    sy,
    anchorX: anchor.x,
    anchorY: anchor.y,
    x: anchor.x + (before.x - anchor.x) * sx,
    y: anchor.y + (before.y - anchor.y) * sy,
    w: before.w * sx,
    h: before.h * sy,
  };
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
  if (state.view.busy || isSplitActive()) return;

  if (event.button === 1 || (event.button === 0 && spaceHeld)) {
    event.preventDefault();
    startPan(event);
    return;
  }
  if (event.button !== 0) return;

  const groupGrip = event.target.closest('.group-box .grip');
  if (groupGrip) {
    startGroupResize(event, groupGrip.dataset.corner);
    return;
  }

  const handle = event.target.closest('.handles .grip');
  const node = event.target.closest('.obj');

  if (handle && node) {
    startResize(event, node, handle.dataset.corner);
    return;
  }
  if (node) {
    startMove(event, node);
    return;
  }

  // 空白处：从落点拖一个选框出来。落点不在任何页内时只当作取消选择。
  if (startMarquee(event)) return;
  applySelection([]);
  commitSelection([]);
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
  const obj = state.data.objects.find((o) => o.id === id);
  if (!obj) return;

  const current = (state.data.selection || []).slice();
  const pageOf = (objectId) => {
    const found = state.data.objects.find((o) => o.id === objectId);
    return found ? found.page : null;
  };
  const selectionPage = current.length ? pageOf(current[0]) : obj.page;

  let ids;
  if (event.shiftKey) {
    if (current.includes(id)) {
      ids = current.filter((item) => item !== id);
    } else if (current.length && obj.page !== selectionPage) {
      // 多选要画一个组框、按组缩放，跨页的对象没有共同坐标系，所以只能同页。
      toast(T('select.same_page'), false);
      ids = [id];
    } else {
      ids = [...current, id];
    }
  } else {
    ids = current.includes(id) ? current : [id];
  }

  if (!ids.length) {
    applySelection([]);
    commitSelection([]);
    return;
  }
  // 点谁选谁：即使还没松手，视觉上也立刻切到这个元素。
  applySelection(ids);

  const k = pxPerPt();
  const items = [];
  for (const objectId of ids) {
    const item = state.data.objects.find((o) => o.id === objectId);
    const el = objectEl(objectId);
    if (!item || !el) continue;
    const origin = pageRectRel(item.page);
    if (!origin) continue;
    items.push({
      id: objectId,
      obj: item,
      el,
      origin,
      mountedOn: item.page,
      target: item.page,
      before: { x: item.x, y: item.y, w: item.w, h: item.h, page: item.page },
      scene: {
        left: origin.left + item.x * k,
        top: origin.top + item.y * k,
        width: item.w * k,
        height: item.h * k,
      },
      next: null,
    });
  }
  if (!items.length) return;

  beginGesture({
    kind: 'move',
    pointerId: event.pointerId,
    start: scenePoint(event.clientX, event.clientY),
    items,
    moved: false,
    ids,
    // 记下按在谁身上、有没有按 Shift：松手没拖动时要用它收拢选中。
    clicked: id,
    toggled: event.shiftKey,
  });
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
    // 指针进了哪一页就落到哪一页：不用等松手，也不用猜中心点。
    const target = pageAt(point.y);
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

/* ---------- 单图缩放 ---------- */

function startResize(event, node, corner) {
  const id = node.dataset.id;
  const obj = state.data.objects.find((o) => o.id === id);
  if (!obj) return;
  applySelection([id]);

  beginGesture({
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
  });
  capture(event);
  event.preventDefault();
}

function resizeItem(point, freeRatio) {
  const k = pxPerPt();
  const item = gesture.item;
  const before = item.before;
  const info = state.data.pages.find((p) => p.index === before.page);
  if (!info) return;

  const dx = (point.x - gesture.start.x) / k;
  const dy = (point.y - gesture.start.y) / k;
  // 边手柄本身就是改长宽比，Alt 对它们没有意义。
  const keepRatio = CORNER_HANDLES.includes(gesture.corner) && !freeRatio;
  const scaled = scaleFromCorner(before, gesture.corner, dx, dy, keepRatio);
  const rect = clampScale(before, gesture.corner, scaled, keepRatio, info.w, info.h);

  item.next = rect;
  item.el.style.left = `${rect.x * k}px`;
  item.el.style.top = `${rect.y * k}px`;
  item.el.style.width = `${rect.w * k}px`;
  item.el.style.height = `${rect.h * k}px`;
}

/* ---------- 组框缩放 ---------- */

function startGroupResize(event, corner) {
  const bounds = selectionBounds();
  if (!bounds) return;
  const items = selectedObjects().map((obj) => ({
    id: obj.id,
    el: objectEl(obj.id),
    before: { x: obj.x, y: obj.y, w: obj.w, h: obj.h, page: obj.page },
  }));
  if (items.length < 2) return;

  beginGesture({
    kind: 'group',
    pointerId: event.pointerId,
    start: scenePoint(event.clientX, event.clientY),
    corner,
    bounds,
    page: bounds.page,
    items,
    moved: false,
    next: null,
  });
  capture(event);
  event.preventDefault();
}

function resizeGroup(point, freeRatio) {
  const k = pxPerPt();
  const dx = (point.x - gesture.start.x) / k;
  const dy = (point.y - gesture.start.y) / k;
  const { bounds, corner } = gesture;
  const keepRatio = CORNER_HANDLES.includes(corner) && !freeRatio;

  const info = state.data.pages.find((p) => p.index === gesture.page);
  if (!info) return;

  const scaled = scaleFromCorner(bounds, corner, dx, dy, keepRatio);

  // 组里最小的那张不能小于 MIN_SIZE，否则会被后端拒掉、整组变形。
  let minSx = 0;
  let minSy = 0;
  for (const item of gesture.items) {
    minSx = Math.max(minSx, MIN_SIZE / item.before.w);
    minSy = Math.max(minSy, MIN_SIZE / item.before.h);
  }

  const next = clampScale(
    bounds,
    corner,
    scaled,
    keepRatio,
    info.w,
    info.h,
    minSx,
    minSy
  );
  gesture.next = next;

  for (const item of gesture.items) {
    const before = item.before;
    if (!item.el) continue;
    item.el.style.left = `${(next.anchorX + (before.x - next.anchorX) * next.sx) * k}px`;
    item.el.style.top = `${(next.anchorY + (before.y - next.anchorY) * next.sy) * k}px`;
    item.el.style.width = `${before.w * next.sx * k}px`;
    item.el.style.height = `${before.h * next.sy * k}px`;
  }

  const box = document.getElementById('groupBox');
  if (box) {
    box.style.left = `${next.x * k}px`;
    box.style.top = `${next.y * k}px`;
    box.style.width = `${next.w * k}px`;
    box.style.height = `${next.h * k}px`;
  }
}

function commitGroupResize(current) {
  const next = current.next;
  if (!next) return;
  const payload = current.items.map((item) => ({
    id: item.id,
    page: item.before.page,
    x: next.anchorX + (item.before.x - next.anchorX) * next.sx,
    y: next.anchorY + (item.before.y - next.anchorY) * next.sy,
    w: item.before.w * next.sx,
    h: item.before.h * next.sy,
  }));
  call('commit_transform', payload).then((snapshot) => snapshot && apply(snapshot));
}

/* ---------- 框选 ---------- */

function startMarquee(event) {
  const hit = pagePointAt(event.clientX, event.clientY);
  if (!hit) return false;

  const el = document.createElement('div');
  el.className = 'marquee';
  pageEl(hit.index).appendChild(el);

  beginGesture({
    kind: 'marquee',
    pointerId: event.pointerId,
    page: hit.index,
    origin: {
      x: Math.min(Math.max(hit.x, 0), hit.info.w),
      y: Math.min(Math.max(hit.y, 0), hit.info.h),
    },
    el,
    rect: null,
    preview: null,
    base: event.shiftKey ? (state.data.selection || []).slice() : [],
    moved: false,
    start: scenePoint(event.clientX, event.clientY),
  });
  capture(event);
  event.preventDefault();
  return true;
}

/** 与选框相交就算命中——「只要有一点在框内」。 */
function marqueeHits(rect) {
  return state.data.objects
    .filter((obj) => obj.page === gesture.page)
    .filter(
      (obj) =>
        obj.x < rect.x + rect.w &&
        obj.x + obj.w > rect.x &&
        obj.y < rect.y + rect.h &&
        obj.y + obj.h > rect.y
    )
    .map((obj) => obj.id);
}

function updateMarquee(event) {
  const point = pointInPage(event.clientX, event.clientY, gesture.page);
  if (!point) return;
  const info = state.data.pages.find((p) => p.index === gesture.page);
  if (!info) return;
  const x = Math.min(Math.max(point.x, 0), info.w);
  const y = Math.min(Math.max(point.y, 0), info.h);
  const rect = {
    x: Math.min(gesture.origin.x, x),
    y: Math.min(gesture.origin.y, y),
    w: Math.abs(x - gesture.origin.x),
    h: Math.abs(y - gesture.origin.y),
  };

  const k = pxPerPt();
  gesture.rect = rect;
  gesture.el.style.left = `${rect.x * k}px`;
  gesture.el.style.top = `${rect.y * k}px`;
  gesture.el.style.width = `${rect.w * k}px`;
  gesture.el.style.height = `${rect.h * k}px`;

  // 实时预览：只改 class，不发请求。
  const hits = marqueeHits(rect);
  const ids = gesture.base.length ? [...new Set([...gesture.base, ...hits])] : hits;
  gesture.preview = ids;
  applySelection(ids);
}

/* ---------- 平移 ---------- */

function startPan(event) {
  const box = viewport();
  beginGesture({
    kind: 'pan',
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: box.scrollLeft,
    scrollTop: box.scrollTop,
  });
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
  else if (gesture.kind === 'group') resizeGroup(point, event.altKey);
  else if (gesture.kind === 'marquee') updateMarquee(event);
}

function onUp(event) {
  if (!gesture || gesture.pointerId !== event.pointerId) return;
  const current = gesture;
  const wasPan = current.kind === 'pan';
  release(event);
  endGesture();

  if (wasPan) {
    viewport().style.cursor = '';
    return;
  }

  if (current.kind === 'marquee') {
    current.el.remove();
    if (!current.moved) {
      // 没拖出距离：当作点击空白，清空选择。
      applySelection([]);
      commitSelection([]);
      return;
    }
    commitSelection(current.preview || []);
    return;
  }

  if (current.kind === 'group') {
    if (current.moved) commitGroupResize(current);
    return;
  }

  if (current.kind === 'move') {
    if (!current.moved) {
      // 多选时点中其中一张、又没拖动：只留这一张。
      // 收起选中不能放在 pointerdown——那样就没法整组拖动了。
      const ids =
        !current.toggled && current.ids.length > 1 ? [current.clicked] : current.ids;
      applySelection(ids);
      commitSelection(ids);
      return;
    }
    commitMove(current);
    return;
  }
  if (current.kind === 'resize') {
    if (current.moved && current.item.next) commitResize(current.item);
    else commitSelection([current.item.id]);
  }
}

function commitSelection(ids) {
  call('select', ids).then((snapshot) => snapshot && apply(snapshot));
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
  // 选中跟着一起提交：拖谁就选谁，不用再跑一次往返。
  call('commit_transform', payload, current.ids).then(
    (snapshot) => snapshot && apply(snapshot)
  );
}

function commitResize(item) {
  call(
    'commit_transform',
    [
      {
        id: item.id,
        page: item.before.page,
        x: item.next.x,
        y: item.next.y,
        w: item.next.w,
        h: item.next.h,
      },
    ],
    [item.id]
  ).then((snapshot) => snapshot && apply(snapshot));
}

/* ---------- 键盘微调 ---------- */

export function nudge(dx, dy) {
  if (state.view.busy) return;
  const ids = (state.data && state.data.selection) || [];
  if (!ids.length) return;
  const payload = [];
  for (const id of ids) {
    const obj = state.data.objects.find((o) => o.id === id);
    if (!obj) continue;
    // 和拖动一样夹在页内：后端只按边裁，微调出界会把长宽比裁坏。
    const info = state.data.pages.find((p) => p.index === obj.page);
    const x = info ? Math.min(Math.max(obj.x + dx, 0), Math.max(info.w - obj.w, 0)) : obj.x + dx;
    const y = info ? Math.min(Math.max(obj.y + dy, 0), Math.max(info.h - obj.h, 0)) : obj.y + dy;
    payload.push({ id, page: obj.page, x, y, w: obj.w, h: obj.h });
  }
  if (!payload.length) return;
  call('commit_transform', payload).then((snapshot) => snapshot && apply(snapshot));
}
