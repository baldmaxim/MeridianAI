import { afterEach, beforeEach, describe, it, expect } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { useMeetingStore } from '../../store/meetingStore';
import { SegmentText } from './SegmentText';
import type { CommittedSegmentWire } from '../../types';

const seg = (id: string, text: string, language: string): CommittedSegmentWire => ({
  segment_id: id, segment_key: id, speaker: 's', text, words: [], start_time: 0, end_time: 1,
  confidence: null, timestamp: '', server_ts_ms: 0, language,
});

describe('SegmentText (живая встреча)', () => {
  beforeEach(() => {
    useMeetingStore.setState({ committedSegments: [seg('a', 'Merhaba', 'tr'), seg('b', 'Хорошо', 'ru')], segmentTranslations: {} });
  });
  afterEach(cleanup);

  it('пока перевода нет — оригинал главным', () => {
    render(<SegmentText segmentIds={['a']} text="Merhaba" />);
    expect(screen.getByText('Merhaba')).toBeTruthy();
    expect(screen.queryByText(/оригинал/)).toBeNull();
  });

  it('после перевода главным становится перевод, оригинал — под ним', () => {
    useMeetingStore.setState({ segmentTranslations: { a: 'Здравствуйте' } });
    render(<SegmentText segmentIds={['a']} text="Merhaba" />);
    const translation = screen.getByText('Здравствуйте');
    const original = screen.getByText('Merhaba');
    expect(screen.getByText('TR · оригинал')).toBeTruthy();
    expect(translation.compareDocumentPosition(original) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('ход из нескольких реплик: русские остаются, иноязычные заменяются переводом', () => {
    useMeetingStore.setState({ segmentTranslations: { a: 'Здравствуйте' } });
    render(<SegmentText segmentIds={['a', 'b']} text="Merhaba Хорошо" />);
    expect(screen.getByText('Здравствуйте Хорошо')).toBeTruthy();
    expect(screen.getByText('Merhaba')).toBeTruthy();
  });
});
