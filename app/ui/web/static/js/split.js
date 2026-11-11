/* 分割模式。
   切线是纯视图状态，按落笔顺序记在一个数组里——撤销就是弹最后一条，
   而不是"先撤竖线再撤横线"。后端只收 cuts 与显式的 (row, col)。 */

import { call, T, toast } from './bridge.js';
import { apply, pageEl } from './render.js';
import { pxPerPt, state } from './state.js';

const $ = (id) => document.getElementById(id);

// 两条切线靠得比这个还近就算同一条：它切出来的格子不足 0.01% 宽，点不中也看不见。
const CUT_GAP = 1e-4;

const split = {
  active: false,
  objectId: null,
  page: 0,
  rect: null,
  marks: [],
  hover: null,
  pointer: null,
  vertical: false,
};

export function isSplitActive() {
  return split.active;
}

function viewport() {
  return document.getElementById('viewport');
}

function cutsOf(axis) {
  return split.marks.filter((mark) => mark.axis === axis).map((mark) => mark.value);
}

/* ---------- 进出 ---------- */

export function startSplit() {
  const ids = (state.data && state.data.selection) || [];
  if (ids.length !== 1) {
    toast(T('split.need_one'), false);
    return;
  }
  const obj = state.data.objects.find((o) => o.id === ids[0]);
  if (!obj) return;

  split.active = true;
  split.objectId = obj.id;
  split.page = obj.page;
  split.rect = { x: obj.x, y: obj.y, w: obj.w, h: obj.h };
  split.marks = [];
  split.hover = null;
  split.pointer = null;
  split.vertical = false;

  const node = document.querySelector(`.obj[data-id="${obj.id}"]`);
  if (node) node.classList.add('splitting');
  viewport().classList.add('splitting');
  $('splitBar').classList.remove('hidden');
  redraw();
  updateBar();
}

export function cancelSplit() {
  if (!split.active) return;
  const node = document.querySelector(`.obj[data-id="${split.objectId}"]`);
  if (node) node.classList.remove('splitting');
  viewport().classList.remove('splitting');
  $('splitBar').classList.add('hidden');
  clearOverlay();
  split.active = false;
  split.objectId = null;
  split.rect = null;
  split.hover = null;
  split.pointer = null;
  split.marks = [];
}

/* ---------- 坐标 ---------- */

function pointerPt(event) {
  const el = pageEl(split.page);
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  const k = pxPerPt();
  return { x: (event.clientX - rect.left) / k, y: (event.clientY - rect.top) / k };
}

function inside(point) {
  const r = split.rect;
  return point.x >= r.x && point.x <= r.x + r.w && point.y >= r.y && point.y <= r.y + r.h;
}

function bounds(values) {
  // 与后端 core/geometry._bounds 同构：按 9 位小数去重后再排序。
  // 不去重的话，两条切线重合时前端会多算出一列零宽格，行列号整体右移一格，
  // 「仅保留此格」就会指到后端不存在的格子，点了没有任何反应。
  const unique = new Map();
  for (const value of values) unique.set(value.toFixed(9), value);
  return [0, ...[...unique.values()].sort((a, b) => a - b), 1];
}

function cellAt(point) {
  const r = split.rect;
  const xs = bounds(cutsOf('v'));
  const ys = bounds(cutsOf('h'));
  const fx = (point.x - r.x) / r.w;
  const fy = (point.y - r.y) / r.h;
  let col = -1;
  let row = -1;
  for (let i = 0; i < xs.length - 1; i += 1) {
    if (fx >= xs[i] && fx <= xs[i + 1]) col = i;
  }
  for (let i = 0; i < ys.length - 1; i += 1) {
    if (fy >= ys[i] && fy <= ys[i + 1]) row = i;
  }
  if (row < 0 || col < 0) return null;
  return { row, col };
}

function cellRect(row, col) {
  const r = split.rect;
  const xs = bounds(cutsOf('v'));
  const ys = bounds(cutsOf('h'));
  return {
    x: r.x + xs[col] * r.w,
    y: r.y + ys[row] * r.h,
    w: (xs[col + 1] - xs[col]) * r.w,
    h: (ys[row + 1] - ys[row]) * r.h,
  };
}

/* ---------- 绘制 ---------- */

function overlay() {
  const el = pageEl(split.page);
  if (!el) return null;
  const canvas = el.querySelector('.overlay');
  if (!canvas) return null;
  const ctx = canvas.getContext('2d');
  const k = pxPerPt();
  const dpr = state.view.dpr;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.setTransform(dpr * k, 0, 0, dpr * k, 0, 0);
  return ctx;
}

function clearOverlay() {
  const el = pageEl(split.page);
  if (!el) return;
  const canvas = el.querySelector('.overlay');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function redraw() {
  if (!split.active) return;
  const ctx = overlay();
  if (!ctx) return;
  const styles = getComputedStyle(document.documentElement);
  const page = state.data.pages.find((p) => p.index === split.page);
  const k = pxPerPt();
  const r = split.rect;

  ctx.fillStyle = styles.getPropertyValue('--backdrop').trim();
  ctx.fillRect(0, 0, page.w, r.y);
  ctx.fillRect(0, r.y + r.h, page.w, page.h - (r.y + r.h));
  ctx.fillRect(0, r.y, r.x, r.h);
  ctx.fillRect(r.x + r.w, r.y, page.w - (r.x + r.w), r.h);

  if (split.hover) {
    const cell = cellRect(split.hover.row, split.hover.col);
    ctx.fillStyle = styles.getPropertyValue('--split-cell-hover').trim();
    ctx.fillRect(cell.x, cell.y, cell.w, cell.h);
  }

  ctx.strokeStyle = styles.getPropertyValue('--split-line').trim();
  ctx.lineWidth = 1 / k;
  for (const cut of cutsOf('h')) {
    const y = r.y + cut * r.h;
    ctx.beginPath();
    ctx.moveTo(r.x, y);
    ctx.lineTo(r.x + r.w, y);
    ctx.stroke();
  }
  for (const cut of cutsOf('v')) {
    const x = r.x + cut * r.w;
    ctx.beginPath();
    ctx.moveTo(x, r.y);
    ctx.lineTo(x, r.y + r.h);
    ctx.stroke();
  }

  if (split.pointer && inside(split.pointer)) {
    ctx.strokeStyle = styles.getPropertyValue('--guide-active').trim();
    ctx.setLineDash([4 / k, 4 / k]);
    ctx.beginPath();
    if (split.vertical) {
      const x = split.pointer.x;
      ctx.moveTo(x, r.y);
      ctx.lineTo(x, r.y + r.h);
    } else {
      const y = split.pointer.y;
      ctx.moveTo(r.x, y);
      ctx.lineTo(r.x + r.w, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  ctx.strokeStyle = styles.getPropertyValue('--obj-outline').trim();
  ctx.lineWidth = 1 / k;
  ctx.strokeRect(r.x, r.y, r.w, r.h);
}

/* ---------- 工具条 ---------- */

function updateBar() {
  const total = split.marks.length;
  $('splitHint').textContent = `${T('split.hint')} · ${T('split.cuts', {
    h: cutsOf('h').length,
    v: cutsOf('v').length,
  })}`;
  $('splitKeep').disabled = !split.hover;
  $('splitPunch').disabled = !split.hover;
  $('splitAll').disabled = total === 0;
}

/** 语言变了：分割条上的提示文字是现算的，要重来一遍。 */
export function refreshSplitBar() {
  if (!split.active) return;
  updateBar();
}

/* ---------- 事件 ---------- */

function onPointerMove(event) {
  if (!split.active) return;
  const point = pointerPt(event);
  if (!point) return;
  split.pointer = point;
  split.vertical = event.shiftKey;
  split.hover = inside(point) ? cellAt(point) : null;
  redraw();
  updateBar();
}

function onPointerDown(event) {
  if (!split.active) return;
  if (event.button !== 0) return;
  event.preventDefault();
  const point = pointerPt(event);
  if (!point || !inside(point)) return;
  const r = split.rect;
  const axis = event.shiftKey ? 'v' : 'h';
  const raw = axis === 'v' ? (point.x - r.x) / r.w : (point.y - r.y) / r.h;
  const value = Math.min(0.999, Math.max(0.001, raw));
  // 同一位置重复落刀只会多出一条零宽格，直接忽略。
  if (cutsOf(axis).some((existing) => Math.abs(existing - value) < CUT_GAP)) return;
  split.marks.push({ axis, value });
  split.hover = cellAt(point);
  redraw();
  updateBar();
}

export function bindSplit() {
  const box = viewport();
  box.addEventListener('pointerdown', onPointerDown);
  box.addEventListener('pointermove', onPointerMove);
  box.addEventListener('pointerleave', () => {
    if (!split.active) return;
    split.pointer = null;
    split.hover = null;
    redraw();
    updateBar();
  });
}

/* ---------- 执行 ---------- */

async function applyEdit(method, args) {
  const snapshot = await call(method, ...args);
  if (snapshot) {
    cancelSplit();
    apply(snapshot);
  }
}

function cutArgs() {
  return [cutsOf('v'), cutsOf('h')];
}

export function splitAll() {
  if (!split.active || !split.marks.length) return;
  const [cutsX, cutsY] = cutArgs();
  applyEdit('split_object', [split.objectId, cutsX, cutsY]);
}

export function keepCell() {
  if (!split.active || !split.hover) return;
  const [cutsX, cutsY] = cutArgs();
  applyEdit('keep_cell', [split.objectId, cutsX, cutsY, split.hover.row, split.hover.col]);
}

export function punchCell() {
  if (!split.active || !split.hover) return;
  const [cutsX, cutsY] = cutArgs();
  applyEdit('punch_cell', [split.objectId, cutsX, cutsY, split.hover.row, split.hover.col]);
}

/** 撤销最后一刀——按落笔顺序，不区分横竖。 */
export function undoCut() {
  if (!split.active || !split.marks.length) return;
  split.marks.pop();
  split.hover = split.pointer ? cellAt(split.pointer) : null;
  redraw();
  updateBar();
}
