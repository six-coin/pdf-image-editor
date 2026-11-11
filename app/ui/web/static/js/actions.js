/* 动作：所有会改后端状态的操作集中在这里，点击与快捷键共用同一份实现。 */

import { call, T, toast } from './bridge.js';
import { askUnsaved, openModal } from './modal.js';
import { apply, selectedIds } from './render.js';
import { refresh } from './sync.js';
import { state } from './state.js';

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* ---------- 任务 ---------- */

function showBusy(status) {
  const box = $('busy');
  if (!box) return;
  if (!status) {
    box.classList.add('hidden');
    return;
  }
  box.classList.remove('hidden');
  const progress = status.progress || {};
  const total = progress.total || 0;
  const done = progress.done || 0;
  const label = status.label === 'open' ? T('status.loading') : T('status.working');
  $('busyText').textContent = total ? `${label} ${done}/${total}` : label;
  $('busyBar').style.width = total ? `${Math.round((100 * done) / total)}%` : '35%';
}

async function waitTask(taskId) {
  if (!taskId) return null;
  for (;;) {
    const status = await call('poll_task', taskId);
    if (!status) {
      showBusy(null);
      return null;
    }
    if (status.state === 'unknown') {
      // 任务表只留最近若干条，轮询到已被挤掉的 id 时必须收手，否则会一直转。
      showBusy(null);
      return { state: 'error', message: T('error.task_lost') };
    }
    showBusy(status);
    if (status.state === 'ready' || status.state === 'error') {
      showBusy(null);
      return status;
    }
    await sleep(80);
  }
}

/* ---------- 文档 ---------- */

export async function openPdf() {
  const path = await call('browse_pdf');
  if (!path) return;

  let started = await call('open_path', path);
  if (!started) return;
  if (!started.ok) {
    // 有未保存修改时后端会拒绝。这里必须给出「保存 / 不保存 / 取消」三条路，
    // 只弹一条提示的话用户选完文件就卡住了，还得自己回去保存再重来一遍。
    if (started.reason !== 'dirty') {
      toast(started.message || T('error.unexpected'), false);
      return;
    }
    const choice = await askUnsaved({
      title: T('dialog.unsaved_title'),
      text: T('dialog.unsaved_text'),
      save: T('dialog.save'),
      discard: T('dialog.discard'),
      cancel: T('dialog.cancel'),
    });
    if (choice === 'cancel') return;
    if (choice === 'save') {
      const saved = await call('save_document');
      if (!saved || !saved.ok) {
        toast((saved && saved.message) || T('error.unexpected'), false);
        return;
      }
      await refresh();
    }
    started = await call('open_path', path, true);
    if (!started || !started.ok) {
      toast((started && started.message) || T('error.unexpected'), false);
      return;
    }
  }

  const done = await waitTask(started.task);
  if (!done || done.state !== 'ready') {
    if (done && done.message) toast(done.message, false);
    return;
  }
  const { fitWidth } = await import('./canvas.js');
  const snapshot = await refresh();
  if (snapshot && snapshot.doc.page_count) fitWidth();
}

const WARNING_KEYS = {
  redact_failed: 'save.warning_redact_failed',
  image_clamped: 'save.warning_image_clamped',
  insert_failed: 'save.warning_insert_failed',
  image_skipped: 'save.warning_image_skipped',
  annots_lost: 'save.warning_annots_lost',
  reopen_failed: 'save.warning_reopen_failed',
};

async function showWarnings(report) {
  const warnings = report.warnings || [];
  if (!warnings.length) return;

  const body = document.createElement('div');
  body.className = 'warning-list';
  for (const warning of warnings) {
    const row = document.createElement('div');
    row.className = 'warning-row';
    // 整份文档级别的警告（保存成功但界面没能刷新）没有页号，就不显示页码徽标。
    if (typeof warning.page === 'number') {
      const page = document.createElement('span');
      page.className = 'chip warn';
      page.textContent = T('save.warning_page', { page: warning.page + 1 });
      row.appendChild(page);
    }
    const text = document.createElement('span');
    text.textContent = T(WARNING_KEYS[warning.code] || 'error.unexpected', {
      detail: warning.detail || '',
    });
    row.appendChild(text);
    body.appendChild(row);
  }

  await openModal({
    title: T('save.warnings', { count: warnings.length }),
    body,
    actions: [{ label: T('dialog.close'), value: 'ok', kind: 'primary' }],
  });
}

/** 保存期间：底部横幅 + 锁住画布与快捷键，避免改动落到正在重建的文档上。 */
function setSaving(on) {
  state.view.busy = Boolean(on);
  document.body.classList.toggle('saving', Boolean(on));
  const banner = $('saveBanner');
  if (banner) banner.classList.toggle('hidden', !on);
}

async function commitSave(path) {
  if (state.view.busy) return;
  setSaving(true);
  let result = null;
  try {
    result = await call('save_document', path || null);
  } finally {
    setSaving(false);
  }
  if (!result) return;
  if (!result.ok) {
    toast(result.message || T('error.unexpected'), false);
    return;
  }
  await refresh();
  await showWarnings(result);
  toast(T('save.done', { path: result.path }));
}

export async function saveDoc() {
  if (!state.data || !state.data.doc.page_count || state.view.busy) return;
  await commitSave(null);
}

export async function saveAs() {
  const data = state.data;
  if (!data || !data.doc.page_count || state.view.busy) return;

  const stem = (data.doc.name || 'output.pdf').replace(/\.pdf$/i, '');
  const path = await call('browse_save', `${stem}-edited.pdf`);
  if (!path) return;
  await commitSave(path);
}

/** 从磁盘重新加载当前文件。有未保存修改时先确认。 */
export async function reloadDoc() {
  const data = state.data;
  if (!data || !data.doc.page_count) return;

  let result = await call('reload_document');
  if (!result) return;

  if (!result.ok && result.needs_confirm) {
    const choice = await openModal({
      title: T('toolbar.reload'),
      text: T('dialog.reload_text'),
      narrow: true,
      actions: [
        { label: T('dialog.cancel'), value: 'cancel', kind: 'ghost' },
        { label: T('toolbar.reload'), value: 'ok', kind: 'danger' },
      ],
    });
    if (choice !== 'ok') return;
    result = await call('reload_document', true);
    if (!result) return;
  }

  if (!result.ok) {
    toast(result.message || T('error.unexpected'), false);
    return;
  }
  apply(result);
}

/* ---------- 编辑 ---------- */

export async function selectIds(ids) {
  const snapshot = await call('select', ids);
  if (snapshot) apply(snapshot);
}

export async function deleteSelection() {
  const ids = selectedIds();
  if (!ids.length) return;
  const snapshot = await call('delete_objects', ids);
  if (snapshot) apply(snapshot);
}

export async function reorder(mode) {
  const ids = selectedIds();
  if (!ids.length) return;
  const snapshot = await call('reorder_objects', ids, mode);
  if (snapshot) apply(snapshot);
}

export async function undo() {
  const snapshot = await call('undo');
  if (snapshot) apply(snapshot);
}

export async function redo() {
  const snapshot = await call('redo');
  if (snapshot) apply(snapshot);
}

export async function selectAll() {
  if (!state.data || state.view.busy) return;
  // 多选只能同页：全选取当前视口所在的这一页，不跨页。
  const { currentPage } = await import('./canvas.js');
  const page = currentPage();
  await selectIds(state.data.objects.filter((o) => o.page === page).map((o) => o.id));
}

export async function clearSelection() {
  if (!state.data || !state.data.selection.length) return;
  await selectIds([]);
}

export async function pasteImage() {
  if (!state.data || !state.data.doc.page_count) return;
  const { currentPage } = await import('./canvas.js');
  const result = await call('paste_image', currentPage());
  if (!result) return;
  if (!result.ok) {
    toast(result.message || T('error.unexpected'), false);
    return;
  }
  apply(result);
}

export async function externalEdit() {
  const ids = selectedIds();
  if (ids.length !== 1) return;

  const opened = await call('edit_external', ids[0]);
  if (!opened || !opened.ok) {
    toast((opened && opened.message) || T('error.unexpected'), false);
    return;
  }

  const choice = await openModal({
    title: T('edit.external_title'),
    text: T('edit.external_hint'),
    narrow: true,
    actions: [
      { label: T('dialog.cancel'), value: 'cancel', kind: 'ghost' },
      { label: T('dialog.ok'), value: 'ok', kind: 'primary' },
    ],
  });
  if (choice !== 'ok') return;

  const result = await call('replace_image', ids[0], opened.path);
  if (result) apply(result);
}

/* ---------- 预处理 ---------- */

/** 黑白化预处理：先解释清楚再让用户选文件，避免点一下就开始跑。 */
export async function preprocessPdf() {
  const choice = await openModal({
    title: T('preprocess.title'),
    text: T('preprocess.text'),
    narrow: true,
    actions: [
      { label: T('dialog.cancel'), value: 'cancel', kind: 'ghost' },
      { label: T('preprocess.start'), value: 'ok', kind: 'primary' },
    ],
  });
  if (choice !== 'ok') return;

  const started = await call('preprocess_pdf');
  if (!started) return;
  if (!started.ok) {
    // 在选择框里点了取消不是错误，不弹提示。
    if (started.reason !== 'cancel') toast(started.message || T('error.unexpected'), false);
    return;
  }
  const done = await waitTask(started.task);
  if (!done || done.state !== 'ready') {
    if (done && done.message) toast(done.message, false);
    return;
  }
  const result = done.result || {};
  toast(T('status.preprocess_done', { count: result.count ?? 0, path: result.path ?? '' }));
}

/* ---------- 界面 ---------- */

export async function toggleInspector() {
  if (!state.data) return;
  const next = !state.data.show_inspector;
  // 先改界面再落盘：属性栏的收放不该等一次桥接往返。
  state.data.show_inspector = next;
  const app = document.getElementById('app');
  if (app) app.classList.toggle('inspector-hidden', !next);
  const button = document.getElementById('btnInspector');
  if (button) button.setAttribute('aria-pressed', next ? 'true' : 'false');

  const snapshot = await call('update_settings', { show_inspector: next });
  if (snapshot) apply(snapshot);
}
