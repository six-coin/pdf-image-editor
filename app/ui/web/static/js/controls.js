/* 通用表单控件。
   设置页和首次运行的语言选择共用同一套外观，避免两处各写一份、慢慢长歪。 */

/**
 * 分段选择器：一排互斥按钮，选中项高亮。
 * @param {Array<{value: string, label: string}>} options
 * @param {string} current 当前值
 * @param {(value: string) => void} onChange
 * @returns {HTMLDivElement}
 */
export function segmented(options, current, onChange) {
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


/* ---------- 自绘下拉框 ----------
   原生 <select> 的弹层由系统绘制，深色模式下没法控制。语言一多，分段控件
   又会把一行撑得很长，所以语言改用下拉：外观与音乐播放器的番茄钟编辑框一致。 */

function closeAllSelects(except) {
  document.querySelectorAll('.select.open').forEach((node) => {
    if (node === except) return;
    node.classList.remove('open');
    node.setAttribute('aria-expanded', 'false');
  });
}

document.addEventListener('click', () => closeAllSelects());
// 滚动或改窗口大小时菜单会飘走，直接收起。
window.addEventListener('resize', () => closeAllSelects());
window.addEventListener(
  'scroll',
  (event) => {
    if (event.target && event.target.closest && event.target.closest('.select-menu')) return;
    closeAllSelects();
  },
  true
);

/**
 * 自绘下拉框：点击展开选项，选中后回调。
 * @param {Array<{value: string, label: string}>} options
 * @param {string} current 当前值
 * @param {(value: string) => void} onChange
 * @returns {HTMLDivElement}
 */
export function selectBox(options, current, onChange) {
  const box = document.createElement('div');
  box.className = 'select';
  box.setAttribute('role', 'combobox');
  box.setAttribute('tabindex', '0');
  box.setAttribute('aria-haspopup', 'listbox');
  box.setAttribute('aria-expanded', 'false');

  const valueNode = document.createElement('span');
  valueNode.className = 'select-value';

  const arrow = document.createElement('span');
  arrow.innerHTML =
    '<svg class="select-arrow" viewBox="0 0 12 12" aria-hidden="true">' +
    '<path d="M2.5 4.5L6 8l3.5-3.5"/></svg>';

  const menu = document.createElement('div');
  menu.className = 'select-menu';
  menu.setAttribute('role', 'listbox');

  let value = current;

  function labelOf(target) {
    const hit = options.find((item) => item.value === target);
    return hit ? hit.label : options.length ? options[0].label : '';
  }

  function close() {
    box.classList.remove('open');
    box.setAttribute('aria-expanded', 'false');
  }

  function paint() {
    valueNode.textContent = labelOf(value);
    box.dataset.value = value;
    menu.innerHTML = '';
    for (const option of options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'select-option' + (option.value === value ? ' active' : '');
      button.setAttribute('role', 'option');
      button.dataset.value = option.value;
      button.textContent = option.label;
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        const next = option.value;
        if (next === value) {
          close();
          return;
        }
        value = next;
        paint();
        close();
        onChange(next);
      });
      menu.appendChild(button);
    }
  }

  /* 菜单按视口定位：首次运行那种矮弹窗里，绝对定位的菜单会被卡片裁掉。 */
  function placeMenu() {
    const rect = box.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.right = 'auto';
    menu.style.left = rect.left + 'px';
    menu.style.minWidth = rect.width + 'px';
    menu.style.width = 'auto';
    // 菜单比控件宽时可能顶到窗口右边，量完宽度再往里收。
    const width = menu.offsetWidth;
    menu.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)) + 'px';
    const height = menu.offsetHeight;
    let top = rect.bottom + 6;
    if (top + height > window.innerHeight - 8 && rect.top - height - 6 > 8) {
      top = rect.top - height - 6;
    }
    menu.style.top = Math.max(8, top) + 'px';
  }

  function toggle() {
    const open = !box.classList.contains('open');
    closeAllSelects(box);
    box.classList.toggle('open', open);
    box.setAttribute('aria-expanded', String(open));
    if (open) placeMenu();
  }

  box.addEventListener('click', (event) => {
    // 不让这次点击冒泡到 document，否则刚展开就被「点别处收起」关掉。
    event.stopPropagation();
    toggle();
  });

  box.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      event.stopPropagation();
      toggle();
    } else if (event.key === 'Escape') {
      event.stopPropagation();
      close();
    }
  });

  box.append(valueNode, arrow, menu);
  paint();
  box.setValue = (next) => {
    value = next;
    paint();
  };
  return box;
}
