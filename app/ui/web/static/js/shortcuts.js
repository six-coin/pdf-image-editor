/* 键位分发。
   分割模式有独立作用域：进入分割后只认 split 表，全局快捷键一律不响应，
   所以两边可以绑同一个键而不打架。 */

import * as actions from './actions.js';
import { fitWidth, resetZoom, zoomBy } from './canvas.js';
import { openExport } from './export.js';
import { nudge, setSpaceHeld } from './interact.js';
import { accelOf, lookup } from './keymap.js';
import { isOpen as modalOpen } from './modal.js';
import { openSettings } from './settings.js';
import { state } from './state.js';
import {
  cancelSplit,
  isSplitActive,
  keepCell,
  punchCell,
  splitAll,
  startSplit,
  undoCut,
} from './split.js';

const GLOBAL_RUNNERS = {
  open: actions.openPdf,
  save: actions.saveDoc,
  save_as: actions.saveAs,
  export: openExport,
  undo: actions.undo,
  redo: actions.redo,
  delete: actions.deleteSelection,
  select_all: actions.selectAll,
  paste: actions.pasteImage,
  zoom_in: () => zoomBy(1.2),
  zoom_out: () => zoomBy(1 / 1.2),
  zoom_fit: fitWidth,
  zoom_reset: resetZoom,
  split: startSplit,
  front: () => actions.reorder('front'),
  back: () => actions.reorder('back'),
  external: actions.externalEdit,
  settings: openSettings,
  toggle_inspector: actions.toggleInspector,
};

const SPLIT_RUNNERS = {
  split_keep: keepCell,
  split_punch: punchCell,
  split_all: splitAll,
  split_undo: undoCut,
  split_cancel: cancelSplit,
};

const ARROWS = { Up: [0, -1], Down: [0, 1], Left: [-1, 0], Right: [1, 0] };

function inEditable(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable;
}

function onKeyDown(event) {
  if (modalOpen() || state.view.busy || inEditable(event.target)) return;

  if (event.code === 'Space') {
    // 焦点在按钮上时，空格属于「按下这个按钮」，不能拿来当平移的起手式。
    if (event.target && event.target.tagName === 'BUTTON') return;
    setSpaceHeld(true);
    event.preventDefault();
    return;
  }

  const accel = accelOf(event);
  if (!accel) return;

  if (isSplitActive()) {
    const command = lookup('split', accel);
    if (command && SPLIT_RUNNERS[command]) {
      event.preventDefault();
      SPLIT_RUNNERS[command]();
    }
    // 分割模式下不响应全局快捷键：作用域隔离。
    return;
  }

  const command = lookup('global', accel);
  if (command && GLOBAL_RUNNERS[command]) {
    event.preventDefault();
    GLOBAL_RUNNERS[command]();
    return;
  }

  // 方向键微调不参与自定义键位，避免和上面的表互相干扰。
  const arrow = ARROWS[accel];
  if (arrow) {
    event.preventDefault();
    const step = event.shiftKey ? 10 : 1;
    nudge(arrow[0] * step, arrow[1] * step);
    return;
  }

  // Ctrl+方向键：单步的 1/5，用来对齐细部
  if (accel.startsWith('Ctrl+')) {
    const fine = ARROWS[accel.slice(5)];
    if (fine) {
      event.preventDefault();
      nudge(fine[0] * 0.2, fine[1] * 0.2);
    }
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
