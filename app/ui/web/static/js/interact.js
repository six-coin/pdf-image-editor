/* 指针手势：选中、拖动、四角缩放、平移。
   拖动只改 left/top，不重排布局；松手时一次性提交给后端。

   手势期间禁止任何快照落地（见 state.view.gesture）：重建 DOM 会把正在拖的
   节点换掉，表现就是"元素突然被拉回原位"。 */

import { call } from './bridge.js';
import { apply, applySelection, objectEl, pageEl } from './render.js';
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

/* ---------- 手势生命周期 ---------- */

function beginGesture(detail) {
  state.view.gesture = true;
  gesture = detail;
}

function endGesture() {
  state.view.gesture = false;
  gesture = null;
  // 手势期间被丢弃的快照不作数，这里重新拉一份最新的。
  if (state.stale) {
    state.stale = false;
    scheduleRefresh(0);
  }
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

  if (handle && node) {
    startResize(event, node, handle.dataset.corner);
    return;
  }
  if (node) {
    startMove(event, node);
    return;
  }
  // 空白处：取消选中
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
  const current = (state.data.selection || []).slice();
  let ids = current.includes(id) ? current : [id];
  if (event.shiftKey) {
    ids = current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
  }
  if (!ids.length) {
    applySelection([]);
    return;
  }
  // 点谁选谁：即使还没松手，视觉上也立刻切到这个元素。
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

  beginGesture({
    kind: 'move',
    pointerId: event.pointerId,
    start: scenePoint(event.clientX, event.clientY),
    items,
    moved: false,
    ids,
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
  const dx = (point.x - gesture.start.x) / k;
  const dy = (point.y - gesture.start.y) / k;
  const rect = scaleFromCorner(item.before, gesture.corner, dx, dy, !freeRatio);
  item.next = rect;
  item.el.style.left = `${rect.x * k}px`;
  item.el.style.top = `${rect.y * k}px`;
  item.el.style.width = `${rect.w * k}px`;
  item.el.style.height = `${rect.h * k}px`;
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

  if (current.kind === 'move') {
    if (!current.moved) {
      applySelection(current.ids);
      commitSelection(current.ids);
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
  const ids = (state.data && state.data.selection) || [];
  if (!ids.length) return;
  const payload = [];
  for (const id of ids) {
    const obj = state.data.objects.find((o) => o.id === id);
    if (!obj) continue;
    payload.push({ id, page: obj.page, x: obj.x + dx, y: obj.y + dy, w: obj.w, h: obj.h });
  }
  if (!payload.length) return;
  call('commit_transform', payload).then((snapshot) => snapshot && apply(snapshot));
}
