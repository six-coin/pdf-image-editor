/* 设置面板。表单值先改在本地草稿里，点「保存」才写盘并整体重绘。 */

import { call, setStrings, T, toast } from './bridge.js';
import { COMMANDS, DEFAULT_BINDINGS, accelOf, bindings, findConflicts } from './keymap.js';
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
      box.querySelectorAll('.seg-item').forEach((node) => {
        node.classList.remove('active');
        node.setAttribute('aria-pressed', 'false');
      });
      button.classList.add('active');
      button.setAttribute('aria-pressed', 'true');
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
    if (Number.isFinite(parsed)) onChange(Math.min(max, Math.max(min, parsed)));
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

function keyRow(scope, command, draft) {
  const row = document.createElement('div');
  row.className = 'key-row';

  const label = document.createElement('span');
  label.className = 'key-label';
  label.textContent = T(command.labelKey);

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'key-binding';
  button.textContent = draft[scope][command.id] || '—';

  button.addEventListener('click', () => {
    if (button.classList.contains('capturing')) return;
    button.classList.add('capturing');
    button.textContent = T('settings.press_key');

    const stop = () => {
      document.removeEventListener('keydown', onKey, true);
      button.classList.remove('capturing');
      button.textContent = draft[scope][command.id] || '—';
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
      draft[scope][command.id] = accel;
      button.textContent = accel;
      document.removeEventListener('keydown', onKey, true);
      button.classList.remove('capturing');
    };

    document.addEventListener('keydown', onKey, true);
  });

  row.append(label, button);
  return row;
}

function keySection(scope, draft) {
  const wrap = document.createElement('div');
  wrap.className = 'key-section';
  wrap.appendChild(section(scope === 'global' ? 'settings.scope_global' : 'settings.scope_split'));

  const grid = document.createElement('div');
  grid.className = 'key-grid';
  for (const command of COMMANDS[scope]) {
    grid.appendChild(keyRow(scope, command, draft));
  }
  wrap.appendChild(grid);
  return wrap;
}

/* ---------- 主入口 ---------- */

export async function openSettings() {
  if (!state.data) return;

  const draft = {
    language: state.data.language,
    theme: state.data.theme,
    save_mode: state.data.doc.save_mode,
    undo_limit: state.data.undo_limit,
    show_guides: state.data.show_guides,
  };
  const margins = { ...state.data.reference };
  const keys = bindings();

  const body = document.createElement('div');
  body.className = 'settings';

  const languages = (state.data.languages || ['zh-CN']).map((code) => ({
    value: code,
    label: languageLabel(code),
  }));
  body.appendChild(
    field(
      'settings.language',
      segmented(languages, draft.language, (value) => {
        draft.language = value;
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
        draft.theme,
        (value) => {
          draft.theme = value;
        }
      )
    )
  );

  const modeHint = document.createElement('p');
  modeHint.className = 'hint';
  modeHint.textContent = T(`save.mode_${draft.save_mode}_hint`);
  body.appendChild(
    field(
      'settings.save_mode',
      segmented(
        [
          { value: 'preserve', label: T('save.mode_preserve') },
          { value: 'raster', label: T('save.mode_raster') },
        ],
        draft.save_mode,
        (value) => {
          draft.save_mode = value;
          modeHint.textContent = T(`save.mode_${value}_hint`);
        }
      )
    )
  );
  body.appendChild(modeHint);

  body.appendChild(
    field(
      'settings.undo_limit',
      numberBox(draft.undo_limit, 10, 500, 10, (value) => {
        draft.undo_limit = value;
      })
    )
  );

  const guidesRow = document.createElement('div');
  guidesRow.className = 'field-row';
  const guidesLabel = document.createElement('span');
  guidesLabel.className = 'field-label';
  guidesLabel.textContent = T('settings.guides');
  guidesRow.append(
    guidesLabel,
    toggle(draft.show_guides, (value) => {
      draft.show_guides = value;
    })
  );
  body.appendChild(guidesRow);

  const marginGrid = document.createElement('div');
  marginGrid.className = 'margin-grid';
  for (const key of ['left', 'top', 'right', 'bottom']) {
    const cell = document.createElement('label');
    cell.className = 'margin-cell';
    const text = document.createElement('span');
    text.textContent = T(`settings.${key}`);
    const input = numberBox(margins[`${key}_mm`] ?? 0, 0, 300, 1, (value) => {
      margins[`${key}_mm`] = value;
    });
    cell.append(text, input);
    marginGrid.appendChild(cell);
  }
  body.appendChild(field('settings.margins', marginGrid));

  body.appendChild(section('settings.shortcuts'));

  const resetButton = document.createElement('button');
  resetButton.type = 'button';
  resetButton.className = 'btn sm';
  resetButton.textContent = T('settings.reset_shortcuts');
  resetButton.addEventListener('click', () => {
    keys.global = { ...DEFAULT_BINDINGS.global };
    keys.split = { ...DEFAULT_BINDINGS.split };
    body.querySelectorAll('.key-binding').forEach((node) => {
      node.textContent = '—';
    });
    // 重建两张表，最省事也最不容易漏。
    body.querySelectorAll('.key-section').forEach((node) => node.remove());
    body.append(keySection('global', keys), keySection('split', keys));
  });
  body.appendChild(resetButton);

  body.append(keySection('global', keys), keySection('split', keys));

  const choice = await openModal({
    title: T('settings.title'),
    body,
    actions: [
      { label: T('dialog.cancel'), value: 'cancel', kind: 'ghost' },
      { label: T('dialog.save'), value: 'ok', kind: 'primary' },
    ],
  });
  if (choice !== 'ok') return;

  for (const scope of ['global', 'split']) {
    const conflicts = findConflicts(keys[scope]);
    if (conflicts.length) {
      toast(T('settings.conflict', { accel: conflicts[0][0] }), false);
      return;
    }
  }

  const snapshot = await call('update_settings', { ...draft, keybindings: keys });
  if (snapshot) apply(snapshot);
  await call('update_reference', margins);

  const strings = await call('get_strings');
  if (strings) setStrings(strings);
  applyStrings();

  const fresh = await call('get_state');
  if (fresh) apply(fresh);
}
