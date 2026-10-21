import type { StateCreator } from 'zustand';
import type { IMeetingStore, ISuggestionSlice } from './types';

export const createSuggestionSlice: StateCreator<IMeetingStore, [], [], ISuggestionSlice> = (set) => ({
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

  customSuggestionTypes: null,
  setCustomSuggestionTypes: (types) => set({ customSuggestionTypes: types }),
});
