import { afterEach, describe, it, expect } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
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
    expect(screen.getByText('TR')).toBeTruthy();
    expect(screen.getByText('Спикер 1')).toBeTruthy();
    expect(screen.getByText('Здравствуйте')).toBeTruthy();
  });

  it('старые записи без полей и русский язык — без бейджей и перевода', () => {
    render(<TranscriptRow segment={{ ...base, text: 'привет', language: 'ru' }} />);
    expect(screen.queryByTitle('Язык реплики')).toBeNull();
    expect(screen.queryByTitle('Перевод на русский')).toBeNull();
    expect(screen.queryByTitle('Говорящий по распознаванию голоса')).toBeNull();
  });
});
