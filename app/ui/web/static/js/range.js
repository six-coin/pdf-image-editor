/* 拖动条的填充比例。
   轨道是 CSS 渐变，JS 只负责把「已填充到百分之几」写进 --fill；
   设置面板和属性栏共用这一份，样式与行为不会走偏。 */

export function paintRange(range) {
  const min = Number(range.min) || 0;
  const max = Number(range.max) || 100;
  const value = Number(range.value) || 0;
  const ratio = max > min ? (value - min) / (max - min) : 0;
  const percent = Math.min(1, Math.max(0, ratio)) * 100;
  range.style.setProperty('--fill', `${percent}%`);
}
