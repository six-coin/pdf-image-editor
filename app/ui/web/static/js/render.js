/* 渲染：把后端快照铺到 DOM 上。
   前端不维护业务数据，快照变了就整体重绘；只有纯视图状态留在这边。 */

import { T } from './bridge.js';
import { objectsOf, pageInfo, pxPerPt, state } from './state.js';

const $ = (id) => document.getElementById(id);

export function pageEl(index) {
  return document.querySelector(`.page[data-page="${index}"]`);
}

export function objectEl(id) {
  return document.querySelector(`.obj[data-id="${id}"]`);
}

/* ---------- 文案 ---------- */

export function applyStrings() {
  const table = state.strings;
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    const text = table[node.dataset.i18n];
    if (text !== undefined) node.textContent = text;
  });
  document.querySelectorAll('[data-i18n-title]').forEach((node) => {
    const text = table[node.dataset.i18nTitle];
    if (text !== undefined) node.title = text;
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
    const text = table[node.dataset.i18nPlaceholder];
    if (text !== undefined) node.placeholder = text;
  });
  document.querySelectorAll('[data-i18n-aria]').forEach((node) => {
    const text = table[node.dataset.i18nAria];
    if (text !== undefined) node.setAttribute('aria-label', text);
  });
}

/* ---------- 主题 ---------- */

export function applyTheme(theme) {
  const next = theme === 'dark' ? 'dark' : 'light';
  state.view.theme = next;
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem('appTheme', next);
  } catch (error) {
    /* 隐私模式下写不进去，不影响使用 */
  }
  document.querySelectorAll('#themeSeg .seg-item').forEach((node) => {
    const active = node.dataset.themeValue === next;
    node.classList.toggle('active', active);
    node.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

/* ---------- 主入口 ---------- */

function signature(objects) {
  return objects
    .map((o) => `${o.id}:${o.x},${o.y},${o.w},${o.h},${o.z},${o.page}`)
    .join('|');
}

export function apply(data) {
  if (!data) return;
  const previous = state.data;
  const rebuilt = !previous || previous.doc.generation !== data.doc.generation;
  const changed = !previous || signature(previous.objects) !== signature(data.objects);
  const selectionChanged =
    !previous || previous.selection.join() !== data.selection.join();

  state.data = data;
  applyTheme(data.theme);
  applyChrome();

  if (rebuilt) {
    buildPages();
    layoutPages();
    renderObjects();
    document.dispatchEvent(new CustomEvent('pages:rebuilt'));
  } else {
    layoutPages();
    if (changed) renderObjects();
    else if (selectionChanged) applySelection();
  }

  renderInspector();
}

function applyChrome() {
  const doc = state.data.doc;
  const hasDoc = doc.page_count > 0;

  $('empty').hidden = hasDoc;
  $('pages').hidden = !hasDoc;

  document.querySelectorAll('[data-act="save"]').forEach((b) => {
    b.disabled = !hasDoc || !doc.can_save;
  });
  document.querySelectorAll('[data-act="save-as"], [data-act="export"]').forEach((b) => {
    b.disabled = !hasDoc;
  });
  document.querySelectorAll('[data-act="undo"]').forEach((b) => {
    b.disabled = !state.data.history.can_undo;
  });
  document.querySelectorAll('[data-act="redo"]').forEach((b) => {
    b.disabled = !state.data.history.can_redo;
  });

  const nameBox = $('docName');
  nameBox.hidden = !hasDoc;
  $('docTitle').textContent = doc.name || '';
  $('docTitle').title = doc.path || '';
  $('dirtyDot').classList.toggle('hidden', !doc.dirty);

  $('app').classList.toggle('inspector-hidden', !hasDoc);
  renderZoom();
  renderPageIndicator(0);
}

/** 底部页码浮标。视口滚动时由 canvas.js 调用。 */
export function renderPageIndicator(index) {
  const chip = $('pageChip');
  if (!chip) return;
  const total = state.data ? state.data.pages.length : 0;
  chip.hidden = total === 0;
  if (total) {
    const current = Math.min(total, Math.max(1, index + 1));
    chip.textContent = T('page.indicator', { current, total });
  }
}

export function renderZoom() {
  $('zoomValue').textContent = `${Math.round(state.view.zoom * 100)}%`;
}

/* ---------- 页面 ---------- */

function buildPages() {
  const box = $('pages');
  box.innerHTML = '';
  for (const info of state.data.pages) {
    const section = document.createElement('section');
    section.className = 'page loading';
    section.dataset.page = String(info.index);

    const img = document.createElement('img');
    img.className = 'page-bg';
    img.alt = '';
    img.draggable = false;

    const objects = document.createElement('div');
    objects.className = 'objects';

    const overlay = document.createElement('canvas');
    overlay.className = 'overlay';

    const guides = document.createElement('canvas');
    guides.className = 'guides';

    const label = document.createElement('span');
    label.className = 'page-no';
    label.textContent = String(info.index + 1);

    section.append(img, objects, guides, overlay, label);
    if (info.locked > 0) {
      section.classList.add('locked');
      label.title = T('page.locked', { count: info.locked });
    }
    box.appendChild(section);
  }
}

export function layoutPages() {
  if (!state.data) return;
  const k = pxPerPt();
  for (const info of state.data.pages) {
    const el = pageEl(info.index);
    if (!el) continue;
    el.style.width = `${info.w * k}px`;
    el.style.height = `${info.h * k}px`;
    resizeOverlay(el, info);
  }
  positionObjects();
  document.dispatchEvent(new CustomEvent('layout:done'));
}

/** 只改已有节点的位置，不重建 DOM——缩放时用，避免图片反复重新解码。 */
export function positionObjects() {
  if (!state.data) return;
  const k = pxPerPt();
  for (const obj of state.data.objects) {
    const el = objectEl(obj.id);
    if (!el) continue;
    el.style.left = `${obj.x * k}px`;
    el.style.top = `${obj.y * k}px`;
    el.style.width = `${obj.w * k}px`;
    el.style.height = `${obj.h * k}px`;
  }
}

function resizeOverlay(el, info) {
  const canvas = el.querySelector('.overlay');
  if (!canvas) return;
  const dpr = state.view.dpr;
  const width = Math.max(1, Math.round(info.w * pxPerPt() * dpr));
  const height = Math.max(1, Math.round(info.h * pxPerPt() * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  canvas.style.width = '100%';
  canvas.style.height = '100%';
}

export function renderObjects(onlyIndex = null) {
  if (!state.data) return;
  const k = pxPerPt();
  for (const info of state.data.pages) {
    if (onlyIndex !== null && info.index !== onlyIndex) continue;
    const el = pageEl(info.index);
    if (!el) continue;
    const box = el.querySelector('.objects');
    if (!box) continue;
    box.innerHTML = '';
    for (const obj of objectsOf(info.index)) {
      box.appendChild(objectNode(obj, k));
    }
  }
}

function objectNode(obj, k) {
  const node = document.createElement('div');
  node.className = 'obj';
  node.dataset.id = obj.id;
  node.style.left = `${obj.x * k}px`;
  node.style.top = `${obj.y * k}px`;
  node.style.width = `${obj.w * k}px`;
  node.style.height = `${obj.h * k}px`;

  const img = document.createElement('img');
  img.src = obj.src;
  img.alt = '';
  img.draggable = false;
  node.appendChild(img);

  const handles = document.createElement('div');
  handles.className = 'handles';
  for (const corner of ['tl', 'tr', 'bl', 'br']) {
    const grip = document.createElement('i');
    grip.dataset.corner = corner;
    handles.appendChild(grip);
  }
  node.appendChild(handles);

  if (state.data.selection.includes(obj.id)) node.classList.add('selected');
  return node;
}

/* ---------- 选择 ---------- */

export function applySelection(ids = null) {
  const selected = new Set(ids || (state.data && state.data.selection) || []);
  document.querySelectorAll('.obj').forEach((el) => {
    el.classList.toggle('selected', selected.has(el.dataset.id));
  });
}

export function selectedIds() {
  return (state.data && state.data.selection) || [];
}

/* ---------- 属性面板 ---------- */

function renderInspector() {
  const body = $('inspectorBody');
  if (!body) return;
  const selection = state.data.selection || [];

  body.hidden = false;
  body.innerHTML = '';

  if (!selection.length) {
    const note = document.createElement('p');
    note.className = 'empty-hint';
    note.textContent = T('inspector.empty');
    body.append(note, actionRow(['paste']));
    return;
  }

  if (selection.length > 1) {
    const note = document.createElement('p');
    note.className = 'empty-hint';
    note.textContent = T('inspector.multi');
    body.append(note, actionRow(['delete']));
    return;
  }

  const obj = state.data.objects.find((o) => o.id === selection[0]);
  if (!obj) {
    body.hidden = true;
    return;
  }

  const thumb = document.createElement('img');
  thumb.className = 'thumb';
  thumb.src = obj.thumb;
  thumb.alt = '';
  body.appendChild(thumb);

  const list = document.createElement('dl');
  list.className = 'kv';
  const rows = [
    [T('inspector.page'), String(obj.page + 1)],
    [T('inspector.position'), `${obj.x.toFixed(1)}, ${obj.y.toFixed(1)}`],
    [T('inspector.size'), `${obj.w.toFixed(1)} × ${obj.h.toFixed(1)}`],
  ];
  for (const [key, value] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = key;
    const dd = document.createElement('dd');
    dd.textContent = value;
    list.append(dt, dd);
  }
  body.appendChild(list);
  body.appendChild(actionRow(['split', 'front', 'back', 'external', 'delete']));
}

const ACTIONS = {
  split: ['toolbar.split', 'btn sm'],
  front: ['toolbar.front', 'btn sm'],
  back: ['toolbar.back', 'btn sm'],
  external: ['inspector.external', 'btn sm'],
  delete: ['toolbar.delete', 'btn sm danger-ghost'],
  paste: ['edit.paste', 'btn sm'],
};

function actionRow(keys) {
  const row = document.createElement('div');
  row.className = 'inspector-actions';
  for (const key of keys) {
    const [label, className] = ACTIONS[key];
    const button = document.createElement('button');
    button.className = className;
    button.dataset.act = key;
    button.textContent = T(label);
    row.appendChild(button);
  }
  return row;
}

/* ---------- 供其它模块使用 ---------- */

export function setPageLoaded(index) {
  const el = pageEl(index);
  if (el) el.classList.remove('loading');
}

export function setPageImage(index, url) {
  const el = pageEl(index);
  if (!el) return;
  const img = el.querySelector('.page-bg');
  if (img) img.src = url;
}

export function clearPageImage(index) {
  const el = pageEl(index);
  if (!el) return;
  const img = el.querySelector('.page-bg');
  if (img) {
    img.removeAttribute('src');
    el.classList.add('loading');
  }
}

export function pageHeightInViewport(index) {
  const info = pageInfo(index);
  return info ? info.h * pxPerPt() : 0;
}
