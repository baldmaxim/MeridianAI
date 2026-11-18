import type { StateCreator } from 'zustand';
import type { IMeetingStore, ITranscriptSlice } from './types';

let messageCounter = 0;

export const createTranscriptSlice: StateCreator<IMeetingStore, [], [], ITranscriptSlice> = (set) => ({
  messages: [],
  committedSegments: [],
  addMessage: (msg) =>
    set((s) => ({
      messages: [...s.messages, { ...msg, id: msg.id || String(++messageCounter) }],
    })),
  segmentTranslations: {},
  segmentSpeakers: {},
  setSegmentTranslation: (segmentId, text) =>
    set((s) => ({ segmentTranslations: { ...s.segmentTranslations, [segmentId]: text } })),
  setSegmentSpeaker: (segmentId, speaker) =>
    set((s) => ({ segmentSpeakers: { ...s.segmentSpeakers, [segmentId]: speaker } })),
  addCommittedSegment: (seg) =>
    set((s) => ({
      committedSegments: [...s.committedSegments, seg],
      // Also add to messages for backward-compat display
      messages: [...s.messages, {
        id: seg.segment_id,
        speaker: seg.speaker,
        text: seg.text,
        timestamp: seg.timestamp,
        is_partial: false,
      }],
    })),
  replaceBatchSegments: (segs) =>
    set({
      committedSegments: segs,
      messages: segs.map((seg) => ({
        id: seg.segment_id,
        speaker: seg.speaker,
        text: seg.text,
        timestamp: seg.timestamp,
        is_partial: false,
      })),
      turns: [],
      segmentTranslations: {},
      segmentSpeakers: {},
    }),
  partialMessage: null,
  updatePartial: (msg) =>
    set({ partialMessage: { ...msg, id: msg.id || 'partial' } }),
  clearPartial: () =>
    set({ partialMessage: null }),

  turns: [],
  handleTurnUpdate: (turn) =>
    set((s) => {
      const idx = s.turns.findIndex((t) => t.turn_id === turn.turn_id);
      if (idx >= 0) {
        const updated = [...s.turns];
        updated[idx] = turn;
        return { turns: updated };
      }
      return { turns: [...s.turns, turn] };
    }),
  resetTurns: () => set({ turns: [] }),
});
