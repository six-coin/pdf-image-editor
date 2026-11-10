/* 快照通道。
   全项目只有这里能"拉状态 + 落地渲染"：其它模块只负责触发一次刷新，
   不自己拼数据、不自己合并对象。这样后端模型永远是唯一真相。 */

import { call } from './bridge.js';
import { apply } from './render.js';

let timer = 0;

/** 立刻拉一次快照并渲染。 */
export async function refresh() {
  const snapshot = await call('get_state');
  if (snapshot) apply(snapshot);
  return snapshot;
}

/** 合并短时间内的多次刷新请求，避免一页页加载时把 DOM 反复重建。 */
export function scheduleRefresh(delay = 80) {
  if (timer) window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    timer = 0;
    refresh();
  }, delay);
}
