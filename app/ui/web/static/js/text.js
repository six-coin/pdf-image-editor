/* 文本框：渲染、编辑、浮动工具栏。

   屏幕上的位置与 PDF 里的位置来自同一份排版数据——后端算出「第几行、基线在
   哪儿、每个字段从哪个 x 开始」，这里只负责照着画。所以不存在「屏幕换行、
   PDF 不换行」的偏差。

   工具栏钉在文本框左上角：选中就出现。编辑时改的是选区与整框样式，未编辑时
   改的是整框样式。编辑态换成 contenteditable，让浏览器自己排；提交时把 DOM
   重新序列化成若干「文字 + 字体」的段，交回后端。 */

import { call, T } from './bridge.js';
import { selectBox } from './controls.js';
import { mountFloat, placeFloat } from './floatbar.js';
import { apply, objectEl, pageEl, updateLiveTextSize } from './render.js';
import { pxPerPt, state } from './state.js';

const ZWSP = '\u200b';
const MIN_SIZE = 6;
const MAX_SIZE = 200;
const MIN_LINE_HEIGHT = 0.8;
const MAX_LINE_HEIGHT = 3;

let editing = null;
let bar = null; // { el, id, live, target }
// 「当前默认值」：上一个编辑过的文本框的样式。打开新文档时清空，用户看不见。
let currentDefault = null;

/* ---------- 小工具 ---------- */

function paletteHex(kind, key) {
  const palette = (state.data && state.data.palette) || {};
  const list = palette[kind] || [];
  const hit = list.find((item) => item.key === key);
  return hit ? hit.hex : '#000000';
}

function cssFont(key) {
  const fonts = (state.data && state.data.fonts) || [];
  const hit = fonts.find((item) => item.key === key);
  return hit ? hit.css : 'sans-serif';
}

function defaults() {
  const data = (state.data && state.data.defaults) || {};
  return {
    font: data.text_font || 'msyh',
    size: data.text_size_px || 14,
    color: data.text_color || 'blue',
    line_height: data.text_line_height || 1.15,
    width: ((data.text_width_mm || 40) * 72) / 25.4,
  };
}

/* ---------- 渲染 ---------- */

export function textNode(obj, k) {
  const node = document.createElement('div');
  node.className = 'obj text-box';
  node.dataset.id = obj.id;
  node.dataset.kind = 'text';
  node.style.left = `${obj.x * k}px`;
  node.style.top = `${obj.y * k}px`;
  node.style.width = `${obj.w * k}px`;
  node.style.height = `${obj.h * k}px`;
  node.style.color = obj.hex;

  const sizePx = obj.size * 0.75 * k;
  const lineHeight = obj.line_height * obj.size * 0.75 * k;
  (obj.lines || []).forEach((line, index) => {
    const row = document.createElement('div');
    row.className = 'text-line';
    row.style.top = `${index * lineHeight}px`;
    row.style.height = `${lineHeight}px`;
    row.style.lineHeight = `${lineHeight}px`;
    row.style.fontSize = `${sizePx}px`;
    for (const [text, font, x] of line.runs || []) {
      const span = document.createElement('span');
      span.textContent = text;
      span.style.left = `${x * k}px`;
      span.style.fontFamily = cssFont(font);
      row.appendChild(span);
    }
    node.appendChild(row);
  });

  const handles = document.createElement('div');
  handles.className = 'handles';
  // 文本框只能改宽度：左右各一个手柄，上下不给。
  for (const corner of ['w', 'e']) {
    const grip = document.createElement('i');
    grip.className = 'grip';
    grip.dataset.corner = corner;
    handles.appendChild(grip);
  }
  node.appendChild(handles);

  if ((state.data.selection || []).includes(obj.id)) node.classList.add('selected');
  return node;
}

/** 缩放时只改内部尺寸，不重建 DOM——否则每滚一下滚轮所有文字都要重新排版。 */
export function updateTextMetrics(node, obj, k) {
  const sizePx = obj.size * 0.75 * k;
  const lineHeight = obj.line_height * obj.size * 0.75 * k;
  const rows = node.querySelectorAll('.text-line');
  rows.forEach((row, index) => {
    row.style.top = `${index * lineHeight}px`;
    row.style.height = `${lineHeight}px`;
    row.style.lineHeight = `${lineHeight}px`;
    row.style.fontSize = `${sizePx}px`;
  });
  const lines = obj.lines || [];
  rows.forEach((row, index) => {
    const line = lines[index];
    if (!line) return;
    row.querySelectorAll('span').forEach((span, slot) => {
      const run = (line.runs || [])[slot];
      if (run) span.style.left = `${run[2] * k}px`;
    });
  });
}

/* ---------- 编辑 ---------- */

export function isEditing() {
  return Boolean(editing);
}

export function editingId() {
  return editing ? editing.id : null;
}

function runSpan(text, font) {
  const span = document.createElement('span');
  span.dataset.font = font;
  span.textContent = text;
  span.style.fontFamily = cssFont(font);
  return span;
}

function caretToEnd(editor) {
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  const selection = window.getSelection();
  if (!selection) return;
  selection.removeAllRanges();
  selection.addRange(range);
}

export async function beginEdit(obj) {
  if (!obj || obj.kind !== 'text') return;
  if (editing && editing.id === obj.id) return;
  await commitEdit();
  if (editing) return; // 等待期间又开了另一个，别抢

  const node = objectEl(obj.id);
  if (!node) return;
  const baseFont = (obj.runs && obj.runs.length && obj.runs[0][1]) || defaults().font;

  const editor = document.createElement('div');
  editor.className = 'text-editor';
  editor.contentEditable = 'true';
  editor.spellcheck = false;
  editor.style.fontFamily = cssFont(baseFont);
  editor.style.color = obj.hex;

  for (const [text, font] of obj.runs || []) {
    if (text) editor.appendChild(runSpan(text, font));
  }

  node.innerHTML = '';
  node.classList.add('editing');
  node.appendChild(editor);

  editing = {
    id: obj.id,
    obj,
    node,
    editor,
    page: obj.page,
    baseFont,
    height: obj.h,
    style: { size: obj.size, color: obj.color, line_height: obj.line_height },
  };
  // 「当前默认值」跟着这个框走：下一个新建的文本框就用这一套。
  currentDefault = {
    font: baseFont,
    size: obj.size,
    color: obj.color,
    line_height: obj.line_height,
    width: obj.w,
  };

  applyEditorMetrics();
  editor.focus();
  caretToEnd(editor);
  syncTextBar();
  editor.addEventListener('keydown', onEditorKey);
  editor.addEventListener('input', scheduleEditorHeight);
}

function applyEditorMetrics() {
  if (!editing) return;
  const k = pxPerPt();
  const { editor, style } = editing;
  editor.style.fontSize = `${style.size * 0.75 * k}px`;
  editor.style.lineHeight = `${style.line_height * style.size * 0.75 * k}px`;
  editor.style.color = paletteHex('text', style.color);
  syncEditorHeight();
}

/**
 * 让框的高度跟着编辑内容走。
 *
 * 编辑层是 contenteditable，浏览器自己排；框的高度却还停在上一次提交时的值，
 * 多敲两行字就溢出到框外。这里临时把编辑层改成高度自适应，量一次内容高度，
 * 再写回对象节点。行尾回车在浏览器里不占行盒，但后端把它算作一行，这里补上，
 * 编辑时和保存后的高度才一致。
 */
function syncEditorHeight() {
  if (!editing) return;
  const { editor, node, style } = editing;
  const k = pxPerPt();
  const lineHeight = style.line_height * style.size * 0.75 * k;
  const previousHeight = editor.style.height;
  const previousBottom = editor.style.bottom;
  editor.style.height = 'auto';
  editor.style.bottom = 'auto';
  let content = editor.scrollHeight;
  editor.style.height = previousHeight;
  editor.style.bottom = previousBottom;
  if (editor.textContent.endsWith('\n')) content += lineHeight;
  content = Math.max(lineHeight, content);
  node.style.height = `${content}px`;
  editing.height = content / k;
  updateLiveTextSize(editing.id, editing.obj.w, editing.height);
  placeBar();
}

function onEditorKey(event) {
  if (event.key === 'Enter' && !event.ctrlKey && !event.metaKey) {
    // 保持 DOM 扁平：回车插的是真正的换行符，不是 <div> 套 <div>。
    event.preventDefault();
    insertPlainText('\n');
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    commitEdit();
    return;
  }
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    commitEdit();
  }
}

function insertPlainText(text) {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) return;
  const range = selection.getRangeAt(0);
  range.deleteContents();
  const node = document.createTextNode(text);
  range.insertNode(node);
  range.setStartAfter(node);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
  scheduleEditorHeight();
}

let heightFrame = 0;

/** 输入很密，按帧合并一次高度测量，别每个字符都强制回流。 */
function scheduleEditorHeight() {
  if (heightFrame) return;
  heightFrame = window.requestAnimationFrame(() => {
    heightFrame = 0;
    syncEditorHeight();
  });
}

/** 把 DOM 序列化成「文字 + 字体」的段。零宽占位符要剔掉。 */
function serialize(root) {
  const runs = [];
  const add = (text, font) => {
    if (!text) return;
    const last = runs[runs.length - 1];
    if (last && last[1] === font) last[0] += text;
    else runs.push([text, font]);
  };
  const walk = (node, font) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) {
        add(child.nodeValue.split(ZWSP).join(''), font);
        continue;
      }
      if (child.nodeType !== 1) continue;
      if (child.tagName === 'BR') {
        add('\n', font);
        continue;
      }
      const own = child.dataset && child.dataset.font ? child.dataset.font : font;
      walk(child, own);
    }
  };
  walk(root, editing ? editing.baseFont : defaults().font);
  return runs;
}

export async function commitEdit() {
  if (!editing) return;
  const current = editing;
  const runs = serialize(current.editor);
  editing = null;

  // 进去看一眼又出来不该留下一条撤销记录。空框（runs 为空）仍然要走一次，
  // 让后端把它删掉。
  const sameRuns = JSON.stringify(runs) === JSON.stringify(current.obj.runs || []);
  const sameStyle =
    current.style.size === current.obj.size &&
    current.style.color === current.obj.color &&
    current.style.line_height === current.obj.line_height;
  if (runs.length && sameRuns && sameStyle) {
    syncTextBar();
    return;
  }

  const snapshot = await call('update_text', current.id, runs, {
    size: current.style.size,
    color: current.style.color,
    line_height: current.style.line_height,
  });
  if (snapshot) apply(snapshot);
}

/* ---------- 浮动工具栏 ---------- */

function selectedText() {
  if (!state.data) return null;
  const ids = state.data.selection || [];
  if (ids.length !== 1) return null;
  const obj = state.data.objects.find((item) => item.id === ids[0]);
  return obj && obj.kind === 'text' ? obj : null;
}

/** 光标/选区落在哪个字体段里。工具栏显示它，而不是永远显示第一段的字体。 */
function currentFont() {
  if (!editing) return defaults().font;
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) return editing.baseFont;
  const range = selection.getRangeAt(0);
  if (!editing.editor.contains(range.commonAncestorContainer)) return editing.baseFont;
  let node = range.startContainer;
  if (node.nodeType === 3) node = node.parentElement;
  const hit = node && node.closest ? node.closest('[data-font]') : null;
  if (hit && editing.editor.contains(hit)) return hit.dataset.font;
  return editing.baseFont;
}

/** 工具栏现在该跟着谁：编辑中的框优先，否则是唯一选中的文本框。 */
function barTarget() {
  if (editing) {
    return {
      id: editing.id,
      obj: editing.obj,
      live: true,
      font: currentFont(),
      style: editing.style,
    };
  }
  const obj = selectedText();
  if (!obj) return null;
  return {
    id: obj.id,
    obj,
    live: false,
    font: (obj.runs && obj.runs[0] && obj.runs[0][1]) || defaults().font,
    style: { size: obj.size, color: obj.color, line_height: obj.line_height },
  };
}

function hideBar() {
  if (bar) {
    bar.el.remove();
    bar = null;
  }
}

function placeBar() {
  if (!bar || !bar.target) return;
  // 编辑中框的高度是随内容实时变的，不能再用快照里的旧 h。
  const obj = bar.target.obj;
  const height = bar.target.live && editing ? editing.height : obj.h;
  placeFloat(bar.el, { page: obj.page, x: obj.x, y: obj.y, w: obj.w, h: height });
}

function tapButton(label, title, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'step';
  button.textContent = label;
  if (title) button.title = title;
  // mousedown 不抢焦点：否则点一下工具条，编辑框里的选区就没了。
  button.addEventListener('mousedown', (event) => event.preventDefault());
  button.addEventListener('click', onClick);
  return button;
}

function numberInput(value, min, max, step, onCommit) {
  const input = document.createElement('input');
  input.type = 'number';
  input.className = 'num';
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(value);
  input.addEventListener('mousedown', (event) => event.stopPropagation());
  const commit = () => {
    const parsed = Number(input.value);
    input.value = String(onCommit(Number.isFinite(parsed) ? parsed : null));
  };
  input.addEventListener('change', commit);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      commit();
      input.blur();
    }
  });
  return input;
}

function buildBar(target) {
  const page = pageEl(target.obj.page);
  if (!page) return;

  const el = document.createElement('div');
  el.className = 'float-bar';
  el.dataset.role = 'text-bar';
  el.addEventListener('mousedown', (event) => event.preventDefault());

  const fonts = ((state.data && state.data.fonts) || []).map((font) => ({
    value: font.key,
    label: T(`font.${font.key}`),
  }));
  // 工具条会跨多次快照复用；回调里不能再用 buildBar 时捕获的旧对象，
  // 否则改完文字再改字体/字号，会把旧内容一起写回去。
  const liveTarget = () => (bar && bar.id === target.id ? bar.target : target);
  const picker = selectBox(fonts, target.font, (value) => {
    const current = liveTarget();
    if (!current.live) {
      applyFontToBox(current.obj, value);
      return;
    }
    // 选区不在编辑框里时 applyFont 会拒绝，下拉框要退回到光标真实的字体，
    // 否则它会停在一个其实没生效的选项上。
    if (!applyFont(value) && bar && bar.picker) bar.picker.setValue(currentFont());
  });
  picker.addEventListener('mousedown', (event) => event.stopPropagation());
  el.appendChild(picker);

  // 字号：一点一点调，整数。
  const sizeInput = numberInput(target.style.size, MIN_SIZE, MAX_SIZE, 1, (value) => {
    const current = liveTarget();
    return setSize(current, value === null ? current.style.size : value);
  });
  const minus = tapButton('−', T('text.size'), () => {
    const current = liveTarget();
    sizeInput.value = String(setSize(current, current.style.size - 1));
  });
  const plus = tapButton('+', T('text.size'), () => {
    const current = liveTarget();
    sizeInput.value = String(setSize(current, current.style.size + 1));
  });
  const sizeBox = document.createElement('div');
  sizeBox.style.display = 'flex';
  sizeBox.style.alignItems = 'center';
  sizeBox.style.gap = '2px';
  sizeBox.append(minus, sizeInput, plus);
  el.appendChild(sizeBox);

  // 行高：字号倍数，允许两位小数。
  const lineInput = numberInput(
    target.style.line_height,
    MIN_LINE_HEIGHT,
    MAX_LINE_HEIGHT,
    0.05,
    (value) => {
      const current = liveTarget();
      return setLineHeight(current, value === null ? current.style.line_height : value);
    }
  );
  lineInput.title = T('text.line_height');
  lineInput.classList.add('line-height');
  el.appendChild(lineInput);

  const sep = document.createElement('span');
  sep.className = 'sep';
  el.appendChild(sep);

  for (const color of ((state.data && state.data.palette) || {}).text || []) {
    const swatch = document.createElement('button');
    swatch.type = 'button';
    swatch.className = 'swatch' + (color.key === target.style.color ? ' active' : '');
    swatch.style.background = color.hex;
    swatch.dataset.color = color.key;
    swatch.title = T(`color.${color.key}`);
    swatch.addEventListener('mousedown', (event) => event.preventDefault());
    swatch.addEventListener('click', () => setColor(liveTarget(), color.key));
    el.appendChild(swatch);
  }

  mountFloat(el);
  bar = { el, id: target.id, live: target.live, target, picker, sizeInput, lineInput };
  placeBar();
}

export function syncTextBar() {
  const target = barTarget();
  if (!target) {
    hideBar();
    return;
  }
  if (bar && bar.id === target.id && bar.live === target.live) {
    bar.target = target;
    if (bar.picker && bar.picker.dataset.value !== target.font) bar.picker.setValue(target.font);
    // 撤销/重做或外部改动会换掉样式；输入框没在编辑时跟着回填，别停在旧值上。
    if (bar.sizeInput && document.activeElement !== bar.sizeInput) {
      bar.sizeInput.value = String(target.style.size);
    }
    if (bar.lineInput && document.activeElement !== bar.lineInput) {
      bar.lineInput.value = String(Number(target.style.line_height.toFixed(2)));
    }
    bar.el.querySelectorAll('.swatch').forEach((node) => {
      node.classList.toggle('active', node.dataset.color === target.style.color);
    });
    placeBar();
    return;
  }
  hideBar();
  buildBar(target);
}

/* ---------- 改样式 ---------- */

function setSize(target, value) {
  const next = Math.min(MAX_SIZE, Math.max(MIN_SIZE, Math.round(Number(value) || 0)));
  target.style.size = next;
  if (target.live) applyEditorMetrics();
  else applyStyleToBox(target.obj, { size: next });
  return next;
}

function setLineHeight(target, value) {
  const raw = Number(value);
  if (!Number.isFinite(raw)) return Number(target.style.line_height.toFixed(2));
  const next = Math.min(MAX_LINE_HEIGHT, Math.max(MIN_LINE_HEIGHT, raw));
  target.style.line_height = Math.round(next * 100) / 100;
  if (target.live) applyEditorMetrics();
  else applyStyleToBox(target.obj, { line_height: target.style.line_height });
  return Number(target.style.line_height.toFixed(2));
}

function setColor(target, key) {
  target.style.color = key;
  if (target.live) {
    applyEditorMetrics();
  } else {
    applyStyleToBox(target.obj, { color: key });
  }
  if (bar) {
    bar.el.querySelectorAll('.swatch').forEach((node) => {
      node.classList.toggle('active', node.dataset.color === key);
    });
  }
}

async function applyStyleToBox(obj, patch) {
  const snapshot = await call('update_text', obj.id, obj.runs, {
    size: patch.size ?? obj.size,
    color: patch.color ?? obj.color,
    line_height: patch.line_height ?? obj.line_height,
  });
  if (snapshot) apply(snapshot);
}

async function applyFontToBox(obj, key) {
  const runs = (obj.runs || []).map(([text]) => [text, key]);
  const snapshot = await call('update_text', obj.id, runs, {
    size: obj.size,
    color: obj.color,
    line_height: obj.line_height,
  });
  if (snapshot) apply(snapshot);
}

/** 给选区（或光标后面要敲的字）换字体。返回是否真的改了。 */
function applyFont(key) {
  if (!editing) return false;
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) return false;
  const range = selection.getRangeAt(0);
  if (!editing.editor.contains(range.commonAncestorContainer)) return false;

  if (range.collapsed) {
    // 光标塌着：塞一个零宽占位，后面敲的字就继承这个字体。
    const span = runSpan(ZWSP, key);
    range.insertNode(span);
    const next = document.createRange();
    next.setStart(span.firstChild, 1);
    next.collapse(true);
    selection.removeAllRanges();
    selection.addRange(next);
    return true;
  }

  const fragment = range.extractContents();
  const wrapper = document.createElement('span');
  wrapper.dataset.font = key;
  wrapper.style.fontFamily = cssFont(key);
  wrapper.appendChild(fragment);
  // 选区里原有的 run 还带着旧字体的 data-font 与 font-family。只包一层新
  // span 不够：serialize 取的是最内层的 data-font，里面的旧值会把新字体盖掉。
  wrapper.querySelectorAll('span').forEach((node) => {
    node.dataset.font = key;
    node.style.fontFamily = cssFont(key);
  });
  range.insertNode(wrapper);

  const next = document.createRange();
  next.selectNodeContents(wrapper);
  selection.removeAllRanges();
  selection.addRange(next);
  return true;
}

/* ---------- 对外动作 ---------- */

export function resetTextDefaults() {
  currentDefault = null;
}

export async function createTextAt(pageIndex, x, y) {
  await commitEdit();
  const style = currentDefault || defaults();
  const snapshot = await call('create_text', pageIndex, x, y, style);
  if (!snapshot) return;
  apply(snapshot);
  const obj = snapshot.created
    ? snapshot.objects.find((item) => item.id === snapshot.created)
    : null;
  if (obj) beginEdit(obj);
}

/** 新建一个文本框，落点用最后一次鼠标位置（不在页面上就取当前页左上角）。 */
export async function createTextAtPointer() {
  const pointer = state.view.pointer;
  if (pointer && typeof pointer.page === 'number') {
    await createTextAt(pointer.page, pointer.x, pointer.y);
    return;
  }
  const { currentPage } = await import('./canvas.js');
  const page = currentPage();
  const info = state.data && state.data.pages[page];
  await createTextAt(page, 40, info ? Math.min(60, info.h / 4) : 40);
}

export function bindText() {
  // 点了框外面就提交：比监听 blur 可靠——点工具条、拖滚动条都不该结束编辑。
  document.addEventListener(
    'pointerdown',
    (event) => {
      if (!editing) return;
      if (editing.node.contains(event.target)) return;
      if (bar && bar.el.contains(event.target)) return;
      // 这一下只负责结束编辑。拦的只是画布上的那一下：否则「文本模式点空白建新框」
      // 会跟着触发，点一下空白就多出一个空文本框。左栏、顶栏的按钮不在画布里，
      // 不能被拦——否则编辑时点模式按钮会连切换都切不了。
      if (event.target.closest && event.target.closest('#viewport')) {
        event.stopPropagation();
      }
      commitEdit();
    },
    true
  );

  document.addEventListener('selection:changed', syncTextBar);

  // 光标在混排文字里移动时，工具栏的字体要跟着走，不能一直停在第一段的字体上。
  document.addEventListener('selectionchange', () => {
    if (!editing || !bar || !bar.picker) return;
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!editing.editor.contains(range.commonAncestorContainer)) return;
    const font = currentFont();
    if (bar.picker.dataset.value !== font) bar.picker.setValue(font);
  });

  // 滚动、缩放窗口时工具栏要跟着对象走：它是 fixed 的，不会自己动。
  const viewport = document.getElementById('viewport');
  if (viewport) viewport.addEventListener('scroll', placeBar, { passive: true });
  window.addEventListener('resize', placeBar);

  document.addEventListener('layout:done', () => {
    if (editing) {
      const node = objectEl(editing.id);
      if (node) {
        editing.node = node;
        const editor = node.querySelector('.text-editor');
        if (editor) editing.editor = editor;
      }
      // 缩放会同时改页面和对象尺寸，编辑层的字号与行高必须跟着重算，
      // 否则字还是旧的 px、框已经是新的 pt，看着就错位了。
      applyEditorMetrics();
    }
    placeBar();
  });

  document.addEventListener('pages:rebuilt', () => {
    resetTextDefaults();
    editing = null;
    hideBar();
  });
}
