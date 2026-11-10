/* 动作：所有会改后端状态的操作集中在这里，点击与快捷键共用同一份实现。 */

import { call, T, toast } from './bridge.js';
import { openModal } from './modal.js';
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
  $('busyText').textContent = total
    ? `${T('status.loading')} ${done}/${total}`
    : T('status.loading');
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
  const started = await call('open_path', path);
  if (!started) return;
  if (!started.ok) {
    toast(started.message || T('error.unexpected'), false);
    return;
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
};

async function showWarnings(report) {
  const warnings = report.warnings || [];
  if (!warnings.length) return;

  const body = document.createElement('div');
  body.className = 'warning-list';
  for (const warning of warnings) {
    const row = document.createElement('div');
    row.className = 'warning-row';
    const page = document.createElement('span');
    page.className = 'chip warn';
    page.textContent = T('save.warning_page', { page: (warning.page ?? 0) + 1 });
    const text = document.createElement('span');
    text.textContent = T(WARNING_KEYS[warning.code] || 'error.unexpected', {
      detail: warning.detail || '',
    });
    row.append(page, text);
    body.appendChild(row);
  }

  await openModal({
    title: T('save.warnings', { count: warnings.length }),
    body,
    actions: [{ label: T('dialog.close'), value: 'ok', kind: 'primary' }],
  });
}

async function commitSave(mode, path) {
  const result = await call('save_document', mode, path || null);
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
  if (!state.data || !state.data.doc.page_count) return;
  await commitSave(null, null);
}

export async function saveAs() {
  const data = state.data;
  if (!data || !data.doc.page_count) return;

  const stem = (data.doc.name || 'output.pdf').replace(/\.pdf$/i, '');
  const path = await call('browse_save', `${stem}-edited.pdf`);
  if (!path) return;

  const chosen = { mode: data.doc.save_mode };
  const body = document.createElement('div');
  body.className = 'save-mode';

  const hint = document.createElement('p');
  hint.className = 'hint';
  hint.textContent = T(`save.mode_${chosen.mode}_hint`);

  const seg = document.createElement('div');
  seg.className = 'seg';
  for (const mode of ['preserve', 'raster']) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `seg-item${mode === chosen.mode ? ' active' : ''}`;
    button.textContent = T(`save.mode_${mode}`);
    button.addEventListener('click', () => {
      chosen.mode = mode;
      seg.querySelectorAll('.seg-item').forEach((node) => node.classList.remove('active'));
      button.classList.add('active');
      hint.textContent = T(`save.mode_${mode}_hint`);
    });
    seg.appendChild(button);
  }

  const label = document.createElement('div');
  label.className = 'field-label';
  label.textContent = T('save.mode');
  body.append(label, seg, hint);

  const choice = await openModal({
    title: T('save.title'),
    text: path,
    body,
    actions: [
      { label: T('dialog.cancel'), value: 'cancel', kind: 'ghost' },
      { label: T('dialog.save'), value: 'ok', kind: 'primary' },
    ],
  });
  if (choice !== 'ok') return;
  await commitSave(chosen.mode, path);
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
  if (!state.data) return;
  await selectIds(state.data.objects.map((o) => o.id));
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

export async function preprocessPdf() {
  const started = await call('preprocess_pdf');
  if (!started || !started.ok) return;
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
