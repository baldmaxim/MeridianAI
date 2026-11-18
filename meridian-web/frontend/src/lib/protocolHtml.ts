import type { BatchSegment } from '../api/batch';
import { fmtTime } from '../components/batch/batchDetailUtils';
import { parseInline, parseMarkdown, timecodeToSeconds } from './protocolMarkdown';
import type { MdInline } from './protocolMarkdown';
import { PROTOCOL_HTML_CSS } from './protocolHtmlCss';
import { PROTOCOL_HTML_SCRIPT, PROTOCOL_HTML_THEME_INIT } from './protocolHtmlScript';

export interface IProtocolHtmlOptions {
  title: string;
  createdAt?: string;
  protocolMarkdown: string | null;
  segments: BatchSegment[];
  /** Имя аудио рядом с HTML (относительная ссылка); null — без плеера. */
  audioFileName: string | null;
}

const TONES_COUNT = 8;
const TIMECODE_RE = /\b\d{1,2}:\d{2}(?::\d{2})?\b/g;

export const escapeHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/** Экранированный текст; таймкоды — ссылки, если есть аудио. */
const textHtml = (text: string, linkTimecodes: boolean): string => {
  if (!linkTimecodes) return escapeHtml(text);
  let out = '';
  let last = 0;
  for (const m of text.matchAll(TIMECODE_RE)) {
    const sec = timecodeToSeconds(m[0]);
    if (sec == null) continue;
    out += escapeHtml(text.slice(last, m.index)) + `<a href="#" class="tc" data-t="${sec}">${m[0]}</a>`;
    last = m.index + m[0].length;
  }
  return out + escapeHtml(text.slice(last));
};

/** Узлы инлайн-разметки → HTML (strong может содержать mark/timecode). */
const nodesHtml = (nodes: MdInline[], link: boolean): string =>
  nodes
    .map((n) => {
      switch (n.type) {
        case 'strong':
          return `<strong>${n.children ? nodesHtml(n.children, link) : textHtml(n.text, link)}</strong>`;
        case 'code':
          return `<code>${escapeHtml(n.text)}</code>`;
        case 'mark':
          return `<mark>${escapeHtml(n.text)}</mark>`;
        case 'timecode':
          return `<span class="chip">${textHtml(n.text, link)}</span>`;
        case 'text':
          return textHtml(n.text, link);
      }
    })
    .join('');

/** summary — раздел «Краткое резюме»: числа маркером, таймкод чипом. */
const inlineHtml = (text: string, linkTimecodes: boolean, summary = false): string =>
  nodesHtml(parseInline(text, { highlight: summary }), linkTimecodes);

/** Протокол → HTML с теми же классами, что у MarkdownView на сайте. */
const protocolHtml = (md: string, link: boolean): string =>
  parseMarkdown(md)
    .map((b) => {
      switch (b.type) {
        case 'heading':
          return b.level <= 2
            ? `<h2 class="h2">${inlineHtml(b.text, link)}</h2>`
            : `<h3 class="h3">${inlineHtml(b.text, link)}</h3>`;
        case 'ul':
          return `<ul class="ul">${b.items.map((it) => `<li class="li">${inlineHtml(it, link, b.summary)}</li>`).join('')}</ul>`;
        case 'ol':
          return `<ol class="ul" start="${b.start}">${b.items.map((it) => `<li class="li">${inlineHtml(it, link, b.summary)}</li>`).join('')}</ol>`;
        case 'table': {
          const head = b.header.map((h) => `<th class="th">${inlineHtml(h, link)}</th>`).join('');
          const body = b.rows
            .map((r) => `<tr>${r.map((c) => `<td class="td">${inlineHtml(c, link)}</td>`).join('')}</tr>`)
            .join('');
          return `<div class="table-wrap"><table class="table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
        }
        case 'p':
          return `<p class="p">${inlineHtml(b.text, link, b.summary)}</p>`;
      }
    })
    .join('\n');

/** Цвет говорящего — по номеру в имени (как на сайте), 8 тонов. */
const speakerTone = (speaker: string): number => {
  const m = speaker.match(/(\d+)/);
  return (m ? parseInt(m[1], 10) : 0) % TONES_COUNT;
};

const segmentHtml = (s: BatchSegment): string => {
  // Иноязычная реплика: русский перевод главный, оригинал под ним
  const body = s.text_ru
    ? `<div class="seg-text">${escapeHtml(s.text_ru)}</div>` +
      `<div class="seg-orig"><span class="orig-tag">оригинал</span>${escapeHtml(s.text)}</div>`
    : `<div class="seg-text">${escapeHtml(s.text)}</div>`;
  return (
    `<div class="seg" data-start="${Number.isFinite(s.start) ? s.start : 0}">` +
    `<div class="seg-meta"><span class="seg-speaker t${speakerTone(s.speaker)}">${escapeHtml(s.speaker)}</span>` +
    `<span class="seg-time">${fmtTime(s.start)}</span></div>` +
    `<div class="seg-body">${body}</div></div>`
  );
};

const FONTS_URL =
  'https://fonts.googleapis.com/css2?family=Syne:wght@800&family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap';

type TabId = 'transcript' | 'protocol';

/** Самодостаточный HTML протокола: те же вкладки и оформление, что на сайте; аудио — файл рядом. */
export function buildProtocolHtml(opts: IProtocolHtmlOptions): string {
  const { title, createdAt, protocolMarkdown, segments, audioFileName } = opts;
  const hasAudio = !!audioFileName;
  const hasProtocol = !!protocolMarkdown?.trim();
  const hasSegments = segments.length > 0;
  // как на сайте: вкладки «Транскрипция | Протокол»; по умолчанию — протокол, если он есть
  const available: TabId[] = [];
  if (hasSegments) available.push('transcript');
  if (hasProtocol) available.push('protocol');
  const active: TabId | null = hasProtocol ? 'protocol' : hasSegments ? 'transcript' : null;

  const tabsHtml = available.length
    ? '<div class="tabs" role="tablist">' +
      available
        .map((id) => {
          const on = id === active;
          const label = id === 'transcript' ? 'Транскрипция' : 'Протокол';
          return `<button type="button" class="tab${on ? ' active' : ''}" role="tab" id="tab-${id}" data-tab="${id}" aria-selected="${on}" aria-controls="pane-${id}">${label}</button>`;
        })
        .join('') +
      '</div>'
    : '';

  const audio = hasAudio
    ? `<audio id="player" controls preload="metadata" src="${encodeURIComponent(audioFileName)}"></audio>`
    : '';
  const sticky = tabsHtml || audio ? `<div class="sticky">${tabsHtml}${audio}</div>` : '';
  // плашка вне липкой шапки — на телефоне не съедает экран
  const audioErr = hasAudio
    ? '<div id="audio-err" class="audio-err" hidden>Аудио не найдено. Распакуйте архив целиком: файл записи должен лежать рядом с этим HTML.</div>'
    : '';

  const pane = (id: TabId, label: string, cls: string, inner: string): string =>
    `<section class="pane${cls}" id="pane-${id}" data-pane="${id}" role="tabpanel" aria-labelledby="tab-${id}"${id === active ? '' : ' hidden'}>` +
    `<div class="print-h" aria-hidden="true">${label}</div>${inner}</section>`;
  const panes: string[] = [];
  if (hasProtocol) panes.push(pane('protocol', 'Протокол', ' card', `<div class="doc">${protocolHtml(protocolMarkdown ?? '', hasAudio)}</div>`));
  if (hasSegments) panes.push(pane('transcript', 'Транскрипция', '', `<div class="seg-list">${segments.map(segmentHtml).join('\n')}</div>`));

  return [
    '<!doctype html>',
    '<html lang="ru">',
    '<head>',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
    `<title>${escapeHtml(title)}</title>`,
    '<link rel="preconnect" href="https://fonts.googleapis.com">',
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
    `<link rel="stylesheet" href="${FONTS_URL}">`,
    `<script>${PROTOCOL_HTML_THEME_INIT}</script>`,
    `<style>${PROTOCOL_HTML_CSS}</style>`,
    '</head>',
    `<body${hasAudio ? ' class="has-audio"' : ''}>`,
    '<div class="page">',
    `<header class="head"><h1 class="file-name">${escapeHtml(title)}</h1>` +
      (createdAt ? `<span class="date">${escapeHtml(createdAt)}</span>` : '') +
      '<button type="button" id="theme-toggle" class="theme-btn" aria-label="Переключить тему">\u263E</button></header>',
    sticky,
    audioErr,
    panes.join('\n'),
    '</div>',
    `<script>${PROTOCOL_HTML_SCRIPT}</script>`,
    '</body>',
    '</html>',
    '',
  ].join('\n');
}
