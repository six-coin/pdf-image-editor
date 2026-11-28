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
import { MODE_SELECT, setMode } from './modes.js';
import { apply, applySelection, objectEl, pageEl, updateLiveTextSize } from './render.js';
import { pxPerPt, state } from './state.js';

const ZWSP = '\u200b';
const MIN_SIZE = 6;
const MAX_SIZE = 200;
const MIN_LINE_HEIGHT = 0.8;
const MAX_LINE_HEIGHT = 3;

// contenteditable 里的块级元素：粘贴、拖放带进来的 <div> / <p> 会把换行藏在
// 元素边界上，textContent 里看不到。序列化和高度测量都必须把它们当换行。
const BLOCK_TAGS = new Set([
  'ADDRESS',
  'ARTICLE',
  'ASIDE',
  'BLOCKQUOTE',
  'DD',
  'DIV',
  'DL',
  'DT',
  'FIGCAPTION',
  'FIGURE',
  'FOOTER',
  'FORM',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'HEADER',
  'LI',
  'MAIN',
  'NAV',
  'OL',
  'P',
  'PRE',
  'SECTION',
  'TABLE',
  'TR',
  'UL',
]);

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
    width: ((data.text_width_mm || 45) * 72) / 25.4,
  };
}

/** 文本框第一段的字体；没有段时用新建默认值。 */
function boxFont(obj) {
  return (obj.runs && obj.runs[0] && obj.runs[0][1]) || defaults().font;
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
  const last = editor.lastChild;
  // 末尾哨兵只是为了撑出空行，光标应该停在哨兵前面，而不是后面。
  // 停在后面时再按回车，换行会插到哨兵之后，哨兵就跑到文档中间去了。
  if (last && last.nodeType === 1 && last.dataset && last.dataset.eol === '1') {
    range.setStartBefore(last);
    range.collapse(true);
  } else {
    range.selectNodeContents(editor);
    range.collapse(false);
  }
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
  composing = false;

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
  // 粘贴、拖放一律走纯文本：contenteditable 默认会把源文档的字体、颜色、
  // 甚至 <div> 结构一起搬进来，提交时字体对不上、换行还会丢。
  editor.addEventListener('paste', onEditorPaste);
  editor.addEventListener('drop', onEditorDrop);
  editor.addEventListener('compositionstart', () => {
    composing = true;
  });
  editor.addEventListener('compositionend', () => {
    composing = false;
    scheduleEditorHeight();
  });
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
 * 再写回对象节点。
 *
 * 末尾的回车在浏览器里不占行盒（块末尾的换行会被吃掉），后端却把它算作一行：
 * 补一个零宽哨兵把那个空行撑出来，既让光标有地方落，也让两边的高度一致。
 */
function syncEditorHeight() {
  if (!editing) return;
  const { editor, node, style } = editing;
  const k = pxPerPt();
  const lineHeight = style.line_height * style.size * 0.75 * k;
  ensureEolLine();
  const previousHeight = editor.style.height;
  const previousBottom = editor.style.bottom;
  editor.style.height = 'auto';
  editor.style.bottom = 'auto';
  const content = Math.max(lineHeight, editor.scrollHeight);
  editor.style.height = previousHeight;
  editor.style.bottom = previousBottom;
  node.style.height = `${content}px`;
  editing.height = content / k;
  updateLiveTextSize(editing.id, editing.obj.w, editing.height);
  placeBar();
}

/** 文字以换行结尾时，在末尾放一个零宽哨兵，让最后的空行真的占一行。 */
function ensureEolLine() {
  // 输入法组字期间不要动 DOM：在候选词旁边插节点会把组字打断。
  if (!editing || composing) return;
  const { editor } = editing;
  const sentinels = [...editor.querySelectorAll('[data-eol="1"]')];
  let last = editor.lastChild;

  if (editorText(editor).endsWith('\n')) {
    // 浏览器有时会在末尾补一个 <br> 撑行。前面已经有真正的 \n 时它只是
    // 占位，留着会让高度多出一行；如果它是唯一的换行，就换成文本 \n，
    // 后续的删除逻辑只认文本换行。
    while (last && last.nodeType === 1 && last.tagName === 'BR') {
      last.remove();
      if (!editorText(editor).endsWith('\n')) {
        editor.appendChild(document.createTextNode('\n'));
        break;
      }
      last = editor.lastChild;
    }
    const sentinel = Boolean(
      last && last.nodeType === 1 && last.dataset && last.dataset.eol === '1'
    );
    if (sentinel) {
      // 哨兵只能有一个，而且必须在末尾；编辑过程中可能被插到中间去。
      sentinels.forEach((node) => {
        if (node !== last) node.remove();
      });
      return;
    }
    sentinels.forEach((node) => node.remove());
    const span = document.createElement('span');
    span.dataset.eol = '1';
    span.textContent = ZWSP;
    editor.appendChild(span);
    return;
  }
  if (!sentinels.length) return;
  // 光标可能正停在哨兵里，先挪到末尾再拆，别把光标一起删掉。
  const selection = window.getSelection();
  if (
    selection &&
    selection.rangeCount &&
    sentinels.some((node) => node.contains(selection.getRangeAt(0).startContainer))
  ) {
    caretToEnd(editor);
  }
  sentinels.forEach((node) => node.remove());
}

function onEditorKey(event) {
  // 输入法组字时的回车/退格属于输入法：拦下来会把候选词直接吃掉。
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === 'Backspace' && dropTrailingLine()) {
    event.preventDefault();
    return;
  }
  if (event.key === 'Enter' && !event.ctrlKey && !event.metaKey) {
    // 保持 DOM 扁平：回车插的是真正的换行符，不是 <div> 套 <div>。
    event.preventDefault();
    insertPlainText('\n');
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    exitEditToSelect();
    return;
  }
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    commitEdit();
  }
}

/**
 * 光标在末尾空行时，浏览器不会把上一行的换行符当成可删字符：它要么去删
 * 上一行最后一个字，要么删掉零宽哨兵再补一个 <br>，于是「往回删」看起来
 * 永远删不掉最后一行。这里直接把最后一个换行符从 DOM 里摘掉。
 *
 * 只处理「光标在文档末尾、前面是换行」这一种情况；其它位置的换行删除交给
 * 浏览器，它处理得比我们准。
 */
function dropTrailingLine() {
  if (!editing) return false;
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) return false;
  const range = selection.getRangeAt(0);
  if (!range.collapsed || !editing.editor.contains(range.commonAncestorContainer)) return false;
  if (!editorText(editing.editor).endsWith('\n')) return false;

  const before = document.createRange();
  before.selectNodeContents(editing.editor);
  before.setEnd(range.startContainer, range.startOffset);
  const after = document.createRange();
  after.selectNodeContents(editing.editor);
  after.setStart(range.endContainer, range.endOffset);
  const read = (piece) =>
    collectRuns(piece.cloneContents(), editing.baseFont)
      .map(([text]) => text)
      .join('');
  if (read(after) !== '' || !read(before).endsWith('\n')) return false;

  const { editor } = editing;
  // 找最后一个含换行的文本节点。哨兵里的零宽字符不算。
  const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
  let target = null;
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.parentElement && node.parentElement.closest('[data-eol="1"]')) continue;
    if (node.nodeValue.includes('\n')) target = node;
  }
  if (!target) return false;

  const value = target.nodeValue;
  const index = value.lastIndexOf('\n');
  target.nodeValue = value.slice(0, index) + value.slice(index + 1);
  if (!target.nodeValue) target.remove();

  // 哨兵和浏览器补在末尾的 <br> 都不是用户敲的换行，一起清掉。
  editor.querySelectorAll('[data-eol="1"]').forEach((node) => node.remove());
  while (editor.lastChild && editor.lastChild.nodeType === 1 && editor.lastChild.tagName === 'BR') {
    editor.lastChild.remove();
  }
  caretToEnd(editor);
  scheduleEditorHeight();
  return true;
}

/** 粘贴、拖放进来的文本一律当纯文本：不要字体、颜色、字号，也不要块级结构。 */
function plainText(raw) {
  return String(raw || '')
    .replace(/\r\n?/g, '\n')
    .replace(/\u00a0/g, ' ')
    .replace(/\u200b/g, '')
    .replace(/\t/g, '    ')
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '');
}

function onEditorPaste(event) {
  const data = event.clipboardData;
  if (!data) return;
  event.preventDefault();
  event.stopPropagation();
  insertPlainText(plainText(data.getData('text/plain')));
}

function onEditorDrop(event) {
  const data = event.dataTransfer;
  const raw = data ? data.getData('text/plain') : '';
  if (!raw) return; // 文件、图片交给画布
  event.preventDefault();
  event.stopPropagation();
  if (document.caretRangeFromPoint) {
    const point = document.caretRangeFromPoint(event.clientX, event.clientY);
    if (point && editing && editing.editor.contains(point.startContainer)) {
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(point);
    }
  }
  insertPlainText(plainText(raw));
}

/** 光标在编辑层里就返回当前 range；不在就补到末尾——点过工具条也不能让回车失效。 */
function editorRange() {
  if (!editing) return null;
  const selection = window.getSelection();
  if (selection && selection.rangeCount) {
    const range = selection.getRangeAt(0);
    if (editing.editor.contains(range.commonAncestorContainer)) return range;
  }
  caretToEnd(editing.editor);
  const again = window.getSelection();
  return again && again.rangeCount ? again.getRangeAt(0) : null;
}

function insertPlainText(text) {
  if (!text) return;
  const range = editorRange();
  if (!range) return;
  range.deleteContents();
  const node = document.createTextNode(text);
  range.insertNode(node);
  range.setStartAfter(node);
  range.collapse(true);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  scheduleEditorHeight();
}

let heightFrame = 0;
// 输入法组字中：这期间不改 DOM，等 compositionend 再量高度。
let composing = false;

/** 输入很密，按帧合并一次高度测量，别每个字符都强制回流。 */
function scheduleEditorHeight() {
  if (heightFrame) return;
  heightFrame = window.requestAnimationFrame(() => {
    heightFrame = 0;
    syncEditorHeight();
  });
}

/**
 * 把 DOM 拆成「文字 + 字体」的段。零宽占位符要剔掉。
 *
 * 块级元素的边界也是换行：粘贴进来的 <div>a</div><div>b</div> 在浏览器里是
 * 两行，textContent 里却连在一起。不补这个换行，提交时两行会粘成一行。
 */
function collectRuns(root, baseFont) {
  const runs = [];
  let pendingBreak = false;
  const add = (text, font) => {
    if (!text) return;
    const last = runs[runs.length - 1];
    if (last && last[1] === font) last[0] += text;
    else runs.push([text, font]);
  };
  const atLineStart = () => {
    const last = runs[runs.length - 1];
    return !last || last[0].endsWith('\n');
  };
  const emit = (text, font) => {
    if (!text) return;
    // 刚走完一个块：它后面自带一次换行，等下一段内容出现时再补，免得留下
    // 一个多余的行尾换行（块末尾的换行浏览器是不画的）。
    if (pendingBreak) {
      pendingBreak = false;
      if (!atLineStart()) add('\n', font);
    }
    add(text, font);
  };
  const walk = (node, font) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) {
        emit(child.nodeValue.split(ZWSP).join(''), font);
        continue;
      }
      if (child.nodeType !== 1) continue;
      if (child.tagName === 'BR') {
        // 浏览器会在块末尾补 <br> 撑行；前面已经是换行时它只是占位，
        // 不是用户又敲了一行。真换行由我们插入的 \n 文本节点负责。
        if (!atLineStart()) emit('\n', font);
        continue;
      }
      const own = child.dataset && child.dataset.font ? child.dataset.font : font;
      const block = BLOCK_TAGS.has(child.tagName);
      if (block && !atLineStart()) add('\n', font);
      walk(child, own);
      if (block) pendingBreak = true;
    }
  };
  walk(root, baseFont);
  return runs;
}

/** 编辑层里真正的文字（含块级边界与 <br> 的换行），高度与「是不是默认文本」都按它算。 */
function editorText(root) {
  return collectRuns(root, '').map(([text]) => text).join('');
}

function serialize(root) {
  return collectRuns(root, editing ? editing.baseFont : defaults().font);
}

/** 编辑完还是设置里的默认文本：这个框只是占位，删掉。 */
function defaultText() {
  return String((state.data && state.data.defaults && state.data.defaults.text_default) || '');
}

export async function commitEdit() {
  if (!editing) return;
  const current = editing;
  const runs = serialize(current.editor);
  editing = null;

  // 内容还是默认文本：这个框没被真正编辑过，交回后端删掉。
  const preset = defaultText();
  const joined = runs.map(([text]) => text).join('');
  const placeholder = Boolean(preset.trim()) && joined.trim() === preset.trim();

  // 进去看一眼又出来不该留下一条撤销记录。空框（runs 为空）仍然要走一次，
  // 让后端把它删掉。
  const sameRuns = JSON.stringify(runs) === JSON.stringify(current.obj.runs || []);
  const sameStyle =
    current.style.size === current.obj.size &&
    current.style.color === current.obj.color &&
    current.style.line_height === current.obj.line_height;
  if (runs.length && sameRuns && sameStyle && !placeholder) {
    // 内容没变，但编辑层已经拆了：必须把普通文本节点装回去，否则页面会停在
    // 「看着还在编辑、其实 editing 已经是 null」的状态，缩放时字号也不跟着变。
    restoreTextNode(current);
    syncTextBar();
    return;
  }

  const snapshot = await call(
    'update_text',
    current.id,
    runs,
    {
      size: current.style.size,
      color: current.style.color,
      line_height: current.style.line_height,
    },
    true
  );
  if (snapshot) apply(snapshot);
  else restoreTextNode(current);
}

/**
 * Esc：结束编辑 → 切到选择模式 → 选中这个框。
 *
 * 直接提交再取消选中会让人愣一下：想接着拖这个框，还得再点一次。切到选择模式
 * 之后框就带着手柄，方向键、拖动立刻可用。
 */
async function exitEditToSelect() {
  const current = editing;
  if (!current) return;
  const id = current.id;
  await commitEdit();
  setMode(MODE_SELECT);
  if (!state.data) return;
  // 内容还是默认文本时框已经被删掉了，没什么可选。
  const alive = (state.data.objects || []).some((obj) => obj.id === id);
  if (!alive) return;
  const snapshot = await call('select', [id]);
  if (snapshot) apply(snapshot);
}

/** 把编辑层换回按模型渲染的普通文本框。 */
function restoreTextNode(current) {
  if (!current.node.isConnected) return;
  current.node.replaceWith(textNode(current.obj, pxPerPt()));
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
    font: boxFont(obj),
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
  const picker = selectBox(fonts, target.font, async (value) => {
    const current = liveTarget();
    try {
      const changed = current.live
        ? await applyFont(value)
        : await applyFontToBox(current.obj, value);
      // 一个字符都换不了时，把下拉框退回真实字体，别停在一个没生效的选项上。
      if (!changed && bar && bar.picker) {
        bar.picker.setValue(current.live ? currentFont() : boxFont(current.obj));
      }
    } catch (error) {
      if (bar && bar.picker) {
        bar.picker.setValue(current.live ? currentFont() : boxFont(current.obj));
      }
    }
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
  const snapshot = await call('set_text_font', obj.id, key);
  if (snapshot) apply(snapshot);
  return Boolean(snapshot && snapshot.changed);
}

/** 给选区（或光标后面要敲的字）换字体。返回是否真的改了。 */
async function applyFont(key) {
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

  // 选区里的字符逐个问后端有没有目标字体的字形：能换的换，缺字形的保留
  // 原字体。不能直接给整段套新字体——MuPDF 保存时会静默回退，屏幕和落盘
  // 的字形就对不上了。
  const startContainer = range.startContainer;
  const startOffset = range.startOffset;
  const endContainer = range.endContainer;
  const endOffset = range.endOffset;
  const runs = collectRuns(range.cloneContents(), editing.baseFont);
  if (!runs.length) return false;

  const result = await call('retarget_runs', key, runs);
  if (!result || !result.ok) return false;
  const retargeted = (result.runs || []).filter(([text]) => text);
  if (!retargeted.length) return false;
  // 一个字符都换不了（比如整段中文选 Times）：不动 DOM，让工具栏退回原字体。
  if (!retargeted.some(([, family]) => family === result.font)) return false;

  // 等回包期间选区或编辑框可能已经变了。
  if (!editing || !editing.editor.isConnected) return false;
  const now = window.getSelection();
  if (!now || !now.rangeCount) return false;
  const current = now.getRangeAt(0);
  if (
    current.startContainer !== startContainer ||
    current.startOffset !== startOffset ||
    current.endContainer !== endContainer ||
    current.endOffset !== endOffset
  ) {
    return false;
  }

  current.deleteContents();
  const holder = document.createDocumentFragment();
  for (const [text, family] of retargeted) holder.appendChild(runSpan(text, family));
  const first = holder.firstChild;
  const last = holder.lastChild;
  current.insertNode(holder);

  if (first && last) {
    const next = document.createRange();
    next.setStartBefore(first);
    next.setEndAfter(last);
    now.removeAllRanges();
    now.addRange(next);
  }
  scheduleEditorHeight();
  return true;
}

/* ---------- 对外动作 ---------- */

export function resetTextDefaults() {
  currentDefault = null;
}

/** 新建一个文本框，落点由调用方给（文本模式下单击空白）。 */
export async function createTextAt(pageIndex, x, y, { blank = false } = {}) {
  await commitEdit();
  const style = currentDefault || defaults();
  const preset = (state.data && state.data.defaults && state.data.defaults.text_default) || '';
  const text = blank ? '' : String(preset);
  const snapshot = await call('create_text', pageIndex, x, y, style, text);
  if (!snapshot) return;
  apply(snapshot);
  const obj = snapshot.created
    ? snapshot.objects.find((item) => item.id === snapshot.created)
    : null;
  if (obj) beginEdit(obj);
}

export function bindText() {
  // 点了框外面就提交：比监听 blur 可靠——点工具条、拖滚动条都不该结束编辑。
  document.addEventListener(
    'pointerdown',
    (event) => {
      if (!editing) return;
      if (editing.node.contains(event.target)) return;
      if (bar && bar.el.contains(event.target)) return;
      // 属性栏里的删除等动作要依赖当前选择，不能先把选择清掉。
      if (event.target.closest && event.target.closest('#inspector')) {
        commitEdit();
        return;
      }
      const inViewport = event.target.closest && event.target.closest('#viewport');
      if (inViewport) {
        // 拦的只是画布上的那一下：否则「文本模式点空白建新框」会跟着触发，
        // 点一下空白就多出一个空文本框。左栏、顶栏的按钮不在画布里，不能被拦。
        event.stopPropagation();
      }
      // 点文本框以外：结束编辑并取消选中。不新建文本框，也不把手势留给画布。
      commitEdit().then(() => {
        applySelection([]);
        call('select', []).then((snapshot) => snapshot && apply(snapshot));
      });
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
