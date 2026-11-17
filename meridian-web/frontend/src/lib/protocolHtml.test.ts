import { describe, expect, it } from 'vitest';
import { buildProtocolHtml } from './protocolHtml';
import type { BatchSegment } from '../api/batch';

const seg = (over: Partial<BatchSegment> = {}): BatchSegment => ({
  speaker: 'Спикер 1', start: 0, end: 5, text: 'Привет', ...over,
});

const build = (over: Partial<Parameters<typeof buildProtocolHtml>[0]> = {}) =>
  buildProtocolHtml({
    title: 'Встреча',
    protocolMarkdown: null,
    segments: [seg()],
    audioFileName: null,
    ...over,
  });

describe('buildProtocolHtml', () => {
  it('экранирует <script> в тексте реплики и заголовке', () => {
    const html = build({
      title: '<b>"x"</b>',
      segments: [seg({ text: '<script>alert(1)</script>' })],
    });
    expect(html).not.toContain('<script>alert(1)</script>');
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).toContain('<title>&lt;b&gt;&quot;x&quot;&lt;/b&gt;</title>');
  });

  it('таймкод протокола → ссылка data-t при наличии аудио', () => {
    const html = build({ protocolMarkdown: 'Обсудили сроки (03:19–04:34).', audioFileName: 'a.mp3' });
    expect(html).toContain('<a href="#" class="tc" data-t="199">03:19</a>');
    expect(html).toContain('data-t="274"');
  });

  it('без аудио таймкод — обычный текст', () => {
    const html = build({ protocolMarkdown: 'Обсудили сроки (03:19).' });
    expect(html).toContain('(03:19)');
    expect(html).not.toContain('class="tc"');
  });

  it('нумерованный список одной строкой → <ol> с 2 <li>', () => {
    const html = build({ protocolMarkdown: '1. А (01:00). 2. Б (02:00).' });
    expect(html).toContain('<ol class="ul" start="1">');
    expect(html.match(/<li class="li">/g)).toHaveLength(2);
  });

  it('без аудио нет <audio> и плашки ошибки, скрипт (вкладки/тема) есть', () => {
    const html = build({ audioFileName: null });
    expect(html).not.toContain('<audio');
    expect(html).not.toContain('id="audio-err"');
    expect(html).toContain('<script>');
  });

  it('две вкладки «Транскрипция | Протокол», по умолчанию открыт протокол', () => {
    const html = build({ protocolMarkdown: '## 1. Итог\n- а' });
    expect(html.indexOf('data-tab="transcript"')).toBeLessThan(html.indexOf('data-tab="protocol"'));
    expect(html).toMatch(/class="tab active"[^>]*data-tab="protocol"/);
    expect(html).toMatch(/id="pane-transcript"[^>]* hidden>/);
    expect(html).not.toMatch(/id="pane-protocol"[^>]* hidden>/);
    expect(html).toContain('<h2 class="h2">1. Итог</h2>');
  });

  it('вкладка без содержимого не выводится; без протокола открыта транскрипция', () => {
    const html = build({ protocolMarkdown: null });
    expect(html).not.toContain('data-tab="protocol"');
    expect(html).toMatch(/class="tab active"[^>]*data-tab="transcript"/);
    const onlyProtocol = build({ protocolMarkdown: 'Текст', segments: [] });
    expect(onlyProtocol).not.toContain('data-tab="transcript"');
  });

  it('кнопка темы, data-theme и prefers-color-scheme, localStorage в try/catch', () => {
    const html = build();
    expect(html).toContain('id="theme-toggle"');
    expect(html).toContain('aria-label="Переключить тему"');
    expect(html).toContain('data-theme');
    expect(html).toContain('prefers-color-scheme');
    expect(html).toMatch(/try\{[^}]*localStorage/);
  });

  it('«Краткое резюме»: числа в mark, таймкод — чип со ссылками при аудио', () => {
    const md = '## 3. Краткое резюме\n1. Цена 150 000 руб./м² и аванс 30% (24:50–25:41).\n\n## 4. Вопросы\n- Цена 150 000 руб./м²';
    const html = build({ protocolMarkdown: md, audioFileName: 'a.mp3' });
    expect(html).toContain('<mark>150 000 руб./м²</mark>');
    expect(html).toContain('<mark>30%</mark>');
    expect(html).toContain('<span class="chip">(<a href="#" class="tc" data-t="1490">24:50</a>–<a href="#" class="tc" data-t="1541">25:41</a>)</span>');
    // вне резюме — без mark
    expect(html.match(/<mark>/g)).toHaveLength(2);
  });

  it('экранирует HTML внутри резюме и жирного', () => {
    const md = '## Краткое резюме\n1. **<b>x</b> 30%** <i>y</i>';
    const html = build({ protocolMarkdown: md });
    expect(html).toContain('&lt;b&gt;x&lt;/b&gt;');
    expect(html).toContain('<strong>&lt;b&gt;x&lt;/b&gt; <mark>30%</mark></strong>');
    expect(html).toContain('&lt;i&gt;y&lt;/i&gt;');
    expect(html).not.toContain('<i>y');
  });

  it('имя аудио кодируется в src', () => {
    const html = build({ audioFileName: 'тест запись.mp3' });
    expect(html).toContain(`src="${encodeURIComponent('тест запись.mp3')}"`);
    expect(html).toContain('<audio id="player" controls preload="metadata"');
  });

  it('реплика содержит data-start и время', () => {
    const html = build({ segments: [seg({ start: 3725, text: 'ок' })] });
    expect(html).toContain('data-start="3725"');
    expect(html).toContain('1:02:05');
  });
});
