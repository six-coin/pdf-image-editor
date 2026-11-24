/* 浮动工具栏的挂载与定位。
 *
 * 工具栏必须挂在 body 上、用 fixed 定位：
 * - 挂在页面里会被视口裁掉——元素在页面顶端时，工具栏跑到页面外面就看不见了；
 * - 挂在页面里时，点工具栏的 pointerdown 会冒泡到画布的 onDown，画布以为点了
 *   空白、清掉选中，工具栏随即消失（「点一下就跑了」）。
 *
 * 定位一律按窗口算，并且夹在窗口内：工具栏永远不出界面。
 */

import { pageEl } from './render.js';
import { pxPerPt } from './state.js';

const MARGIN = 8;
const GAP = 6;

export function mountFloat(el) {
  // 画布的手势都绑在视口上；工具栏不在视口里，再拦一道 pointerdown 更稳。
  el.addEventListener('pointerdown', (event) => event.stopPropagation());
  document.body.appendChild(el);
}

/** 把工具栏摆到对象上方；上方放不下就摆到下方，左右上下都夹进窗口。 */
export function placeFloat(el, obj) {
  const page = pageEl(obj.page);
  if (!page) return;
  const k = pxPerPt();
  const rect = page.getBoundingClientRect();
  const width = el.offsetWidth;
  const height = el.offsetHeight;
  const boxTop = rect.top + obj.y * k;
  const boxBottom = boxTop + obj.h * k;

  let top = boxTop - height - GAP;
  if (top < MARGIN) top = boxBottom + GAP;
  const left = rect.left + obj.x * k;

  const maxLeft = Math.max(MARGIN, window.innerWidth - width - MARGIN);
  const maxTop = Math.max(MARGIN, window.innerHeight - height - MARGIN);
  el.style.left = `${Math.min(Math.max(left, MARGIN), maxLeft)}px`;
  el.style.top = `${Math.min(Math.max(top, MARGIN), maxTop)}px`;
}
