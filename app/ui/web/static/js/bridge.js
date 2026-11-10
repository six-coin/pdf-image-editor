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

let toastTimer = 0;

export function toast(text, ok = true) {
  const root = document.getElementById('toastRoot');
  if (!root || !text) return;
  root.innerHTML = '';
  const node = document.createElement('div');
  node.className = ok ? 'toast' : 'toast error';
  // 状态栏永远不带句号，这里是最后一道保险。
  node.textContent = String(text).replace(/[。.]$/, '');
  root.appendChild(node);

  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    node.classList.add('leaving');
    window.setTimeout(() => node.remove(), 200);
  }, 2400);
}
