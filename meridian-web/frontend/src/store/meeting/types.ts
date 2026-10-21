import type { ChatMessage, Suggestion, DocumentInfo, CommittedSegmentWire, SuggestionTypeConfig, TurnWire, ConversationTopic, SpeakerSegmentCorrection, SegmentSideHint, DeviceSyncState, SecondaryShadowTrackSummary, MultiSourceAlignment, MultiChannelLiveState, MultiChannelLiveSegment, MultiChannelLiveSnapshot, MultiChannelReconciliationState, TranscriptionAuthorityState, RoomParticipant } from '../../types';

export interface MeetingStats {
  positionStrength: number;
  suggestionsUsed: number;
  activeObjections: number;
  meetingStartTime: number | null;
}

// Транскрипт: сообщения, закоммиченные сегменты, partial, turns
export interface ITranscriptSlice {
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
}

// Подсказки
export interface ISuggestionSlice {
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

  // Custom suggestion types
  customSuggestionTypes: SuggestionTypeConfig[] | null;
  setCustomSuggestionTypes: (types: SuggestionTypeConfig[] | null) => void;
}

// Общее состояние сессии: соединение, статистика, статус, ошибки, сбросы
export interface ISessionSlice {
  isConnected: boolean;
  isListening: boolean;

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

  // Connection state
  setConnected: (connected: boolean) => void;
  setListening: (listening: boolean) => void;

  // Сбросить идентичность встречи для НОВОЙ сессии (без reload)
  newMeetingSession: () => void;

  // Reset
  reset: () => void;
}

// Контекст встречи, документы, выбор заказчика/объекта, UI-режим
export interface IContextSlice {
  // Documents
  documents: DocumentInfo[];
  addDocument: (doc: DocumentInfo) => void;
  removeDocument: (filename: string) => void;
  setDocuments: (docs: DocumentInfo[]) => void;

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

  // Ярлык «Заказчик | Объект» в шапке на странице объекта (read-only канал из ObjectDetailPage).
  objectHeader: { customer: string | null; object: string | null } | null;
  setObjectHeader: (v: { customer: string | null; object: string | null } | null) => void;
}

// Спикеры и дерево общения
export interface ISpeakerSlice {
  // Speaker roles
  speakerRoles: Record<string, string>;
  setSpeakerRoles: (roles: Record<string, string>) => void;

  // Имена спикеров (speaker_label → display_name)
  speakerNames: Record<string, string>;
  setSpeakerNames: (names: Record<string, string>) => void;

  // Число спикеров диаризации — per-meeting (для контрола во встрече)
  maxSpeakers: number;
  setMaxSpeakers: (n: number) => void;

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
}

// MeetingRoom / multi-device, устройства и ingest
export interface IRoomSlice {
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
  // Задача 2b: кто ведёт запись (ярлык аккаунта) и server-время её старта (для таймера наблюдателя)
  activeAudioUserLabel: string | null;
  recordingStartedAtMs: number | null;
  setRecordingMeta: (p: { userLabel: string | null; startedAtMs: number | null }) => void;

  // Задача 3: участники комнаты (live-снапшот для бейджа в шапке). Авторитетен сервер.
  participants: RoomParticipant[];
  setParticipants: (p: RoomParticipant[]) => void;

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
}

// Multi-channel live STT, reconciliation, авторитет транскрипта
export interface IMultiChannelSlice {
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
}

export type IMeetingStore =
  ITranscriptSlice & ISuggestionSlice & ISessionSlice & IContextSlice &
  ISpeakerSlice & IRoomSlice & IMultiChannelSlice;
