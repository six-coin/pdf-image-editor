/* 画布模式：选择 / 文本 / 荧光笔。

   模式决定「在页面上按下去会发生什么」，所以它必须一直看得见——左栏常驻、
   不能关。切换模式时把状态同步到左栏按钮和视口的光标上。 */

export const MODE_SELECT = 'select';
export const MODE_TEXT = 'text';
export const MODE_HIGHLIGHT = 'highlight';

const MODES = [MODE_SELECT, MODE_TEXT, MODE_HIGHLIGHT];

let mode = MODE_SELECT;
const listeners = new Set();

export function currentMode() {
  return mode;
}

/** 订阅模式变化。返回取消订阅的函数。 */
export function onModeChange(handler) {
  listeners.add(handler);
  return () => listeners.delete(handler);
}

export function setMode(next, options = {}) {
  const value = MODES.includes(next) ? next : MODE_SELECT;
  const changed = value !== mode;
  mode = value;

  const viewport = document.getElementById('viewport');
  if (viewport) {
    viewport.classList.toggle('mode-text', value === MODE_TEXT);
    viewport.classList.toggle('mode-highlight', value === MODE_HIGHLIGHT);
  }
  document.querySelectorAll('.rail-btn').forEach((button) => {
    const on = button.dataset.mode === value;
    button.classList.toggle('active', on);
    button.setAttribute('aria-pressed', on ? 'true' : 'false');
  });

  if (changed) {
    for (const handler of listeners) handler(value, options);
  }
}

export function bindModes() {
  document.querySelectorAll('.rail-btn').forEach((button) => {
    button.addEventListener('click', () => setMode(button.dataset.mode));
  });
  setMode(mode);
}
