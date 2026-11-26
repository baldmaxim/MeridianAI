import { afterEach, describe, it, expect, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { TranscriptRow } from './TranscriptRow';
import type { TranscriptSegmentRecord } from '../../types';

const base: TranscriptSegmentRecord = {
  segment_id: 's1', text: 'Merhaba', speaker_id: 'speaker_0', speaker_label: null,
  start_time: 0, end_time: 1, wall_clock: '2026-11-18T10:00:00', origin: 'live',
};

describe('TranscriptRow (история встречи)', () => {
  afterEach(cleanup);

  it('показывает бейдж языка, «Спикер N» и перевод из сохранённой записи', () => {
    render(<TranscriptRow segment={{
      ...base, language: 'tr', translation: 'Здравствуйте', diarized_speaker: 's1_speaker_0',
    }} />);
    expect(screen.getByText('TR · оригинал')).toBeTruthy();
    expect(screen.getByTitle('Говорящий по распознаванию голоса').textContent).toBe('Спикер 1');
    // перевод — главный (первый), оригинал — под ним
    const translation = screen.getByText('Здравствуйте');
    const original = screen.getByText('Merhaba');
    expect(translation.getAttribute('title')).toBe('Перевод на русский');
    expect(translation.compareDocumentPosition(original) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('без перевода иностранная реплика остаётся главной с бейджем языка', () => {
    render(<TranscriptRow segment={{ ...base, language: 'tr' }} />);
    expect(screen.getByText('TR')).toBeTruthy();
    expect(screen.getByText('Merhaba')).toBeTruthy();
    expect(screen.queryByText('TR · оригинал')).toBeNull();
  });

  it('старые записи без полей и русский язык — без бейджей и перевода', () => {
    render(<TranscriptRow segment={{ ...base, text: 'привет', language: 'ru' }} />);
    expect(screen.queryByTitle('Язык реплики')).toBeNull();
    expect(screen.queryByTitle('Перевод на русский')).toBeNull();
    expect(screen.queryByTitle('Говорящий по распознаванию голоса')).toBeNull();
  });

  it('показывает заданное имя и тег стороны', () => {
    render(<TranscriptRow segment={base} speakerName="Иван" side="opponent" />);
    expect(screen.getByText('Иван')).toBeTruthy();
    expect(screen.getByText('Оппонент')).toBeTruthy();
  });

  it('без имени метка человекочитаемая, без стороны — без тега', () => {
    render(<TranscriptRow segment={{ ...base, speaker_label: 'Speaker_speaker_1' }} />);
    expect(screen.getByText('Спикер 2')).toBeTruthy();
    expect(screen.queryByText('Мы')).toBeNull();
  });

  it('без onSeek строка не кнопка', () => {
    render(<TranscriptRow segment={base} />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('onSeek: клик и Enter/Space вызывают перемотку, активная строка выделяется', () => {
    const onSeek = vi.fn();
    render(<TranscriptRow segment={base} onSeek={onSeek} active />);
    const row = screen.getByRole('button');
    expect(row.getAttribute('tabindex')).toBe('0');
    expect(row.className).toContain('rowActive');
    fireEvent.click(row);
    fireEvent.keyDown(row, { key: 'Enter' });
    fireEvent.keyDown(row, { key: ' ' });
    expect(onSeek).toHaveBeenCalledTimes(3);
  });

  it('onSeek не вызывается при выделенном тексте', () => {
    const onSeek = vi.fn();
    const spy = vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => 'Merh' } as Selection);
    render(<TranscriptRow segment={base} onSeek={onSeek} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onSeek).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  describe('подсветка слов', () => {
    const audioRef = { current: document.createElement('audio') };
    const withWords: TranscriptSegmentRecord = {
      ...base, text: 'добрый день', language: 'ru',
      words: [{ text: 'добрый', start: 0, end: 0.4 }, { text: 'день', start: 0.5, end: 0.9 }],
    };

    it('активная строка со словами рендерит span-ы слов', () => {
      render(<TranscriptRow segment={withWords} active audioRef={audioRef} />);
      expect(screen.getByText('добрый').tagName).toBe('SPAN');
      expect(screen.getByText('день').tagName).toBe('SPAN');
    });

    it('с переводом — обычный текст без span-ов слов', () => {
      render(<TranscriptRow segment={{ ...withWords, translation: 'Добрый день' }} active audioRef={audioRef} />);
      expect(screen.queryByText('добрый')).toBeNull();
      expect(screen.getByText('добрый день')).toBeTruthy();
    });

    it('неактивная строка — без span-ов слов', () => {
      render(<TranscriptRow segment={withWords} audioRef={audioRef} />);
      expect(screen.queryByText('добрый')).toBeNull();
      expect(screen.getByText('добрый день')).toBeTruthy();
    });

    it('без audioRef — без span-ов слов', () => {
      render(<TranscriptRow segment={withWords} active />);
      expect(screen.queryByText('добрый')).toBeNull();
    });
  });
});
