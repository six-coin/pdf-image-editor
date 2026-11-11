/* 导出选中页。页码解析以后端为准，这里只做输入时的即时预览。 */

import { call, T, toast } from './bridge.js';
import { openModal } from './modal.js';
import { state } from './state.js';

function parsePages(text, max) {
  const pages = new Set();
  // 中文逗号与全角空格都要认，否则预览说「没有可用的页码」而导出却成功。
  const normalized = String(text || '')
    .replace(/，/g, ',')
    .replace(/[\s\u3000]/g, '');
  for (const raw of normalized.split(',')) {
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

const PROBLEM_KEYS = {
  reversed: 'error.page_range_reversed',
  out_of_range: 'error.page_range_out_of_bounds',
  bad_token: 'error.page_range_bad',
};

/** 被跳过的片段必须列出来：少导了页却不吭声，用户要等打开文件才发现。 */
async function showProblems(problems, total) {
  if (!problems.length) return;

  const body = document.createElement('div');
  body.className = 'warning-list';
  for (const problem of problems) {
    const row = document.createElement('div');
    row.className = 'warning-row';
    const token = document.createElement('span');
    token.className = 'chip warn';
    token.textContent = problem.token;
    const text = document.createElement('span');
    text.textContent = T(PROBLEM_KEYS[problem.code] || 'error.unexpected', {
      token: problem.token,
      total,
    });
    row.append(token, text);
    body.appendChild(row);
  }

  await openModal({
    title: T('export.skipped', { count: problems.length }),
    body,
    narrow: true,
    actions: [{ label: T('dialog.close'), value: 'ok', kind: 'primary' }],
  });
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
  await showProblems(result.errors || [], data.doc.page_count);
}
