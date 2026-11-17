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
    expect(html).toContain('<ol start="1">');
    expect(html.match(/<li>/g)).toHaveLength(2);
  });

  it('без аудио нет <audio> и скрипта', () => {
    const html = build({ audioFileName: null });
    expect(html).not.toContain('<audio');
    expect(html).not.toContain('<script>');
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
