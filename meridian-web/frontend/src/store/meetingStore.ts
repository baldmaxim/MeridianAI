import { create } from 'zustand';
import type { ChatMessage, Suggestion, DocumentInfo, CommittedSegmentWire, SuggestionTypeConfig, TurnWire, ConversationTopic } from '../types';

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
  partialMessage: ChatMessage | null;
  updatePartial: (msg: ChatMessage) => void;
  clearPartial: () => void;

  // Turns (server-assembled utterances)
  turns: TurnWire[];
  handleTurnUpdate: (turn: TurnWire) => void;
  resetTurns: () => void;

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
  meetingName: string;
  meetingTopic: string;
  meetingNotes: string;
  negotiationType: string;
  meetingRole: string;
  opponentWeaknesses: string;
  setMeetingName: (n: string) => void;
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

  // Speaker roles
  speakerRoles: Record<string, string>;
  setSpeakerRoles: (roles: Record<string, string>) => void;

  // Conversation Tree (дерево общения)
  conversationTree: ConversationTopic[];
  treeVersion: number;
  treeCollapsed: Record<number, boolean>;  // topicId -> refs свёрнуты
  treePanelOpen: boolean;
  setConversationTree: (topics: ConversationTopic[], version: number) => void;
  upsertConversationTopic: (topic: ConversationTopic, version: number) => void;
  toggleTopicExpanded: (topicId: number) => void;
  setTreePanelOpen: (v: boolean) => void;

  // Active role
  activeRoleName: string | null;
  setActiveRoleName: (name: string | null) => void;

  // Meeting saved
  meetingSavedId: number | null;
  setMeetingSavedId: (id: number | null) => void;

  // Directory selection (Этап 1 MVP): заказчик/объект встречи + draft id
  selectedCustomerId: number | null;
  selectedObjectId: number | null;
  draftMeetingId: number | null;
  setSelectedCustomerId: (id: number | null) => void;
  setSelectedObjectId: (id: number | null) => void;
  setDraftMeetingId: (id: number | null) => void;

  // MeetingRoom / multi-device (Этап 2)
  currentMeetingId: number | null;
  roomConnected: boolean;
  connectionId: string | null;
  deviceRole: string | null;
  canSendAudio: boolean;
  activeAudioSource: string | null;
  recording: boolean;
  setCurrentMeetingId: (id: number | null) => void;
  setRoomConnected: (v: boolean) => void;
  setRoomJoined: (p: { connectionId: string; deviceRole: string; canSendAudio: boolean; activeAudioSource: string | null }) => void;
  setActiveAudioSource: (id: string | null) => void;
  setRecording: (v: boolean) => void;

  // Этап 3: право записи / телефон-диктофон
  recordPermissionDenied: boolean;
  phoneRecording: boolean;
  setRecordPermissionDenied: (v: boolean) => void;
  setPhoneRecording: (v: boolean) => void;

  // Сбросить идентичность встречи для НОВОЙ сессии (без reload)
  newMeetingSession: () => void;

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
      turns: [],
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

  meetingName: '',
  meetingTopic: '',
  meetingNotes: '',
  negotiationType: 'sale',
  meetingRole: '',
  opponentWeaknesses: '',
  setMeetingName: (n) => set({ meetingName: n }),
  setMeetingTopic: (t) => set({ meetingTopic: t }),
  setMeetingNotes: (n) => set({ meetingNotes: n }),
  setNegotiationType: (t) => set({ negotiationType: t }),
  setMeetingRole: (r) => set({ meetingRole: r }),
  setOpponentWeaknesses: (w) => set({ opponentWeaknesses: w }),

  customSuggestionTypes: null,
  setCustomSuggestionTypes: (types) => set({ customSuggestionTypes: types }),

  speakerRoles: {},
  setSpeakerRoles: (roles) => set({ speakerRoles: roles }),

  conversationTree: [],
  treeVersion: 0,
  treeCollapsed: {},
  treePanelOpen: true,
  setConversationTree: (topics, version) => set({ conversationTree: topics, treeVersion: version }),
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

  activeRoleName: null,
  setActiveRoleName: (name) => set({ activeRoleName: name }),

  meetingSavedId: null,
  setMeetingSavedId: (id) => set({ meetingSavedId: id }),

  selectedCustomerId: null,
  selectedObjectId: null,
  draftMeetingId: null,
  setSelectedCustomerId: (id) => set({ selectedCustomerId: id }),
  setSelectedObjectId: (id) => set({ selectedObjectId: id }),
  setDraftMeetingId: (id) => set({ draftMeetingId: id }),

  currentMeetingId: null,
  roomConnected: false,
  connectionId: null,
  deviceRole: null,
  canSendAudio: false,
  activeAudioSource: null,
  recording: false,
  setCurrentMeetingId: (id) => set({ currentMeetingId: id }),
  setRoomConnected: (v) => set({ roomConnected: v }),
  setRoomJoined: (p) => set({
    roomConnected: true,
    connectionId: p.connectionId,
    deviceRole: p.deviceRole,
    canSendAudio: p.canSendAudio,
    activeAudioSource: p.activeAudioSource,
  }),
  setActiveAudioSource: (id) => set({ activeAudioSource: id }),
  setRecording: (v) => set({ recording: v }),

  recordPermissionDenied: false,
  phoneRecording: false,
  setRecordPermissionDenied: (v) => set({ recordPermissionDenied: v }),
  setPhoneRecording: (v) => set({ phoneRecording: v }),

  newMeetingSession: () => set({
    messages: [], committedSegments: [], partialMessage: null, turns: [],
    suggestions: [], currentSuggestionIndex: -1, currentStreamingText: null,
    analysisStatus: null, isListening: false, lastError: null,
    currentMeetingId: null, draftMeetingId: null, meetingSavedId: null,
    roomConnected: false, connectionId: null, deviceRole: null,
    canSendAudio: false, activeAudioSource: null, recording: false,
    recordPermissionDenied: false, phoneRecording: false,
    conversationTree: [], treeVersion: 0, treeCollapsed: {},
    meetingStats: { positionStrength: 0, suggestionsUsed: 0, activeObjections: 0, meetingStartTime: null },
  }),

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
      partialMessage: null,
      turns: [],
      suggestions: [],
      currentSuggestionIndex: -1,
      currentStreamingText: null,
      suggestionLoading: false,
      strengthenLoading: false,
      documents: [],
      meetingName: '',
      analysisStatus: null,
      statusMessage: 'Готов к работе',
      lastError: null,
      isListening: false,
      lastSuggestionTime: null,
      speakerRoles: {},
      activeRoleName: null,
      meetingStats: { positionStrength: 0, suggestionsUsed: 0, activeObjections: 0, meetingStartTime: null },
      selectedCustomerId: null,
      selectedObjectId: null,
      draftMeetingId: null,
      currentMeetingId: null,
      roomConnected: false,
      connectionId: null,
      deviceRole: null,
      canSendAudio: false,
      activeAudioSource: null,
      recording: false,
      recordPermissionDenied: false,
      phoneRecording: false,
      conversationTree: [],
      treeVersion: 0,
      treeCollapsed: {},
    }),
}));
