/* 入口：装配、事件分发。具体动作在 actions.js，键位在 shortcuts.js。 */

import * as actions from './actions.js';
import { bridgeReady, call, setStrings, T, toast } from './bridge.js';
import { bindCanvas, fitWidth, observePages, pageJump, resetZoom, zoomBy } from './canvas.js';
import { openExport } from './export.js';
import { bindGuides } from './guides.js';
import { bindInteract } from './interact.js';
import { renderMarkdown } from './markdown.js';
import { askUnsaved, openModal } from './modal.js';
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
    // 保存进行中：任何动作都不该插进去，后端此刻已经把文档句柄放掉了。
    if (state.view.busy) return;
    const handler = ACTIONS[trigger.dataset.act];
    if (handler) await handler();
  });

  document.addEventListener('pages:rebuilt', () => observePages());
}

/* ---------- 首次启动 ---------- */

async function runFirstRun() {
  const data = state.data;
  const body = document.createElement('div');

  const intro = document.createElement('p');
  intro.className = 'modal-text';
  intro.dataset.i18n = 'firstrun.text';
  intro.textContent = T('firstrun.text');
  body.appendChild(intro);

  const field = document.createElement('div');
  field.className = 'field';

  const label = document.createElement('label');
  label.htmlFor = 'firstrun-language';
  label.dataset.i18n = 'firstrun.title';
  label.textContent = T('firstrun.title');

  const select = document.createElement('select');
  select.id = 'firstrun-language';
  select.className = 'about-select';
  const names = data.language_names || {};
  for (const code of data.languages || []) {
    const option = document.createElement('option');
    option.value = code;
    option.textContent = names[code] || code;
    if (code === data.language) option.selected = true;
    select.appendChild(option);
  }
  field.append(label, select);
  body.appendChild(field);

  // 下拉框一改就把界面切成那种语言：用户不必先点「开始使用」才能看懂界面。
  select.addEventListener('change', () => previewLanguage(select.value));

  const choice = await openModal({
    title: T('firstrun.title'),
    titleKey: 'firstrun.title',
    body,
    narrow: true,
    actions: [
      { label: T('firstrun.start'), value: 'go', kind: 'primary', i18n: 'firstrun.start' },
    ],
  });
  if (choice !== 'go') return;

  const snapshot = await call('complete_first_run', select.value);
  if (snapshot) {
    apply(snapshot);
    const strings = await call('get_strings');
    if (strings) setStrings(strings);
    applyStrings();
  }

  const readme = await call('get_readme');
  const manual = renderMarkdown((readme && readme.markdown) || '');
  if (!manual.textContent.trim()) manual.textContent = T('about.readme_missing');
  await openModal({
    title: T('firstrun.readme_title'),
    text: T('firstrun.readme_text'),
    body: manual,
    actions: [
      { label: T('firstrun.readme_close'), value: 'ok', kind: 'primary' },
    ],
  });
}

/* 首次运行的语言下拉框：只换内存里的语言，不落盘，界面立刻跟着变。 */
async function previewLanguage(code) {
  const data = await call('preview_language', code);
  if (!data) return;
  const strings = await call('get_strings');
  if (strings) setStrings(strings);
  applyStrings();
  state.language = data.language;
  document.documentElement.lang = data.language;
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
  if (snapshot.first_run) await runFirstRun();
}

if (bridgeReady()) {
  init();
} else {
  window.addEventListener('pywebviewready', init, { once: true });
}
