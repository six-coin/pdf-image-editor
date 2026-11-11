/* 入口：装配、事件分发。具体动作在 actions.js，键位在 shortcuts.js。 */

import * as actions from './actions.js';
import { bridgeReady, call, setStrings, T, toast } from './bridge.js';
import { bindCanvas, fitWidth, observePages, pageJump, resetZoom, zoomBy } from './canvas.js';
import { openExport } from './export.js';
import { bindGuides } from './guides.js';
import { bindInteract } from './interact.js';
import { askUnsaved } from './modal.js';
import { apply, applyStrings, applyTheme } from './render.js';
import { state } from './state.js';
import { openSettings } from './settings.js';
import { bindShortcuts } from './shortcuts.js';
import { bindSplit, cancelSplit, keepCell, punchCell, splitAll, startSplit } from './split.js';

const ACTIONS = {
  open: actions.openPdf,
  save: actions.saveDoc,
  'save-as': actions.saveAs,
  export: openExport,
  preprocess: actions.preprocessPdf,
  reload: actions.reloadDoc,
  'page-jump': pageJump,
  settings: openSettings,
  'toggle-theme': async () => {
    const next = state.view.theme === 'dark' ? 'light' : 'dark';
    // 先切界面再落盘：换主题不该等一次桥接往返。
    applyTheme(next);
    const snapshot = await call('update_settings', { theme: next });
    if (snapshot) apply(snapshot);
  },
  'toggle-inspector': actions.toggleInspector,
  undo: actions.undo,
  redo: actions.redo,
  'zoom-in': () => zoomBy(1.2),
  'zoom-out': () => zoomBy(1 / 1.2),
  'zoom-reset': resetZoom,
  'fit-width': fitWidth,
  split: startSplit,
  'keep-cell': keepCell,
  'punch-cell': punchCell,
  'split-all': splitAll,
  'split-cancel': cancelSplit,
  delete: actions.deleteSelection,
  front: () => actions.reorder('front'),
  back: () => actions.reorder('back'),
  paste: actions.pasteImage,
  external: actions.externalEdit,
};

/* ---------- 关闭握手 ---------- */

function installHost() {
  window.host = {
    /** 后端状态可能被外部改过（比如打开文件的任务），重新拉一次快照并整体重绘。 */
    reload: async () => {
      const snapshot = await call('get_state');
      if (snapshot) apply(snapshot);
      return Boolean(snapshot);
    },
    askUnsaved: async () => {
      const choice = await askUnsaved({
        title: T('dialog.unsaved_title'),
        text: T('dialog.unsaved_text'),
        save: T('dialog.save'),
        discard: T('dialog.discard'),
        cancel: T('dialog.cancel'),
      });
      if (choice === 'save') {
        const result = await call('save_document');
        if (result && result.ok) {
          await call('answer_close', 'close');
        } else {
          toast((result && result.message) || T('error.unexpected'), false);
        }
        return;
      }
      await call('answer_close', choice);
    },
  };
}

/* ---------- 事件 ---------- */

function bindClicks() {
  document.addEventListener('click', async (event) => {
    const trigger = event.target.closest('[data-act]');
    if (!trigger || trigger.disabled) return;
    const handler = ACTIONS[trigger.dataset.act];
    if (handler) await handler();
  });

  document.addEventListener('pages:rebuilt', () => observePages());
}

/* ---------- 启动 ---------- */

async function init() {
  installHost();
  bindCanvas();
  bindInteract();
  bindSplit();
  bindGuides();
  bindShortcuts();
  bindClicks();

  const strings = await call('get_strings');
  if (strings) setStrings(strings);
  applyStrings();

  let theme = 'light';
  try {
    theme = localStorage.getItem('appTheme') || theme;
  } catch (error) {
    /* 隐私模式 */
  }
  applyTheme(theme);

  const snapshot = await call('get_state');
  if (!snapshot) return;
  apply(snapshot);
  if (snapshot.doc.page_count) fitWidth();
}

if (bridgeReady()) {
  init();
} else {
  window.addEventListener('pywebviewready', init, { once: true });
}
