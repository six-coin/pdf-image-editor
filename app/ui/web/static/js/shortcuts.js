/* 键位表。所有快捷键只在这里注册一次，不在业务模块里各绑一遍。 */

import * as actions from './actions.js';
import { nudge, setSpaceHeld } from './interact.js';
import { cancelSplit, isSplitActive, splitAll, startSplit, undoCut } from './split.js';
import { isOpen as modalOpen } from './modal.js';

const ARROW_STEP = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

function inEditable(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable;
}

function handleSplit(event) {
  if (event.key === 'Escape') {
    event.preventDefault();
    cancelSplit();
    return true;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    splitAll();
    return true;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault();
    undoCut();
    return true;
  }
  return false;
}

function onKeyDown(event) {
  if (modalOpen() || inEditable(event.target)) return;

  if (event.code === 'Space') {
    setSpaceHeld(true);
    event.preventDefault();
    return;
  }
  if (isSplitActive() && handleSplit(event)) return;

  const mod = event.ctrlKey || event.metaKey;
  const key = event.key;

  if (mod) {
    const lower = key.toLowerCase();
    if (lower === 'o') {
      event.preventDefault();
      actions.openPdf();
      return;
    }
    if (lower === 's') {
      event.preventDefault();
      if (event.shiftKey) actions.saveAs();
      else actions.saveDoc();
      return;
    }
    if (lower === 'v') {
      event.preventDefault();
      actions.pasteImage();
      return;
    }
    if (lower === 'z') {
      event.preventDefault();
      if (event.shiftKey) actions.redo();
      else actions.undo();
      return;
    }
    if (lower === 'y') {
      event.preventDefault();
      actions.redo();
      return;
    }
    if (lower === 'a') {
      event.preventDefault();
      actions.selectAll();
      return;
    }
    if (key === '0') {
      event.preventDefault();
      import('./canvas.js').then((m) => m.fitWidth());
      return;
    }
    if (key === '=' || key === '+') {
      event.preventDefault();
      import('./canvas.js').then((m) => m.zoomBy(1.2));
      return;
    }
    if (key === '-') {
      event.preventDefault();
      import('./canvas.js').then((m) => m.zoomBy(1 / 1.2));
      return;
    }
    return;
  }

  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    actions.deleteSelection();
    return;
  }
  if (key === 'Escape') {
    actions.clearSelection();
    return;
  }
  if (key === 's' || key === 'S') {
    event.preventDefault();
    startSplit();
    return;
  }
  if (ARROW_STEP[key]) {
    event.preventDefault();
    const [dx, dy] = ARROW_STEP[key];
    const step = event.shiftKey ? 10 : 1;
    nudge(dx * step, dy * step);
  }
}

function onKeyUp(event) {
  if (event.code === 'Space') setSpaceHeld(false);
}

export function bindShortcuts() {
  document.addEventListener('keydown', onKeyDown);
  document.addEventListener('keyup', onKeyUp);
  window.addEventListener('blur', () => setSpaceHeld(false));
}
