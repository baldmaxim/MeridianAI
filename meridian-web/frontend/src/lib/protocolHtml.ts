import type { BatchSegment } from '../api/batch';
import { fmtTime } from '../components/batch/batchDetailUtils';
import { parseInline, parseMarkdown } from './protocolMarkdown';
import { PROTOCOL_HTML_CSS, PROTOCOL_HTML_SCRIPT } from './protocolHtmlAssets';

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

/** «03:19» → 199, «1:02:03» → 3723; null, если это не время (секунды ≥ 60). */
const timecodeToSeconds = (tc: string): number | null => {
  const parts = tc.split(':').map(Number);
  if (parts.some((n) => Number.isNaN(n)) || parts[parts.length - 1] >= 60) return null;
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return parts[0] * 60 + parts[1];
};

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

const inlineHtml = (text: string, linkTimecodes: boolean): string =>
  parseInline(text)
    .map((n) => {
      if (n.type === 'strong') return `<strong>${textHtml(n.text, linkTimecodes)}</strong>`;
      if (n.type === 'code') return `<code>${escapeHtml(n.text)}</code>`;
      return textHtml(n.text, linkTimecodes);
    })
    .join('');

const protocolHtml = (md: string, link: boolean): string =>
  parseMarkdown(md)
    .map((b) => {
      switch (b.type) {
        case 'heading':
          return `<h3>${inlineHtml(b.text, link)}</h3>`;
        case 'ul':
          return `<ul>${b.items.map((it) => `<li>${inlineHtml(it, link)}</li>`).join('')}</ul>`;
        case 'ol':
          return `<ol start="${b.start}">${b.items.map((it) => `<li>${inlineHtml(it, link)}</li>`).join('')}</ol>`;
        case 'table': {
          const head = b.header.map((h) => `<th>${inlineHtml(h, link)}</th>`).join('');
          const body = b.rows
            .map((r) => `<tr>${r.map((c) => `<td>${inlineHtml(c, link)}</td>`).join('')}</tr>`)
            .join('');
          return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
        }
        case 'p':
          return `<p>${inlineHtml(b.text, link)}</p>`;
      }
    })
    .join('\n');

/** Цвет говорящего — по номеру в имени (как на сайте), 8 тонов. */
const speakerTone = (speaker: string): number => {
  const m = speaker.match(/(\d+)/);
  return (m ? parseInt(m[1], 10) : 0) % TONES_COUNT;
};

const segmentHtml = (s: BatchSegment): string => {
  const ru = s.text_ru ? `<div class="seg-ru">RU: ${escapeHtml(s.text_ru)}</div>` : '';
  return (
    `<div class="seg" data-start="${Number.isFinite(s.start) ? s.start : 0}">` +
    `<div class="seg-meta"><span class="seg-speaker t${speakerTone(s.speaker)}">${escapeHtml(s.speaker)}</span>` +
    `<span class="seg-time">${fmtTime(s.start)}</span></div>` +
    `<div class="seg-body">${escapeHtml(s.text)}${ru}</div></div>`
  );
};

/** Самодостаточный HTML протокола с офлайн-просмотрщиком транскрипции (аудио — файл рядом). */
export function buildProtocolHtml(opts: IProtocolHtmlOptions): string {
  const { title, createdAt, protocolMarkdown, segments, audioFileName } = opts;
  const hasAudio = !!audioFileName;
  const hasProtocol = !!protocolMarkdown?.trim();
  const hasSegments = segments.length > 0;

  const nav: string[] = [];
  if (hasProtocol) nav.push('<a href="#protocol">Протокол</a>');
  if (hasSegments) nav.push('<a href="#transcript">Транскрипция</a>');

  const audio = hasAudio
    ? `<audio id="player" controls preload="metadata" src="${encodeURIComponent(audioFileName)}"></audio>`
    : '';
  // плашка вне липкой шапки — на телефоне не съедает экран
  const audioErr = hasAudio
    ? '<div id="audio-err" class="audio-err" hidden>Аудио не найдено. Распакуйте архив целиком: файл записи должен лежать рядом с этим HTML.</div>'
    : '';
  const top = nav.length || hasAudio
    ? `<header class="top"><div class="top-in"><nav class="nav">${nav.join('')}<span class="nav-title">${escapeHtml(title)}</span></nav>${audio}</div></header>`
    : '';

  const sections: string[] = [];
  if (hasProtocol) {
    sections.push(`<section id="protocol"><h2>Протокол</h2>${protocolHtml(protocolMarkdown ?? '', hasAudio)}</section>`);
  }
  if (hasSegments) {
    sections.push(`<section id="transcript"><h2>Транскрипция</h2>${segments.map(segmentHtml).join('\n')}</section>`);
  }

  return [
    '<!doctype html>',
    '<html lang="ru">',
    '<head>',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    `<title>${escapeHtml(title)}</title>`,
    `<style>${PROTOCOL_HTML_CSS}</style>`,
    '</head>',
    `<body${hasAudio ? ' class="has-audio"' : ''}>`,
    top,
    '<main>',
    audioErr,
    `<h1>${escapeHtml(title)}</h1>`,
    createdAt ? `<p class="meta">${escapeHtml(createdAt)}</p>` : '',
    sections.join('\n'),
    '</main>',
    hasAudio ? `<script>${PROTOCOL_HTML_SCRIPT}</script>` : '',
    '</body>',
    '</html>',
    '',
  ].join('\n');
}
