/* 桥接封装。
   所有 Python 调用都走 call()，业务代码里不直接写 window.pywebview.api.xxx。 */

import { state } from './state.js';

function host() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

export function bridgeReady() {
  return Boolean(host());
}

export async function call(method, ...args) {
  const api = host();
  if (!api) return null;
  try {
    return await api[method](...args);
  } catch (error) {
    console.error(method, error);
    toast(T('error.unexpected'), false);
    return null;
  }
}

export function setStrings(table) {
  state.strings = table || {};
}

export function T(key, params) {
  const text = state.strings[key];
  if (text === undefined) return key;
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
  );
}

/* ---------- 状态栏 ----------
   底部居中的圆角黑条，是界面上唯一的临时提示出口：错误、成功、进行中都在这里，
   不再另造横幅。容器底边固定，条目按加入顺序从下往上堆，最多同时显示三条。

   新的一条从下方淡入，已有的几条同时往上挪一格；满了三条还要再来一条时，最老的
   那条一边往上飘一边渐隐，位置由剩下的三条接上。 */

const TOAST_MS = 2400;
const TOAST_ERROR_MS = 4200;
const TOAST_MAX = 3;

/** 记下每条现在的位置，等 DOM 改完再按位移补动画。 */
function snapshot(root) {
  const map = new Map();
  for (const node of root.children) map.set(node, node.getBoundingClientRect().top);
  return map;
}

/** 把「被顶上去」的位移反向补回来再归零：看起来就是往上挪了一格，而不是跳一格。 */
function settle(map) {
  for (const [node, top] of map) {
    if (!node.isConnected) continue;
    const delta = top - node.getBoundingClientRect().top;
    if (!delta) continue;
    node.style.transition = 'none';
    node.style.transform = `translateY(${delta}px)`;
    // 强制回流：否则下一帧的 transition 会从同一个值开始，等于没动。
    void node.offsetHeight;
    node.style.transition = 'transform 0.2s var(--ease)';
    node.style.transform = '';
  }
}

/** 让一条原地脱离文档流再飘走，后面的条目不会跟着往下掉。 */
function retire(node) {
  if (!node.isConnected) return;
  const rect = node.getBoundingClientRect();
  const ghost = node.cloneNode(true);
  ghost.classList.remove('is-entering', 'is-leaving');
  ghost.style.position = 'fixed';
  ghost.style.left = `${rect.left}px`;
  ghost.style.top = `${rect.top}px`;
  // 量出来的宽高要写死：离开容器后它是一块普通的 div，会撑满整行。
  ghost.style.width = `${rect.width}px`;
  ghost.style.height = `${rect.height}px`;
  ghost.style.margin = '0';
  ghost.style.pointerEvents = 'none';
  ghost.style.animation = 'toast-out 0.2s ease forwards';
  document.body.appendChild(ghost);
  window.setTimeout(() => ghost.remove(), 240);
  node.remove();
}

function dismiss(node) {
  if (!node.isConnected || node.classList.contains('is-leaving')) return;
  const map = snapshot(node.parentElement);
  retire(node);
  settle(map);
}

/**
 * 弹一条状态。
 *
 * ``ok`` 为 false 时是错误样式，停留更久。``sticky`` 用于「正在做什么」这类
 * 需要一直在场的提示：不自动消失，返回的句柄负责收尾。
 */
export function toast(text, ok = true, options = {}) {
  const root = document.getElementById('toastRoot');
  // 状态栏永远不带句号，这里是最后一道保险。
  const body = String(text === undefined || text === null ? '' : text)
    .trim()
    .replace(/[。.]+$/, '');
  if (!root || !body) return null;

  const map = snapshot(root);
  while (root.children.length >= TOAST_MAX) retire(root.firstElementChild);

  const node = document.createElement('div');
  node.className = ok ? 'toast' : 'toast error';
  node.textContent = body;
  node.classList.add('is-entering');
  root.appendChild(node);
  settle(map);

  if (options.busy) {
    const spinner = document.createElement('i');
    spinner.className = 'spinner';
    spinner.setAttribute('aria-hidden', 'true');
    node.prepend(spinner);
  }

  let timer = 0;
  const handle = {
    close() {
      window.clearTimeout(timer);
      dismiss(node);
    },
  };

  if (!options.sticky) {
    timer = window.setTimeout(() => dismiss(node), ok ? TOAST_MS : TOAST_ERROR_MS);
  }
  return handle;
}
