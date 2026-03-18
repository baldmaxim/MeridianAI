import { create } from 'zustand';
import type { ChatMessage, Suggestion, DocumentInfo, CommittedSegmentWire, SuggestionTypeConfig } from '../types';

interface MeetingStats {
  positionStrength: number;
  suggestionsUsed: number;
  activeObjections: number;
  meetingStartTime: number | null;
}

interface MeetingState {
  // Connection
  isConnected: boolean;
  isListening: boolean;

  // Transcript
  messages: ChatMessage[];
  committedSegments: CommittedSegmentWire[];
  addMessage: (msg: ChatMessage) => void;
  addCommittedSegment: (seg: CommittedSegmentWire) => void;
  replaceBatchSegments: (segs: CommittedSegmentWire[]) => void;
  updatePartial: (msg: ChatMessage) => void;
  clearPartial: () => void;

  // Suggestions
  suggestions: Suggestion[];
  currentSuggestionIndex: number;
  currentStreamingText: string | null;
  suggestionLoading: boolean;
  strengthenLoading: boolean;
  addSuggestion: (s: Suggestion) => void;
  setStreamingText: (text: string | null) => void;
  setSuggestionLoading: (loading: boolean) => void;
  setStrengthenLoading: (loading: boolean) => void;
  navigateSuggestion: (direction: 'prev' | 'next') => void;

  // Documents
  documents: DocumentInfo[];
  addDocument: (doc: DocumentInfo) => void;
  removeDocument: (filename: string) => void;
  setDocuments: (docs: DocumentInfo[]) => void;

  // Stats
  meetingStats: MeetingStats;
  updateStats: (partial: Partial<MeetingStats>) => void;
  lastSuggestionTime: number | null;

  // Analysis status (shown in suggestion panel)
  analysisStatus: string | null;
  setAnalysisStatus: (status: string | null) => void;

  // Status
  statusMessage: string;
  setStatus: (msg: string) => void;

  // Error
  lastError: string | null;
  setError: (msg: string | null) => void;

  // Meeting context
  meetingTopic: string;
  meetingNotes: string;
  negotiationType: string;
  meetingRole: string;
  opponentWeaknesses: string;
  setMeetingTopic: (t: string) => void;
  setMeetingNotes: (n: string) => void;
  setNegotiationType: (t: string) => void;
  setMeetingRole: (r: string) => void;
  setOpponentWeaknesses: (w: string) => void;

  // Connection state
  setConnected: (connected: boolean) => void;
  setListening: (listening: boolean) => void;

  // Custom suggestion types
  customSuggestionTypes: SuggestionTypeConfig[] | null;
  setCustomSuggestionTypes: (types: SuggestionTypeConfig[] | null) => void;

  // Meeting saved
  meetingSavedId: number | null;
  setMeetingSavedId: (id: number | null) => void;

  // Reset
  reset: () => void;
}

let messageCounter = 0;

export const useMeetingStore = create<MeetingState>((set) => ({
  isConnected: false,
  isListening: false,

  messages: [],
  committedSegments: [],
  addMessage: (msg) =>
    set((s) => ({
      messages: [...s.messages, { ...msg, id: msg.id || String(++messageCounter) }],
    })),
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
    }),
  updatePartial: (msg) =>
    set((s) => {
      const msgs = [...s.messages];
      // Find last partial message and update it, or add new
      const lastIdx = msgs.findLastIndex((m: ChatMessage) => m.is_partial);
      if (lastIdx >= 0) {
        msgs[lastIdx] = { ...msg, id: msgs[lastIdx].id };
      } else {
        msgs.push({ ...msg, id: String(++messageCounter) });
      }
      return { messages: msgs };
    }),
  clearPartial: () =>
    set((s) => ({
      messages: s.messages.filter((m: ChatMessage) => !m.is_partial),
    })),

  suggestions: [],
  currentSuggestionIndex: -1,
  currentStreamingText: null,
  suggestionLoading: false,
  strengthenLoading: false,

  addSuggestion: (s) =>
    set((state) => {
      const suggestions = [...state.suggestions, s];
      if (suggestions.length > 100) suggestions.shift();
      return {
        suggestions,
        currentSuggestionIndex: suggestions.length - 1,
        currentStreamingText: null,
        lastSuggestionTime: Date.now(),
        meetingStats: { ...state.meetingStats, suggestionsUsed: state.meetingStats.suggestionsUsed + 1 },
      };
    }),
  setStreamingText: (text) => set({ currentStreamingText: text }),
  setSuggestionLoading: (loading) => set({ suggestionLoading: loading }),
  setStrengthenLoading: (loading) => set({ strengthenLoading: loading }),
  navigateSuggestion: (direction) =>
    set((s) => {
      const len = s.suggestions.length;
      if (len === 0) return {};
      let idx = s.currentSuggestionIndex;
      if (direction === 'prev') idx = Math.max(0, idx - 1);
      else idx = Math.min(len - 1, idx + 1);
      return { currentSuggestionIndex: idx, currentStreamingText: null };
    }),

  documents: [],
  addDocument: (doc) => set((s) => ({ documents: [...s.documents, doc] })),
  removeDocument: (filename) =>
    set((s) => ({ documents: s.documents.filter((d) => d.filename !== filename) })),
  setDocuments: (docs) => set({ documents: docs }),

  meetingStats: { positionStrength: 0, suggestionsUsed: 0, activeObjections: 0, meetingStartTime: null },
  updateStats: (partial) => set((s) => ({ meetingStats: { ...s.meetingStats, ...partial } })),
  lastSuggestionTime: null,

  analysisStatus: null,
  setAnalysisStatus: (status) => set({ analysisStatus: status }),

  statusMessage: 'Готов к работе',
  setStatus: (msg) => set({ statusMessage: msg }),

  lastError: null,
  setError: (msg) => set({ lastError: msg }),

  meetingTopic: '',
  meetingNotes: '',
  negotiationType: 'sale',
  meetingRole: '',
  opponentWeaknesses: '',
  setMeetingTopic: (t) => set({ meetingTopic: t }),
  setMeetingNotes: (n) => set({ meetingNotes: n }),
  setNegotiationType: (t) => set({ negotiationType: t }),
  setMeetingRole: (r) => set({ meetingRole: r }),
  setOpponentWeaknesses: (w) => set({ opponentWeaknesses: w }),

  customSuggestionTypes: null,
  setCustomSuggestionTypes: (types) => set({ customSuggestionTypes: types }),

  meetingSavedId: null,
  setMeetingSavedId: (id) => set({ meetingSavedId: id }),

  setConnected: (connected) => set({ isConnected: connected }),
  setListening: (listening) => set((s) => ({
    isListening: listening,
    meetingStats: {
      ...s.meetingStats,
      meetingStartTime: listening && !s.meetingStats.meetingStartTime ? Date.now() : s.meetingStats.meetingStartTime,
    },
  })),

  reset: () =>
    set({
      messages: [],
      committedSegments: [],
      suggestions: [],
      currentSuggestionIndex: -1,
      currentStreamingText: null,
      suggestionLoading: false,
      strengthenLoading: false,
      documents: [],
      analysisStatus: null,
      statusMessage: 'Готов к работе',
      lastError: null,
      isListening: false,
      lastSuggestionTime: null,
      meetingStats: { positionStrength: 0, suggestionsUsed: 0, activeObjections: 0, meetingStartTime: null },
    }),
}));
