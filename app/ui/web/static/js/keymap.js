/* 键位表。
   两套作用域：global 与 split。分割模式下只认 split 表，所以两边的键可以重复
   而不冲突——这正是需求里说的"层级管理"。

   组合键用 event.code 归一化，避开 Shift 改变字符（Ctrl+Shift+S 与 Ctrl+S）
   和不同键盘布局带来的差异。 */

const GLOBAL_DEFS = [
  ['open', 'Ctrl+O', 'toolbar.open'],
  ['save', 'Ctrl+S', 'toolbar.save'],
  ['save_as', 'Ctrl+Shift+S', 'toolbar.save_as'],
  ['export', 'Ctrl+E', 'toolbar.export'],
  ['undo', 'Ctrl+Z', 'toolbar.undo'],
  ['redo', 'Ctrl+Y', 'toolbar.redo'],
  ['delete', 'Delete', 'toolbar.delete'],
  ['select_all', 'Ctrl+A', 'cmd.select_all'],
  ['paste', 'Ctrl+V', 'edit.paste'],
  ['zoom_in', 'Ctrl+=', 'toolbar.zoom_in'],
  ['zoom_out', 'Ctrl+-', 'toolbar.zoom_out'],
  ['zoom_fit', 'Ctrl+0', 'toolbar.fit_width'],
  ['zoom_reset', 'Ctrl+1', 'toolbar.zoom_reset'],
  ['split', 'E', 'toolbar.split'],
  ['front', 'Ctrl+U', 'toolbar.front'],
  ['back', 'Ctrl+L', 'toolbar.back'],
  ['external', 'Ctrl+Shift+E', 'inspector.external'],
  ['settings', 'Ctrl+,', 'toolbar.settings'],
  ['toggle_inspector', 'Ctrl+I', 'cmd.toggle_inspector'],
];

const SPLIT_DEFS = [
  ['split_keep', '1', 'split.keep'],
  ['split_punch', '2', 'split.extract'],
  ['split_all', 'R', 'split.all'],
  ['split_undo', 'Ctrl+Z', 'cmd.undo_cut'],
  ['split_cancel', 'Esc', 'dialog.cancel'],
];

function build(defs) {
  return {
    defaults: Object.fromEntries(defs.map(([id, accel]) => [id, accel])),
    commands: defs.map(([id, , labelKey]) => ({ id, labelKey })),
  };
}

const GLOBAL = build(GLOBAL_DEFS);
const SPLIT = build(SPLIT_DEFS);

export const DEFAULT_BINDINGS = {
  global: { ...GLOBAL.defaults },
  split: { ...SPLIT.defaults },
};

export const COMMANDS = {
  global: GLOBAL.commands,
  split: SPLIT.commands,
};

let tables = {
  global: { ...GLOBAL.defaults },
  split: { ...SPLIT.defaults },
};
let reverse = { global: new Map(), split: new Map() };

function rebuild() {
  for (const scope of ['global', 'split']) {
    const map = new Map();
    for (const [command, accel] of Object.entries(tables[scope])) {
      if (accel) map.set(accel, command);
    }
    reverse[scope] = map;
  }
}

rebuild();

/** 后端快照里的 keybindings 覆盖默认值；缺的项回落到默认。 */
export function setBindings(raw) {
  tables = {
    global: { ...GLOBAL.defaults, ...((raw && raw.global) || {}) },
    split: { ...SPLIT.defaults, ...((raw && raw.split) || {}) },
  };
  rebuild();
}

export function bindings() {
  return { global: { ...tables.global }, split: { ...tables.split } };
}

export function defaults() {
  return { global: { ...GLOBAL.defaults }, split: { ...SPLIT.defaults } };
}

export function lookup(scope, accel) {
  const map = reverse[scope];
  return map ? map.get(accel) || null : null;
}

export function accelFor(scope, command) {
  return tables[scope] ? tables[scope][command] : undefined;
}

/** 同一作用域里重复的组合键，返回冲突的 [accel, [commands]]。 */
export function findConflicts(table) {
  const seen = new Map();
  for (const [command, accel] of Object.entries(table)) {
    if (!accel) continue;
    if (!seen.has(accel)) seen.set(accel, []);
    seen.get(accel).push(command);
  }
  return [...seen.entries()].filter(([, commands]) => commands.length > 1);
}

const CODE_NAMES = {
  Equal: '=',
  Minus: '-',
  NumpadAdd: '=',
  NumpadSubtract: '-',
  Comma: ',',
  Period: '.',
  Slash: '/',
  Backslash: '\\',
  Semicolon: ';',
  Quote: "'",
  BracketLeft: '[',
  BracketRight: ']',
  Backquote: '`',
  Space: 'Space',
  Enter: 'Enter',
  NumpadEnter: 'Enter',
  Escape: 'Esc',
  Tab: 'Tab',
  Delete: 'Delete',
  Backspace: 'Backspace',
  ArrowUp: 'Up',
  ArrowDown: 'Down',
  ArrowLeft: 'Left',
  ArrowRight: 'Right',
  Home: 'Home',
  End: 'End',
  PageUp: 'PgUp',
  PageDown: 'PgDn',
};

function keyName(event) {
  const code = event.code || '';
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F\d{1,2}$/.test(code)) return code;
  if (CODE_NAMES[code]) return CODE_NAMES[code];
  const key = event.key || '';
  return key.length === 1 ? key.toUpperCase() : key;
}

/** 把一次按键归一化成 "Ctrl+Shift+S" 这样的字符串；纯修饰键返回 null。 */
export function accelOf(event) {
  const key = keyName(event);
  if (!key || ['Control', 'Shift', 'Alt', 'Meta', 'CapsLock'].includes(key)) return null;

  const parts = [];
  if (event.ctrlKey) parts.push('Ctrl');
  if (event.altKey) parts.push('Alt');
  // 单字符键的字符来自 code，Shift 不改变它；带 Ctrl/Alt 时 Shift 才是语义的一部分。
  if (event.shiftKey && (event.ctrlKey || event.altKey)) parts.push('Shift');
  if (event.metaKey) parts.push('Win');
  parts.push(key);
  return parts.join('+');
}

/** 只按了修饰键时不该触发任何动作，也不该被当成一次绑定。 */
export function isModifierOnly(event) {
  return accelOf(event) === null;
}
