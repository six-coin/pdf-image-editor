/* 弹窗。
   自绘对话框，支持 inert 背景、Tab 循环、Esc 关闭、进出场动画。 */

const EXIT_MS = 170;

let openCount = 0;

export function isOpen() {
  return openCount > 0;
}

function root() {
  return document.getElementById('modalRoot');
}

/** 只在没有弹窗时解除背景的 inert：弹窗可以嵌套（设置里再确认一次）。 */
function syncInert() {
  const app = document.getElementById('app');
  if (app) app.inert = openCount > 0;
}

/**
 * 打开一个弹窗。
 * @param {object} options
 * @param {string} options.title      标题（已本地化）
 * @param {string} [options.titleKey] 标题的文案键；给了就能跟着语言切换刷新
 * @param {string} [options.text]     正文（纯文本）
 * @param {Node}   [options.body]     自定义内容
 * @param {Array}  options.actions    [{label, value, kind, i18n}]；i18n 是按钮的文案键
 * @param {boolean}[options.narrow]   窄版
 * @param {string} [options.name]     给卡片打个标记，便于外部更新标题
 * @param {Node}   [options.leading]  页脚左侧的次要动作
 * @returns {Promise<string>}         选中的 value；Esc 或点遮罩返回 'cancel'
 */
export function openModal({
  title,
  titleKey = '',
  text,
  body,
  actions = [],
  narrow = false,
  name = '',
  leading = null,
}) {
  return new Promise((resolve) => {
    const host = root();

    const layer = document.createElement('div');
    layer.className = 'modal';

    const card = document.createElement('div');
    card.className = narrow ? 'modal-card narrow' : 'modal-card';
    card.tabIndex = -1;
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'true');
    if (name) card.dataset.modal = name;

    const head = document.createElement('div');
    head.className = 'modal-head';
    const heading = document.createElement('h2');
    heading.textContent = title;
    if (titleKey) heading.dataset.i18n = titleKey;
    head.appendChild(heading);

    card.appendChild(head);

    if (text) {
      const paragraph = document.createElement('p');
      paragraph.className = 'modal-text';
      paragraph.textContent = text;
      card.appendChild(paragraph);
    }

    if (body) {
      const box = document.createElement('div');
      box.className = 'modal-body';
      box.appendChild(body);
      card.appendChild(box);
    }

    const footer = document.createElement('div');
    footer.className = 'modal-actions';

    let settled = false;
    const lastFocus = document.activeElement;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      openCount = Math.max(0, openCount - 1);
      syncInert();
      close(layer, card);
      resolve(value);
    };

    // 放在左侧的次要动作，例如设置里的「重置所有」
    if (leading) footer.appendChild(leading);

    for (const action of actions) {
      const button = document.createElement('button');
      button.className = `btn ${action.kind || ''}`.trim();
      button.textContent = action.label;
      // 带上键名，语言切换时 applyStrings() 才能一起刷新；否则按钮会停在旧语言。
      if (action.i18n) button.dataset.i18n = action.i18n;
      button.addEventListener('click', () => finish(action.value));
      footer.appendChild(button);
    }
    card.appendChild(footer);

    layer.appendChild(card);
    layer.addEventListener('mousedown', (event) => {
      if (event.target === layer) finish('cancel');
    });

    host.appendChild(layer);
    openCount += 1;
    syncInert();
    card.focus();

    const onKey = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        finish('cancel');
        return;
      }
      if (event.key === 'Tab') trapTab(event, card);
    };
    layer.addEventListener('keydown', onKey);
    layer._cleanup = () => {
      layer.removeEventListener('keydown', onKey);
      if (lastFocus && lastFocus.isConnected) lastFocus.focus();
    };
  });
}

function close(layer, card) {
  layer.classList.add('leaving');
  window.setTimeout(() => {
    if (typeof layer._cleanup === 'function') layer._cleanup();
    layer.remove();
  }, EXIT_MS);
  card.blur();
}

function trapTab(event, card) {
  const focusable = card.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

/** 关闭握手用：页面里的"未保存"询问。 */
export function askUnsaved(labels) {
  return openModal({
    title: labels.title,
    text: labels.text,
    narrow: true,
    actions: [
      { label: labels.cancel, value: 'cancel', kind: 'ghost' },
      { label: labels.discard, value: 'discard', kind: 'danger-ghost' },
      { label: labels.save, value: 'save', kind: 'primary' },
    ],
  });
}
