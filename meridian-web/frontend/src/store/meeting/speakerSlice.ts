import type { StateCreator } from 'zustand';
import type { IMeetingStore, ISpeakerSlice } from './types';

export const createSpeakerSlice: StateCreator<IMeetingStore, [], [], ISpeakerSlice> = (set) => ({
  speakerRoles: {},
  setSpeakerRoles: (roles) => set({ speakerRoles: roles }),

  speakerNames: {},
  setSpeakerNames: (names) => set({ speakerNames: names }),

  maxSpeakers: 3,
  setMaxSpeakers: (n) => set({ maxSpeakers: n }),
  speakerCorrections: {},
  setSpeakerCorrections: (corrections) => set({ speakerCorrections: corrections }),
  segmentHints: {},
  addSegmentHint: (hint) =>
    set((s) => ({ segmentHints: { ...s.segmentHints, [hint.segment_key]: hint } })),
  dismissSegmentHint: (segmentKey) =>
    set((s) => {
      const next = { ...s.segmentHints };
      delete next[segmentKey];
      return { segmentHints: next };
    }),

  conversationTree: [],
  treeVersion: 0,
  treeUnassigned: [],
  treeCollapsed: {},
  treePanelOpen: true,
  setConversationTree: (topics, version, unassigned) =>
    set((s) => ({
      conversationTree: topics,
      treeVersion: version,
      treeUnassigned: unassigned ?? s.treeUnassigned,
    })),
  upsertConversationTopic: (topic, version) =>
    set((s) => {
      const idx = s.conversationTree.findIndex((t) => t.id === topic.id);
      const next = idx >= 0
        ? s.conversationTree.map((t) => (t.id === topic.id ? topic : t))
        : [...s.conversationTree, topic];
      return { conversationTree: next, treeVersion: Math.max(s.treeVersion, version) };
    }),
  toggleTopicExpanded: (topicId) =>
    set((s) => ({ treeCollapsed: { ...s.treeCollapsed, [topicId]: !s.treeCollapsed[topicId] } })),
  setTreePanelOpen: (v) => set({ treePanelOpen: v }),
});
