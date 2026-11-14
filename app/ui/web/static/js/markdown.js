/* 使用说明的 Markdown 渲染。
   只覆盖手册里实际用到的语法：标题、段落、列表、表格、代码块、引用、分隔线、
   粗体、行内代码、链接。没有引入第三方库——一份手册不值得一个依赖。 */

function esc(value) {
  return String(value === undefined || value === null ? '' : value).replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]
  );
}

function inline(text) {
  const codes = [];
  let out = esc(text).replace(/`([^`]+)`/g, (match, code) => {
    codes.push(code);
    return `\u0000${codes.length - 1}\u0000`;
  });
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1');
  out = out.replace(/\u0000(\d+)\u0000/g, (match, index) => `<code>${codes[Number(index)]}</code>`);
  return out;
}

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

export function renderMarkdown(text) {
  const lines = String(text || '').replace(/\r\n/g, '\n').split('\n');
  const out = [];
  let paragraph = [];
  let index = 0;

  const flush = () => {
    if (!paragraph.length) return;
    out.push(`<p>${inline(paragraph.join(' '))}</p>`);
    paragraph = [];
  };

  while (index < lines.length) {
    const line = lines[index];

    if (/^```/.test(line)) {
      flush();
      index += 1;
      const code = [];
      while (index < lines.length && !/^```/.test(lines[index])) code.push(lines[index++]);
      index += 1;
      out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
      continue;
    }

    if (!line.trim()) {
      flush();
      index += 1;
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      const level = Math.min(6, heading[1].length + 1);
      out.push(`<h${level}>${inline(heading[2].trim())}</h${level}>`);
      index += 1;
      continue;
    }

    if (
      /^\s*\|/.test(line) &&
      index + 1 < lines.length &&
      /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[index + 1])
    ) {
      flush();
      const header = splitRow(line);
      index += 2;
      const rows = [];
      while (index < lines.length && /^\s*\|/.test(lines[index])) rows.push(splitRow(lines[index++]));
      out.push(
        `<table><thead><tr>${header.map((cell) => `<th>${inline(cell)}</th>`).join('')}</tr></thead><tbody>${rows
          .map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join('')}</tr>`)
          .join('')}</tbody></table>`
      );
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      flush();
      const items = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ''));
        index += 1;
      }
      out.push(`<ul>${items.map((item) => `<li>${inline(item)}</li>`).join('')}</ul>`);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      flush();
      const items = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ''));
        index += 1;
      }
      out.push(`<ol>${items.map((item) => `<li>${inline(item)}</li>`).join('')}</ol>`);
      continue;
    }

    if (/^>\s?/.test(line)) {
      flush();
      out.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`);
      index += 1;
      continue;
    }

    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) {
      flush();
      out.push('<hr>');
      index += 1;
      continue;
    }

    paragraph.push(line.trim());
    index += 1;
  }

  flush();
  const host = document.createElement('div');
  host.className = 'md';
  host.innerHTML = out.join('\n');
  return host;
}
