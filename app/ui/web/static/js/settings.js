/* 设置面板。
   每一次改动都立刻写盘，所以没有「取消」也没有「保存」——关掉弹窗不会撤销任何东西，
   界面上看到的永远等于 config 里的内容。 */

import { call, setStrings, T, toast } from './bridge.js';
import { segmented } from './controls.js';
import { COMMANDS, accelOf, bindings, findConflicts } from './keymap.js';
import { renderMarkdown } from './markdown.js';
import { openModal } from './modal.js';
import { apply, applyStrings, refreshTexts } from './render.js';
import { refreshSplitBar } from './split.js';
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
  // 语言名由后端下发（每种语言用自己的文字写），不按当前界面语言翻译。
  const names = (state.data && state.data.language_names) || {};
  return names[code] || code;
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

  /**
   * 语言变了：静态文案、弹窗标题与按钮、属性栏、表单都要重建。
   *
   * 快照是在切语言之前就落地渲染过的，那时字符串表还是旧的；所以这里必须
   * 先用新表覆盖，再把所有现算文案重建一遍，否则属性栏会慢一拍——切两次就
   * 变成「和当前语言相反」。
   */
  async function reloadLanguage() {
    const strings = await call('get_strings');
    if (strings) setStrings(strings);
    applyStrings();
    refreshTexts();
    refreshSplitBar();
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

  async function openReadme() {
    const readme = await call('get_readme');
    const body = renderMarkdown((readme && readme.markdown) || '');
    if (!body.textContent.trim()) {
      body.textContent = T('about.readme_missing');
    }
    await openModal({
      title: T('about.readme_title'),
      body,
      actions: [
        { label: T('dialog.close'), value: 'ok', kind: 'primary', i18n: 'dialog.close' },
      ],
    });
  }

  async function restartApp() {
    const snapshot = await call('restart_app');
    if (!snapshot) return;
    if (snapshot.ok === false && snapshot.message) toast(snapshot.message, false);
    // 成功时后端会直接关掉窗口，这一页不会再有下文。
  }

  async function applyDataDir(value) {
    const text = String(value || '').trim();
    if (!text) {
      renderBody();
      return;
    }
    const snapshot = await call('set_data_dir', text);
    if (!snapshot) return;
    apply(snapshot);
    if (snapshot.message) toast(snapshot.message, snapshot.ok !== false);
    renderBody();
  }

  async function changeDataDir() {
    const picked = await call('browse_folder');
    if (!picked) return;
    await applyDataDir(picked);
  }

  async function resetDataDir() {
    const snapshot = await call('reset_data_dir');
    if (!snapshot) return;
    apply(snapshot);
    if (snapshot.message) toast(snapshot.message, snapshot.ok !== false);
    renderBody();
  }

  /** 输入框下面那行小字：待生效 / 上次迁移的结果 / 默认说明。 */
  function dataDirHint(data) {
    const status = data.data_dir_status || {};
    if (data.data_dir_next) {
      return status.status === 'failed'
        ? T('about.data_dir_pending_failed', { path: data.data_dir_next })
        : T('about.data_dir_pending', { path: data.data_dir_next });
    }
    if (status.status === 'done' && status.moved > 0) {
      return T('about.data_dir_migrated', { count: status.moved, path: data.data_dir });
    }
    return T('about.data_dir_hint');
  }

  /* 数据目录：左边输入框，右边「更改」「重置」。输入框里是重启后生效的落点，
     没有待生效的值就是当前目录。 */
  function aboutBlock(data) {
    const wrap = document.createElement('div');
    wrap.className = 'about-block';

    const row = document.createElement('div');
    row.className = 'about-control';

    const current = String(data.data_dir_next || data.data_dir || '').trim();
    const input = document.createElement('input');
    input.type = 'text';
    input.id = 'about-data-dir';
    input.spellcheck = false;
    input.value = current;
    input.title = current;
    input.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      applyDataDir(input.value);
    });

    const change = document.createElement('button');
    change.type = 'button';
    change.className = 'btn sm';
    change.textContent = T('about.data_dir_change');
    change.addEventListener('click', () => {
      // 输入框改过就按输入的落点走，没改过才去选目录。
      const typed = input.value.trim();
      if (typed && typed !== current) {
        applyDataDir(typed);
        return;
      }
      changeDataDir();
    });

    const reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'btn sm';
    reset.textContent = T('about.data_dir_reset');
    reset.addEventListener('click', resetDataDir);

    row.append(input, change, reset);

    const hintRow = document.createElement('div');
    hintRow.className = 'about-hint-row';

    const hint = document.createElement('div');
    hint.className = 'about-hint';
    hint.textContent = dataDirHint(data);
    hintRow.appendChild(hint);

    // 有待生效的落点才给重启按钮：它才是「重启后生效」的兑现方式。
    if (data.data_dir_next) {
      const restart = document.createElement('button');
      restart.type = 'button';
      restart.className = 'btn sm';
      restart.textContent = T('about.data_dir_restart');
      restart.addEventListener('click', restartApp);
      hintRow.appendChild(restart);
    }

    wrap.append(row, hintRow);
    return wrap;
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

    const handlesRow = document.createElement('div');
    handlesRow.className = 'field-row';
    const handlesLabel = document.createElement('span');
    handlesLabel.className = 'field-label';
    handlesLabel.textContent = T('settings.eight_handles');
    handlesRow.append(
      handlesLabel,
      toggle(data.eight_handles !== false, (value) => writeSettings({ eight_handles: value }))
    );
    body.appendChild(handlesRow);

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

    body.appendChild(section('about.title'));

    body.appendChild(field('about.data_dir', aboutBlock(data)));

    const readme = document.createElement('button');
    readme.type = 'button';
    readme.className = 'btn sm';
    readme.textContent = T('about.readme');
    readme.addEventListener('click', openReadme);
    body.appendChild(field('about.readme', readme));

    // 版本放在「关于」的最后：它是只读信息，不该占最显眼的一行。
    const versionRow = document.createElement('div');
    versionRow.className = 'field-row';
    const versionLabel = document.createElement('span');
    versionLabel.className = 'field-label';
    versionLabel.textContent = T('about.version');
    const versionValue = document.createElement('span');
    versionValue.className = 'about-value';
    versionValue.textContent = data.version || '';
    versionRow.append(versionLabel, versionValue);
    body.appendChild(versionRow);
  }

  renderBody();

  // 「重置所有」和「关闭」同一行，靠左：红字白底，悬停淡红
  const resetButton = document.createElement('button');
  resetButton.type = 'button';
  resetButton.className = 'btn soft-danger modal-leading';
  resetButton.textContent = T('settings.reset_all');
  // 带上键名，切语言时由 applyStrings() 一起刷新
  resetButton.dataset.i18n = 'settings.reset_all';
  resetButton.addEventListener('click', resetAll);

  await openModal({
    title: T('settings.title'),
    titleKey: 'settings.title',
    body,
    name: 'settings',
    leading: resetButton,
    actions: [{ label: T('dialog.close'), value: 'ok', kind: 'primary', i18n: 'dialog.close' }],
  });
}
