/* 把文件拖进窗口。
   这里只负责遮罩提示与阻止 WebView2 的默认行为：真实路径只有宿主拿得到，
   所以「打开」由后端的 drop 事件转回页面（见 main.js 的 window.host.dropPath）。 */

import { isOpen } from './modal.js';

// dragenter / dragleave 会在子元素之间反复触发，用计数判断「是不是真的离开了窗口」。
let depth = 0;

function hintEl() {
  return document.getElementById('dropHint');
}

function show(on) {
  const el = hintEl();
  if (!el) return;
  el.classList.toggle('hidden', !on);
}

function carriesFiles(event) {
  const types = event.dataTransfer && event.dataTransfer.types;
  return Boolean(types && Array.prototype.indexOf.call(types, 'Files') >= 0);
}

export function bindDropZone() {
  document.addEventListener('dragenter', (event) => {
    if (!carriesFiles(event)) return;
    depth += 1;
    if (!isOpen()) show(true);
  });

  // dragover 必须 preventDefault，否则浏览器根本不会触发 drop。
  document.addEventListener('dragover', (event) => {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
  });

  document.addEventListener('dragleave', (event) => {
    if (!carriesFiles(event)) return;
    depth = Math.max(0, depth - 1);
    // relatedTarget 为 null 说明指针离开了整个窗口（拖到桌面上松手也一样）。
    if (!depth || event.relatedTarget === null) {
      depth = 0;
      show(false);
    }
  });

  document.addEventListener('drop', (event) => {
    depth = 0;
    show(false);
    if (!carriesFiles(event)) return;
    // 别让 WebView2 把拖进来的 PDF 当成网页导航过去。
    event.preventDefault();
  });

  // 拖到窗口外松手时收不到 drop，靠失焦收尾。
  window.addEventListener('blur', () => {
    depth = 0;
    show(false);
  });
}
