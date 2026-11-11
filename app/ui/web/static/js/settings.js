/* 设置面板。
   每一次改动都立刻写盘，所以没有「取消」也没有「保存」——关掉弹窗不会撤销任何东西，
   界面上看到的永远等于 config 里的内容。 */

import { call, setStrings, T, toast } from './bridge.js';
import { COMMANDS, accelOf, bindings, findConflicts } from './keymap.js';
import { openModal } from './modal.js';
import { apply, applyStrings } from './render.js';
import { state } from './state.js';

function field(labelKey, control) {
  const wrap = document.createElement('div');
  wrap.className = 'field';
  const label = document.createElement('label');
  label.textContent = T(labelKey);
  wrap.append(label, control);
  return wrap;
}

function section(labelKey) {
  const title = document.createElement('h3');
  title.className = 'settings-section-title';
  title.textContent = T(labelKey);
  return title;
}

function segmented(options, current, onChange) {
  const box = document.createElement('div');
  box.className = 'seg';
  box.setAttribute('role', 'group');
  for (const option of options) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'seg-item';
    const active = option.value === current;
    if (active) button.classList.add('active');
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
    button.textContent = option.label;
    button.addEventListener('click', () => {
      if (option.value === current) return;
      current = option.value;
      box.querySelectorAll('.seg-item').forEach((node) => {
        const on = node === button;
        node.classList.toggle('active', on);
        node.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      onChange(option.value);
    });
    box.appendChild(button);
  }
  return box;
}

function numberBox(value, min, max, step, onChange) {
  const input = document.createElement('input');
  input.type = 'number';
  input.min = String(min);
  input.max = String(max);
  input.step = String(step);
  input.value = String(value);
  input.addEventListener('change', () => {
    const parsed = Number(input.value);
    if (!Number.isFinite(parsed)) {
      input.value = String(value);
      return;
    }
    const clamped = Math.min(max, Math.max(min, parsed));
    input.value = String(clamped);
    if (clamped !== value) {
      value = clamped;
      onChange(clamped);
    }
  });
  return input;
}

function toggle(checked, onChange) {
  const label = document.createElement('label');
  label.className = 'switch';
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = Boolean(checked);
  input.addEventListener('change', () => onChange(input.checked));
  const track = document.createElement('span');
  track.className = 'switch-track';
  label.append(input, track);
  return label;
}

function languageLabel(code) {
  const text = T(`lang.${code}`);
  return text === `lang.${code}` ? code : text;
}

/* ---------- 快捷键 ---------- */

function keyRow(scope, command, keys, onBind) {
  const row = document.createElement('div');
  row.className = 'key-row';

  const label = document.createElement('span');
  label.className = 'key-label';
  label.textContent = T(command.labelKey);

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'key-binding';
  button.textContent = keys[scope][command.id] || '—';

  button.addEventListener('click', () => {
    if (button.classList.contains('capturing')) return;
    button.classList.add('capturing');
    button.textContent = T('settings.press_key');

    const stop = () => {
      document.removeEventListener('keydown', onKey, true);
      button.classList.remove('capturing');
      button.textContent = keys[scope][command.id] || '—';
    };

    const onKey = (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === 'Escape') {
        stop();
        return;
      }
      const accel = accelOf(event);
      if (!accel) return;
      document.removeEventListener('keydown', onKey, true);
      button.classList.remove('capturing');
      // 先显示按下的键，再写盘：写盘失败或冲突时 onBind 会把它改回去。
      button.textContent = accel;
      onBind(scope, command.id, accel, button);
    };

    document.addEventListener('keydown', onKey, true);
  });

  row.append(label, button);
  return row;
}

function keySection(scope, keys, onBind) {
  const wrap = document.createElement('div');
  wrap.className = 'key-section';
  wrap.appendChild(section(scope === 'global' ? 'settings.scope_global' : 'settings.scope_split'));

  const grid = document.createElement('div');
  grid.className = 'key-grid';
  for (const command of COMMANDS[scope]) {
    grid.appendChild(keyRow(scope, command, keys, onBind));
  }
  wrap.appendChild(grid);
  return wrap;
}

/* ---------- 主入口 ---------- */

export async function openSettings() {
  if (!state.data) return;

  const body = document.createElement('div');
  body.className = 'settings';

  // 页脚左侧的「重置所有」，建好之后 reloadLanguage 也要刷它的文案
  let resetButton = null;

  /** 写设置并落地快照。失败时弹提示，界面回到真实状态。 */
  async function writeSettings(patch) {
    const snapshot = await call('update_settings', patch);
    if (!snapshot) return null;
    apply(snapshot);
    if (snapshot.ok === false && snapshot.message) toast(snapshot.message, false);
    return snapshot;
  }

  async function writeReference(patch) {
    const snapshot = await call('update_reference', patch);
    if (!snapshot) return null;
    apply(snapshot);
    if (snapshot.ok === false && snapshot.message) toast(snapshot.message, false);
    return snapshot;
  }

  /** 语言变了：静态文案、弹窗标题和表单都要重建。 */
  async function reloadLanguage() {
    const strings = await call('get_strings');
    if (strings) setStrings(strings);
    applyStrings();
    const heading = document.querySelector(
      '#modalRoot .modal-card[data-modal="settings"] .modal-head h2'
    );
    if (heading) heading.textContent = T('settings.title');
    if (resetButton) resetButton.textContent = T('settings.reset_all');
    renderBody();
  }

  /** 改一个键位：同作用域内冲突就拒绝，不写盘。 */
  async function bindKey(scope, command, accel, button) {
    const keys = bindings();
    const previous = keys[scope][command];
    keys[scope][command] = accel;

    const conflicts = findConflicts(keys[scope]);
    if (conflicts.length) {
      button.textContent = previous || '—';
      toast(T('settings.conflict', { accel: conflicts[0][0] }), false);
      return;
    }

    const snapshot = await writeSettings({ keybindings: keys });
    if (!snapshot || snapshot.ok === false) {
      button.textContent = previous || '—';
    }
  }

  async function resetAll() {
    const choice = await openModal({
      title: T('settings.reset_all'),
      text: T('settings.reset_all_confirm'),
      narrow: true,
      actions: [
        { label: T('dialog.cancel'), value: 'cancel', kind: 'ghost' },
        { label: T('settings.reset_all'), value: 'ok', kind: 'danger' },
      ],
    });
    if (choice !== 'ok') return;

    const snapshot = await call('reset_settings');
    if (!snapshot) return;
    apply(snapshot);
    await reloadLanguage();
    toast(T('settings.reset_done'));
  }

  function renderBody() {
    const data = state.data;
    const keys = bindings();
    body.innerHTML = '';

    const languages = (data.languages || ['zh-CN']).map((code) => ({
      value: code,
      label: languageLabel(code),
    }));
    body.appendChild(
      field(
        'settings.language',
        segmented(languages, data.language, async (value) => {
          const snapshot = await writeSettings({ language: value });
          if (snapshot && snapshot.ok !== false) await reloadLanguage();
        })
      )
    );

    body.appendChild(
      field(
        'settings.theme',
        segmented(
          [
            { value: 'light', label: T('theme.light') },
            { value: 'dark', label: T('theme.dark') },
          ],
          data.theme,
          (value) => writeSettings({ theme: value })
        )
      )
    );

    const modeHint = document.createElement('p');
    modeHint.className = 'hint';
    modeHint.textContent = T(`save.mode_${data.doc.save_mode}_hint`);
    body.appendChild(
      field(
        'settings.save_mode',
        segmented(
          [
            { value: 'preserve', label: T('save.mode_preserve') },
            { value: 'raster', label: T('save.mode_raster') },
          ],
          data.doc.save_mode,
          (value) => {
            modeHint.textContent = T(`save.mode_${value}_hint`);
            writeSettings({ save_mode: value });
          }
        )
      )
    );
    body.appendChild(modeHint);

    body.appendChild(
      field(
        'settings.undo_limit',
        numberBox(data.undo_limit, 10, 500, 10, (value) => writeSettings({ undo_limit: value }))
      )
    );

    const guidesRow = document.createElement('div');
    guidesRow.className = 'field-row';
    const guidesLabel = document.createElement('span');
    guidesLabel.className = 'field-label';
    guidesLabel.textContent = T('settings.guides');
    guidesRow.append(
      guidesLabel,
      toggle(data.show_guides, (value) => writeSettings({ show_guides: value }))
    );
    body.appendChild(guidesRow);

    const margins = data.reference || {};
    const marginGrid = document.createElement('div');
    marginGrid.className = 'margin-grid';
    for (const key of ['left', 'top', 'right', 'bottom']) {
      const cell = document.createElement('label');
      cell.className = 'margin-cell';
      const text = document.createElement('span');
      text.textContent = T(`settings.${key}`);
      const input = numberBox(margins[`${key}_mm`] ?? 0, 0, 300, 1, (value) =>
        writeReference({ [`${key}_mm`]: value })
      );
      cell.append(text, input);
      marginGrid.appendChild(cell);
    }
    body.appendChild(field('settings.margins', marginGrid));

    body.appendChild(section('settings.shortcuts'));

    const resetKeys = document.createElement('button');
    resetKeys.type = 'button';
    resetKeys.className = 'btn sm';
    resetKeys.textContent = T('settings.reset_shortcuts');
    resetKeys.addEventListener('click', async () => {
      const snapshot = await writeSettings({ keybindings: {} });
      if (snapshot && snapshot.ok !== false) renderBody();
    });
    body.appendChild(resetKeys);

    body.append(keySection('global', keys, bindKey), keySection('split', keys, bindKey));
  }

  renderBody();

  // 「重置所有」和「关闭」同一行，靠左：红字白底，悬停淡红
  resetButton = document.createElement('button');
  resetButton.type = 'button';
  resetButton.className = 'btn soft-danger modal-leading';
  resetButton.textContent = T('settings.reset_all');
  resetButton.addEventListener('click', resetAll);

  await openModal({
    title: T('settings.title'),
    body,
    name: 'settings',
    leading: resetButton,
    actions: [{ label: T('dialog.close'), value: 'ok', kind: 'primary' }],
  });
}
