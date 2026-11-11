/* 渲染：把后端快照铺到 DOM 上。
   前端不维护业务数据，快照变了就整体重绘；只有纯视图状态留在这边。 */

import { T } from './bridge.js';
import { accelFor, setBindings } from './keymap.js';
import { objectsOf, pxPerPt, state } from './state.js';

const $ = (id) => document.getElementById(id);

// 最近一次滚动到的页。快照落地时不能把页码重置成第 1 页。
let lastPageIndex = 0;

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
}

/* ---------- 主入口 ---------- */

// 图片 id 必须参与签名：外部编辑回填只换内容、不动几何，漏了它就重绘不出来。
function signature(objects) {
  return objects
    .map((o) => `${o.id}:${o.image}:${o.x},${o.y},${o.w},${o.h},${o.z},${o.page}`)
    .join('|');
}

export function apply(data) {
  if (!data) return;
  // 只认更新的版本：晚到的旧回包直接作废，不会把已经删掉的对象复活。
  if (typeof data.rev === 'number') {
    if (data.rev < state.rev) return;
    state.rev = data.rev;
  }
  if (state.view.gesture) {
    // 拖拽/缩放过程中不重建 DOM（会把正在拖的节点换掉），结束时统一补一次。
    state.stale = true;
    return;
  }
  const previous = state.data;
  const rebuilt = !previous || previous.doc.generation !== data.doc.generation;
  const changed = !previous || signature(previous.objects) !== signature(data.objects);
  const selectionChanged =
    !previous || previous.selection.join() !== data.selection.join();

  state.data = data;
  setBindings(data.keybindings);
  applyTheme(data.theme);
  if (data.language) document.documentElement.lang = data.language;
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
  applyShortcutHints();
}

function applyChrome() {
  const doc = state.data.doc;
  const hasDoc = doc.page_count > 0;

  $('empty').hidden = hasDoc;
  $('pages').hidden = !hasDoc;

  document.querySelectorAll('[data-act="save"]').forEach((b) => {
    b.disabled = !hasDoc || !doc.can_save;
  });
  document.querySelectorAll('[data-act="save-as"], [data-act="export"], [data-act="reload"]').forEach(
    (b) => {
      b.disabled = !hasDoc;
    }
  );
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

  const showInspector = hasDoc && Boolean(state.data.show_inspector);
  $('app').classList.toggle('inspector-hidden', !showInspector);
  const toggle = $('btnInspector');
  if (toggle) {
    toggle.disabled = !hasDoc;
    toggle.setAttribute('aria-pressed', showInspector ? 'true' : 'false');
  }

  renderZoom();
  renderPageIndicator(lastPageIndex);
}

/** 底部页码浮标 + 属性栏底部的页码。视口滚动时由 canvas.js 调用。 */
export function renderPageIndicator(index) {
  lastPageIndex = index;
  const total = state.data ? state.data.pages.length : 0;
  const text = total
    ? T('page.indicator', { current: Math.min(total, Math.max(1, index + 1)), total })
    : '';

  const chip = $('pageChip');
  if (chip) {
    chip.hidden = total === 0;
    if (total) chip.textContent = text;
  }

  const footer = $('inspectorPage');
  if (footer) footer.textContent = text;

  const jump = $('pageJump');
  if (jump) jump.max = String(Math.max(1, total));
}

export function renderZoom() {
  const input = $('zoomValue');
  if (!input) return;
  // 正在输入时不要覆盖用户敲的内容
  if (document.activeElement === input) return;
  input.value = `${Math.round(state.view.zoom * 100)}%`;
}

/* ---------- 语言切换后的动态文案 ---------- */

/** 页面角标上的「本页有 N 张旋转图片」。 */
function applyPageTitles() {
  if (!state.data) return;
  for (const info of state.data.pages) {
    if (!info.locked) continue;
    const label = document.querySelector(`.page[data-page="${info.index}"] .page-no`);
    if (label) label.title = T('page.locked', { count: info.locked });
  }
}

/**
 * 把用 T() 现算的文案全部重建一遍。
 *
 * 带 data-i18n 的静态节点由 applyStrings() 处理；属性栏按钮、页码浮标、分割条
 * 键位提示、页面角标都是渲染时现查表的，字符串表换了不会自己更新——不重建的话
 * 它们会一直停在上一种语言，切两次就成了「和当前语言相反」。
 */
export function refreshTexts() {
  if (!state.data) return;
  renderInspector();
  applyShortcutHints();
  renderPageIndicator(lastPageIndex);
  applyPageTitles();
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
  split: ['toolbar.split', 'btn sm', 'split'],
  front: ['toolbar.front', 'btn sm', 'front'],
  back: ['toolbar.back', 'btn sm', 'back'],
  external: ['inspector.external', 'btn sm', 'external'],
  delete: ['toolbar.delete', 'btn sm danger-ghost', 'delete'],
  paste: ['edit.paste', 'btn sm', 'paste'],
};

const SPLIT_ACTIONS = {
  'keep-cell': 'split_keep',
  'punch-cell': 'split_punch',
  'split-all': 'split_all',
  'split-cancel': 'split_cancel',
};

function shortcutTag(accel) {
  if (!accel) return null;
  const kbd = document.createElement('kbd');
  kbd.textContent = accel;
  return kbd;
}

function actionRow(keys) {
  const row = document.createElement('div');
  row.className = 'inspector-actions';
  for (const key of keys) {
    const [label, className, command] = ACTIONS[key];
    const button = document.createElement('button');
    button.className = className;
    button.dataset.act = key;
    button.textContent = T(label);
    const tag = shortcutTag(accelFor('global', command));
    if (tag) button.appendChild(tag);
    row.appendChild(button);
  }
  return row;
}

/** 分割工具条上的按键提示。键位可改，所以每次快照都重刷一遍。 */
export function applyShortcutHints() {
  document.querySelectorAll('#splitBar [data-act]').forEach((button) => {
    const kbd = button.querySelector('kbd');
    if (!kbd) return;
    const command = SPLIT_ACTIONS[button.dataset.act];
    const accel = command ? accelFor('split', command) : '';
    kbd.textContent = accel || '';
    kbd.hidden = !accel;
  });
}

/* ---------- 供其它模块使用 ---------- */
