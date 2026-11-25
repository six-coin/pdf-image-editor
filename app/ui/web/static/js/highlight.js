/* 荧光笔：横向的黄色色带。

   视觉上用 CSS 的 mix-blend-mode: multiply 模拟「颜色叠加」——压在白纸上显色，
   压在纯黑上几乎看不出。PDF 那边对应的是 /ExtGState <</BM /Multiply>>，
   两边像素一致。

   只有黄色一种。色带只能挪位置，没有手柄，也没有调色面板。 */

import { call } from './bridge.js';
import { apply } from './render.js';
import { state } from './state.js';

const YELLOW = '#FFF066';

export function bandNode(obj, k) {
  const node = document.createElement('div');
  node.className = 'obj hl-band';
  node.dataset.id = obj.id;
  node.dataset.kind = 'highlight';
  node.style.left = `${obj.x * k}px`;
  node.style.top = `${obj.y * k}px`;
  node.style.width = `${obj.w * k}px`;
  node.style.height = `${obj.h * k}px`;
  node.style.background = obj.hex || YELLOW;
  if ((state.data.selection || []).includes(obj.id)) node.classList.add('selected');
  return node;
}

export async function createBand(pageIndex, x, y, width) {
  const snapshot = await call('create_highlight', pageIndex, x, y, width);
  if (snapshot) apply(snapshot);
}
