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
