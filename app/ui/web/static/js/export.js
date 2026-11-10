/* 导出选中页。页码解析以后端为准，这里只做输入时的即时预览。 */

import { call, T, toast } from './bridge.js';
import { openModal } from './modal.js';
import { state } from './state.js';

function parsePages(text, max) {
  const pages = new Set();
  for (const raw of String(text || '').replace(/\s/g, '').split(',')) {
    if (!raw) continue;
    const range = raw.match(/^(\d+)-(\d+)$/);
    if (range) {
      const start = Number(range[1]);
      const end = Number(range[2]);
      if (start <= end) {
        for (let page = Math.max(1, start); page <= Math.min(max, end); page += 1) {
          pages.add(page);
        }
      }
    } else if (/^\d+$/.test(raw)) {
      const page = Number(raw);
      if (page >= 1 && page <= max) pages.add(page);
    }
  }
  return [...pages].sort((a, b) => a - b);
}

export async function openExport() {
  const data = state.data;
  if (!data || !data.doc.page_count) return;
  if (data.doc.dirty) {
    toast(T('error.save_first'), false);
    return;
  }

  const body = document.createElement('div');
  body.className = 'export-form';

  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = '1-3,5,7-9';

  const preview = document.createElement('p');
  preview.className = 'hint';

  const refresh = () => {
    const pages = parsePages(input.value, data.doc.page_count);
    preview.textContent = pages.length
      ? T('export.preview', { count: pages.length, pages: pages.join(', ') })
      : T('export.empty');
  };
  input.addEventListener('input', refresh);

  const field = document.createElement('div');
  field.className = 'field';
  const label = document.createElement('label');
  label.textContent = T('export.range');
  field.append(label, input, preview);
  body.appendChild(field);
  refresh();

  const choice = await openModal({
    title: T('export.title'),
    text: T('export.hint'),
    body,
    narrow: true,
    actions: [
      { label: T('dialog.cancel'), value: 'cancel', kind: 'ghost' },
      { label: T('toolbar.export'), value: 'ok', kind: 'primary' },
    ],
  });
  if (choice !== 'ok') return;

  const text = input.value.trim();
  if (!parsePages(text, data.doc.page_count).length) {
    toast(T('export.empty'), false);
    return;
  }

  const stem = (data.doc.name || 'output.pdf').replace(/\.pdf$/i, '');
  const path = await call('browse_save', `${stem}-pages.pdf`);
  if (!path) return;

  const result = await call('export_pages', text, path);
  if (!result) return;
  if (!result.ok) {
    toast(result.message || T('error.unexpected'), false);
    return;
  }
  toast(T('export.done', { count: result.pages, path: result.path }));
}
