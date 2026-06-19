import { create } from 'zustand';
import type { ChatMessage, Suggestion, DocumentInfo, CommittedSegmentWire, SuggestionTypeConfig, TurnWire, ConversationTopic, SpeakerSegmentCorrection, SegmentSideHint, DeviceSyncState, SecondaryShadowTrackSummary, MultiSourceAlignment, MultiChannelLiveState, MultiChannelLiveSegment, MultiChannelLiveSnapshot, MultiChannelReconciliationState, TranscriptionAuthorityState } from '../types';

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
  // Дата начала записи встречи (started_at, ISO) — справочно в шапке.
  meetingStartedAt: string | null;
  setMeetingStartedAt: (v: string | null) => void;
  meetingTopic: string;
  meetingNotes: string;
  negotiationType: string;
  meetingRole: string;
  opponentWeaknesses: string;
  setMeetingName: (n: string) => void;
  // Метка последнего локального редактирования полей контекста — гасит self-echo
  // (meeting_context_updated не должен затирать ввод во время печати).
  contextEditedAt: number;
  markContextEdited: () => void;
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

  // Этап 8: segment-level коррекции диаризации (по segment_key)
  speakerCorrections: Record<string, SpeakerSegmentCorrection>;
  setSpeakerCorrections: (corrections: Record<string, SpeakerSegmentCorrection>) => void;

  // Этап 9: observer-подсказки стороны реплики (эфемерные)
  segmentHints: Record<string, SegmentSideHint>;
  addSegmentHint: (hint: SegmentSideHint) => void;
  dismissSegmentHint: (segmentKey: string) => void;

  // Conversation Tree (дерево общения)
  conversationTree: ConversationTopic[];
  treeVersion: number;
  treeUnassigned: string[];  // спикеры из транскрипта без назначенной стороны
  treeCollapsed: Record<number, boolean>;  // topicId -> refs свёрнуты
  treePanelOpen: boolean;
  setConversationTree: (topics: ConversationTopic[], version: number, unassigned?: string[]) => void;
  upsertConversationTopic: (topic: ConversationTopic, version: number) => void;
  toggleTopicExpanded: (topicId: number) => void;
  setTreePanelOpen: (v: boolean) => void;

  // UI режим экрана встречи: 'simple' — диктофон, 'full' — детальный
  uiMode: 'simple' | 'full';
  setUiMode: (m: 'simple' | 'full') => void;

  // Active role
  activeRoleName: string | null;
  setActiveRoleName: (name: string | null) => void;

  // Meeting saved
  meetingSavedId: number | null;
  setMeetingSavedId: (id: number | null) => void;

  // Directory selection (Этап 1 MVP): заказчик/объект встречи + draft id
  selectedCustomerId: number | null;
  selectedObjectId: number | null;
  // Имена для справочного показа в шапке встречи (read-only, не редактируются).
  selectedCustomerName: string | null;
  selectedObjectName: string | null;
  draftMeetingId: number | null;
  setSelectedCustomerId: (id: number | null) => void;
  setSelectedObjectId: (id: number | null) => void;
  setSelectedCustomerName: (n: string | null) => void;
  setSelectedObjectName: (n: string | null) => void;
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

  // Этап 9.1: синхронизация часов устройства с backend
  deviceSync: DeviceSyncState | null;
  setDeviceSync: (s: DeviceSyncState | null) => void;

  // Этап 9.2: сводка secondary audio shadow треков комнаты (для desktop-монитора)
  shadowTracks: SecondaryShadowTrackSummary[];
  setShadowTracks: (tracks: SecondaryShadowTrackSummary[]) => void;

  // Этап 9.3: сводка выравнивания multi-source ingest (общая server timeline)
  ingestAlignment: MultiSourceAlignment | null;
  setIngestAlignment: (a: MultiSourceAlignment | null) => void;

  // Этап 9.6: realtime multi-channel live STT shadow (диагностический candidate)
  multiChannelLiveState: MultiChannelLiveState | null;
  multiChannelLiveFinalSegments: MultiChannelLiveSegment[];
  multiChannelLiveInterimByChannel: Record<number, MultiChannelLiveSegment>;
  setMultiChannelLiveState: (s: MultiChannelLiveState | null) => void;
  upsertMultiChannelLiveResult: (seg: MultiChannelLiveSegment) => void;
  setMultiChannelLiveSnapshot: (snap: MultiChannelLiveSnapshot) => void;
  clearMultiChannelLive: () => void;

  // Этап 9.7: channel-aware reconciliation (state + ephemeral dismiss/select)
  multiChannelReconciliation: MultiChannelReconciliationState | null;
  dismissedReconciliationEntries: Record<string, true>;
  selectedReconciliationEntries: Record<string, true>;
  setMultiChannelReconciliation: (s: MultiChannelReconciliationState | null) => void;
  dismissReconciliationEntry: (entryId: string) => void;
  selectReconciliationEntry: (entryId: string, selected: boolean) => void;
  clearReconciliationSelection: () => void;
  clearMultiChannelReconciliation: () => void;

  // Этап 9.8: production cutover (авторитетный источник транскрипта)
  transcriptionAuthority: TranscriptionAuthorityState | null;
  transcriptionAuthorityError: { code: string | null; message: string | null } | null;
  setTranscriptionAuthority: (s: TranscriptionAuthorityState | null) => void;
  setTranscriptionAuthorityError: (e: { code: string | null; message: string | null } | null) => void;

  // Сбросить идентичность встречи для НОВОЙ сессии (без reload)
  newMeetingSession: () => void;

  // Reset
  reset: () => void;
}

let messageCounter = 0;

const MAX_LIVE_FINALS = 2000;
// Этап 9.6: dedupe по segment_id + sort (start_server_ms, channel_index) + bounded.
function mergeLiveFinal(list: MultiChannelLiveSegment[], seg: MultiChannelLiveSegment): MultiChannelLiveSegment[] {
  if (list.some((s) => s.segment_id === seg.segment_id)) return list;
  const next = [...list, seg].sort(
    (a, b) => a.start_server_ms - b.start_server_ms || a.channel_index - b.channel_index);
  return next.length > MAX_LIVE_FINALS ? next.slice(next.length - MAX_LIVE_FINALS) : next;
}

// Дефолт вида встречи: диктофон — только для мобильного; десктоп → полный интерфейс.
// Явный выбор пользователя сохраняется в meridian_ui_mode_v2 (новый ключ — старый
// загрязнён 'simple' прежней логикой «роль → режим»).
const storedUiMode = typeof localStorage !== 'undefined' ? localStorage.getItem('meridian_ui_mode_v2') : null;
const isMobileViewport = typeof window !== 'undefined' && !!window.matchMedia?.('(max-width: 768px)').matches;
const initialUiMode: 'simple' | 'full' =
  storedUiMode === 'simple' || storedUiMode === 'full'
    ? storedUiMode
    : (isMobileViewport ? 'simple' : 'full');

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
  meetingStartedAt: null,
  setMeetingStartedAt: (v) => set({ meetingStartedAt: v }),
  contextEditedAt: 0,
  meetingTopic: '',
  meetingNotes: '',
  negotiationType: 'sale',
  meetingRole: '',
  opponentWeaknesses: '',
  setMeetingName: (n) => set({ meetingName: n }),
  markContextEdited: () => set({ contextEditedAt: Date.now() }),
  setMeetingTopic: (t) => set({ meetingTopic: t }),
  setMeetingNotes: (n) => set({ meetingNotes: n }),
  setNegotiationType: (t) => set({ negotiationType: t }),
  setMeetingRole: (r) => set({ meetingRole: r }),
  setOpponentWeaknesses: (w) => set({ opponentWeaknesses: w }),

  customSuggestionTypes: null,
  setCustomSuggestionTypes: (types) => set({ customSuggestionTypes: types }),

  speakerRoles: {},
  setSpeakerRoles: (roles) => set({ speakerRoles: roles }),
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

  uiMode: initialUiMode,
  setUiMode: (m) => {
    try { localStorage.setItem('meridian_ui_mode_v2', m); } catch { /* ignore */ }
    set({ uiMode: m });
  },

  activeRoleName: null,
  setActiveRoleName: (name) => set({ activeRoleName: name }),

  meetingSavedId: null,
  setMeetingSavedId: (id) => set({ meetingSavedId: id }),

  selectedCustomerId: null,
  selectedObjectId: null,
  selectedCustomerName: null,
  selectedObjectName: null,
  draftMeetingId: null,
  setSelectedCustomerId: (id) => set({ selectedCustomerId: id }),
  setSelectedObjectId: (id) => set({ selectedObjectId: id }),
  setSelectedCustomerName: (n) => set({ selectedCustomerName: n }),
  setSelectedObjectName: (n) => set({ selectedObjectName: n }),
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

  deviceSync: null,
  setDeviceSync: (s) => set({ deviceSync: s }),

  shadowTracks: [],
  setShadowTracks: (tracks) => set({ shadowTracks: tracks }),

  ingestAlignment: null,
  setIngestAlignment: (a) => set({ ingestAlignment: a }),

  multiChannelLiveState: null,
  multiChannelLiveFinalSegments: [],
  multiChannelLiveInterimByChannel: {},
  setMultiChannelLiveState: (s) => set({ multiChannelLiveState: s }),
  upsertMultiChannelLiveResult: (seg) =>
    set((st) => {
      if (seg.is_final) {
        const interim = { ...st.multiChannelLiveInterimByChannel };
        delete interim[seg.channel_index];
        return {
          multiChannelLiveFinalSegments: mergeLiveFinal(st.multiChannelLiveFinalSegments, seg),
          multiChannelLiveInterimByChannel: interim,
        };
      }
      const interim = { ...st.multiChannelLiveInterimByChannel };
      if (!seg.transcript.trim()) delete interim[seg.channel_index];
      else interim[seg.channel_index] = seg;
      return { multiChannelLiveInterimByChannel: interim };
    }),
  setMultiChannelLiveSnapshot: (snap) =>
    set(() => {
      const interim: Record<number, MultiChannelLiveSegment> = {};
      for (const [k, v] of Object.entries(snap.latest_interim_by_channel || {})) {
        interim[Number(k)] = v;
      }
      const finals = [...(snap.final_segments || [])].sort(
        (a, b) => a.start_server_ms - b.start_server_ms || a.channel_index - b.channel_index);
      return {
        multiChannelLiveState: snap.state,
        multiChannelLiveFinalSegments: finals,
        multiChannelLiveInterimByChannel: interim,
      };
    }),
  clearMultiChannelLive: () =>
    set({ multiChannelLiveFinalSegments: [], multiChannelLiveInterimByChannel: {} }),

  multiChannelReconciliation: null,
  dismissedReconciliationEntries: {},
  selectedReconciliationEntries: {},
  setMultiChannelReconciliation: (s) =>
    set((st) => {
      if (s == null) {
        return { multiChannelReconciliation: null,
                 dismissedReconciliationEntries: {}, selectedReconciliationEntries: {} };
      }
      // игнорировать устаревшую ревизию
      const cur = st.multiChannelReconciliation;
      if (cur && s.revision < cur.revision) return {};
      // dismiss/select сохраняем только для всё ещё существующих entry id
      const ids = new Set(s.entries.map((e) => e.entry_id));
      const prune = (m: Record<string, true>) => {
        const out: Record<string, true> = {};
        for (const k of Object.keys(m)) if (ids.has(k)) out[k] = true;
        return out;
      };
      return {
        multiChannelReconciliation: s,
        dismissedReconciliationEntries: prune(st.dismissedReconciliationEntries),
        selectedReconciliationEntries: prune(st.selectedReconciliationEntries),
      };
    }),
  dismissReconciliationEntry: (entryId) =>
    set((st) => {
      const sel = { ...st.selectedReconciliationEntries };
      delete sel[entryId];
      return {
        dismissedReconciliationEntries: { ...st.dismissedReconciliationEntries, [entryId]: true },
        selectedReconciliationEntries: sel,
      };
    }),
  selectReconciliationEntry: (entryId, selected) =>
    set((st) => {
      const sel = { ...st.selectedReconciliationEntries };
      if (selected) sel[entryId] = true; else delete sel[entryId];
      return { selectedReconciliationEntries: sel };
    }),
  clearReconciliationSelection: () => set({ selectedReconciliationEntries: {} }),
  clearMultiChannelReconciliation: () =>
    set({ multiChannelReconciliation: null, dismissedReconciliationEntries: {},
          selectedReconciliationEntries: {} }),

  transcriptionAuthority: null,
  transcriptionAuthorityError: null,
  setTranscriptionAuthority: (s) =>
    set((st) => {
      // игнорировать устаревшую ревизию (state приходит и из join, и из broadcast)
      const cur = st.transcriptionAuthority;
      if (s && cur && cur.meeting_id === s.meeting_id && s.revision < cur.revision) return {};
      return { transcriptionAuthority: s, transcriptionAuthorityError: null };
    }),
  setTranscriptionAuthorityError: (e) => set({ transcriptionAuthorityError: e }),

  newMeetingSession: () => set({
    messages: [], committedSegments: [], partialMessage: null, turns: [],
    suggestions: [], currentSuggestionIndex: -1, currentStreamingText: null,
    analysisStatus: null, isListening: false, lastError: null, activeRoleName: null,
    meetingStartedAt: null,
    currentMeetingId: null, draftMeetingId: null, meetingSavedId: null,
    roomConnected: false, connectionId: null, deviceRole: null,
    canSendAudio: false, activeAudioSource: null, recording: false,
    recordPermissionDenied: false, phoneRecording: false, deviceSync: null,
    shadowTracks: [], ingestAlignment: null,
    multiChannelLiveState: null, multiChannelLiveFinalSegments: [], multiChannelLiveInterimByChannel: {},
    multiChannelReconciliation: null, dismissedReconciliationEntries: {}, selectedReconciliationEntries: {},
    transcriptionAuthority: null, transcriptionAuthorityError: null,
    conversationTree: [], treeVersion: 0, treeUnassigned: [], treeCollapsed: {},
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
      meetingStartedAt: null,
      analysisStatus: null,
      statusMessage: 'Готов к работе',
      lastError: null,
      isListening: false,
      lastSuggestionTime: null,
      speakerRoles: {},
      speakerCorrections: {},
      segmentHints: {},
      activeRoleName: null,
      meetingStats: { positionStrength: 0, suggestionsUsed: 0, activeObjections: 0, meetingStartTime: null },
      selectedCustomerId: null,
      selectedObjectId: null,
      selectedCustomerName: null,
      selectedObjectName: null,
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
      deviceSync: null,
      shadowTracks: [],
      ingestAlignment: null,
      multiChannelLiveState: null,
      multiChannelLiveFinalSegments: [],
      multiChannelLiveInterimByChannel: {},
      multiChannelReconciliation: null,
      dismissedReconciliationEntries: {},
      selectedReconciliationEntries: {},
      transcriptionAuthority: null,
      transcriptionAuthorityError: null,
      conversationTree: [],
      treeVersion: 0,
      treeUnassigned: [],
      treeCollapsed: {},
    }),
}));
