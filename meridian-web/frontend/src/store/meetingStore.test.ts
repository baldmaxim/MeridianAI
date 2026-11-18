import { describe, it, expect, beforeEach } from 'vitest';
import { useMeetingStore } from './meetingStore';
import type { CommittedSegmentWire, Suggestion } from '../types';

const initial = useMeetingStore.getState();

describe('meetingStore', () => {
  beforeEach(() => {
    useMeetingStore.getState().reset();
  });

  it('initial state содержит ключи и значения по умолчанию', () => {
    const s = initial;
    for (const key of [
      'isConnected', 'isListening', 'messages', 'committedSegments', 'turns', 'suggestions',
      'currentSuggestionIndex', 'documents', 'meetingStats', 'statusMessage', 'meetingName',
      'negotiationType', 'speakerRoles', 'maxSpeakers', 'conversationTree', 'treePanelOpen',
      'uiMode', 'currentMeetingId', 'participants', 'multiChannelLiveFinalSegments',
      'multiChannelReconciliation', 'transcriptionAuthority', 'reset', 'newMeetingSession',
      'addCommittedSegment', 'addSuggestion', 'setListening',
    ]) {
      expect(s).toHaveProperty(key);
    }
    expect(s.statusMessage).toBe('Готов к работе');
    expect(s.negotiationType).toBe('sale');
    expect(s.maxSpeakers).toBe(3);
    expect(s.currentSuggestionIndex).toBe(-1);
    expect(s.treePanelOpen).toBe(true);
    expect(s.uiMode).toBe('simple');
    expect(s.meetingStats).toEqual({
      positionStrength: 0, suggestionsUsed: 0, activeObjections: 0, meetingStartTime: null,
    });
  });

  it('addCommittedSegment добавляет сегмент и сообщение', () => {
    const seg = {
      segment_id: 'seg-1', speaker: 'A', text: 'привет', timestamp: '10:00',
    } as CommittedSegmentWire;
    useMeetingStore.getState().addCommittedSegment(seg);
    const s = useMeetingStore.getState();
    expect(s.committedSegments).toHaveLength(1);
    expect(s.messages).toEqual([
      { id: 'seg-1', speaker: 'A', text: 'привет', timestamp: '10:00', is_partial: false },
    ]);
  });

  it('перевод и метка говорящего хранятся по segment_id и сбрасываются', () => {
    const st = useMeetingStore.getState();
    st.setSegmentTranslation('seg-1', 'Здравствуйте');
    st.setSegmentSpeaker('seg-1', 's1_speaker_0');
    expect(useMeetingStore.getState().segmentTranslations).toEqual({ 'seg-1': 'Здравствуйте' });
    expect(useMeetingStore.getState().segmentSpeakers).toEqual({ 'seg-1': 's1_speaker_0' });
    useMeetingStore.getState().newMeetingSession();
    expect(useMeetingStore.getState().segmentTranslations).toEqual({});
    expect(useMeetingStore.getState().segmentSpeakers).toEqual({});
  });

  it('addSuggestion обновляет индекс, статистику и время', () => {
    useMeetingStore.getState().addSuggestion({ id: 's1' } as unknown as Suggestion);
    const s = useMeetingStore.getState();
    expect(s.suggestions).toHaveLength(1);
    expect(s.currentSuggestionIndex).toBe(0);
    expect(s.meetingStats.suggestionsUsed).toBe(1);
    expect(s.lastSuggestionTime).not.toBeNull();
  });

  it('setListening ставит время старта, reset сбрасывает', () => {
    useMeetingStore.getState().setListening(true);
    expect(useMeetingStore.getState().isListening).toBe(true);
    expect(useMeetingStore.getState().meetingStats.meetingStartTime).not.toBeNull();
    useMeetingStore.getState().setMeetingName('X');
    useMeetingStore.getState().reset();
    const s = useMeetingStore.getState();
    expect(s.isListening).toBe(false);
    expect(s.meetingName).toBe('');
    expect(s.meetingStats.meetingStartTime).toBeNull();
    expect(s.suggestions).toEqual([]);
  });
});
