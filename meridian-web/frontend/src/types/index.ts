export interface User {
  id: number;
  email: string;
  role: 'user' | 'admin';
  display_name: string | null;
  department: string | null;
  is_active: boolean;
  // Доступные роли страницы (ключи каталога) — приходят из /auth/me.
  allowed_pages: string[];
  // Набор роли "user" — для превью «смотреть как пользователь» (только у админа).
  user_role_pages?: string[];
}

// --- Доступ к страницам по ролям (page-access) ---

export interface PageCatalogItem {
  key: string;
  label: string;
}

export interface RolePageAccess {
  role_name: string;
  allowed_pages: string[];
}

export interface PageAccessConfig {
  catalog: PageCatalogItem[];
  roles: RolePageAccess[];
  locked: Record<string, string[]>;
}

export interface ChatMessage {
  id: string;
  speaker: string;
  text: string;
  timestamp: string;
  is_partial: boolean;
}

export type SuggestionType = string;

export interface SuggestionTypeConfig {
  key: string;
  badge: string;
  color: string;
  metaLabel?: string;
  actionLabel: string;
  secondaryAction?: string;
  llm_description: string;
  enabled: boolean;
}

export interface TriggerKeywordConfig {
  keyword: string;
  status_message: string;
  enabled: boolean;
}

// --- Этап 6: структурированные карточки подсказок ---

export type SuggestionCardType =
  | 'say_now' | 'ask' | 'counter' | 'risk' | 'fixation'
  | 'trade_concession' | 'pause' | 'clarify' | 'summarize';

export interface SuggestionEvidence {
  source: 'transcript' | 'document' | 'meeting_context' | 'previous_meeting' | 'playbook' | 'protocol' | 'unknown';
  ref: string | null;
  text: string;
  confidence: number | null;
}

export interface SuggestionCard {
  id: string | null;
  type: SuggestionCardType;
  priority: number;
  title: string;
  text: string;
  why: string;
  evidence: SuggestionEvidence[];
  confidence: number;        // 0..1
  needs_user_check: boolean;
  created_at: string | null;
  trigger: string | null;
  source_mode: 'auto' | 'manual' | 'strengthen' | 'fallback';
}

export interface SuggestionResponse {
  cards: SuggestionCard[];
  raw_text: string | null;
  model: string | null;
  degraded: boolean;
}

export interface Suggestion {
  text: string;
  is_auto: boolean;
  timestamp: Date;
  type?: SuggestionType;
  trigger?: string;
  confidence?: number;
  context_info?: string;
  card?: SuggestionCard;  // Этап 6: полная структурированная карточка (если есть)
}

export interface DocumentInfo {
  filename: string;
  doc_type: string;
  doc_type_label: string;
  page_count: number;
}

export interface UserSettings {
  stt_provider: string;
  llm_model: string;
  temperature: number;
  user_role: string;
  use_streaming: boolean;
  diarization: boolean;
  silence_filter: boolean;
  custom_suggestion_types: SuggestionTypeConfig[] | null;
  custom_trigger_keywords: TriggerKeywordConfig[] | null;
  local_storage_path: string | null;
}

export interface NegotiationRole {
  id: number;
  name: string;
  description: string;
  interests: string;
  opponents: string;
  custom_instructions: string;
  is_default: boolean;
  created_at: string;
}

export interface ApiKeyInfo {
  id: number;
  service: string;
  key_masked: string;
  is_active: boolean;
}

export interface TranscriptionRecord {
  id: number;
  filename: string;
  format: string;
  segment_count: number | null;
  created_at: string;
}

// ElevenLabs word-level data
export interface TranscriptWord {
  text: string;
  start: number;
  end: number;
  type: string; // "word" | "spacing" | "punctuation"
  logprob: number | null;
}

// Committed segment with word-level timestamps
export interface CommittedSegmentWire {
  segment_id: string;
  segment_key: string;       // = segment_id; стабильный ключ для channel alignment (Этап 9.1)
  speaker: string;
  text: string;
  words: TranscriptWord[];
  start_time: number;
  end_time: number;
  confidence: number | null;
  timestamp: string;
  server_ts_ms: number;      // абсолютный server timeline (epoch ms)
}

// Этап 9.1: качество синхронизации часов устройства с backend.
export type ClockSyncQuality = 'excellent' | 'good' | 'fair' | 'poor';

export interface DeviceSyncState {
  offsetMs: number;
  rttMs: number;
  quality: ClockSyncQuality;
  samples: number;
  lastSyncMs: number;
}

// Этап 9.2: диагностика secondary audio shadow канала (с backend).
export type SecondaryShadowStatus = 'idle' | 'recording' | 'stale' | 'error';

export interface SecondaryShadowDiag {
  enabled: boolean;
  side_hint: PublicSpeakerSide | null;
  status: SecondaryShadowStatus;
  sample_rate: number | null;
  channels: number | null;
  codec: string | null;
  chunks_count: number;
  bytes_count: number;
  dropped_chunks: number;
  gaps_count: number;
  last_seq: number | null;
  last_duration_ms: number | null;
  last_packet_age_ms: number | null;
  estimated_buffer_ms: number;
  drift_ms: number;
  target_sample_rate: number;
  error: string | null;
}

export interface SecondaryShadowTrackSummary {
  connection_id: string;
  side_hint: PublicSpeakerSide | null;
  status: SecondaryShadowStatus;
  chunks_count: number;
  estimated_buffer_ms: number;
  sample_rate: number | null;
}

// Этап 9.3: multi-source ingest — единая server timeline всех аудиоисточников.
export type IngestRole = 'primary' | 'secondary';

export interface IngestTrackInfo {
  track_id: string;
  role: IngestRole;
  side_hint: PublicSpeakerSide | null;
  sample_rate: number;
  channels: number;
  codec: string;
  frame_ms: number;
  frame_bytes: number;
  frames_count: number;
  buffered_frames: number;
  gaps_count: number;
  duplicates_count: number;
  late_frames: number;
  jitter_ms: number;
  drift_ms: number;
  first_index: number | null;
  last_index: number | null;
}

export interface MultiSourceAlignment {
  meeting_id: number;
  frame_ms: number;
  window_ms: number;
  common_lo: number | null;
  common_hi: number | null;
  tracks: IngestTrackInfo[];
}

// Этап 9.6: realtime multi-channel live STT shadow (диагностический candidate).
export type MultiChannelLiveStatus =
  | 'idle' | 'buffering' | 'connecting' | 'streaming'
  | 'degraded' | 'stopping' | 'stopped' | 'failed';

export interface MultiChannelLiveChannel {
  channel_index: number;
  track_id: string;
  connection_id: string;
  generation: number;
  source_kind: string;
  label: string;
  side: PublicSpeakerSide | null;
}

export interface MultiChannelLiveWord {
  text: string;
  start: number;
  end: number;
  confidence: number | null;
  punctuated_word: string | null;
}

export interface MultiChannelLiveSegment {
  segment_id: string;
  session_id: string;
  channel_index: number;
  channels_count: number;
  track_id: string;
  channel_label: string;
  side: PublicSpeakerSide | null;
  transcript: string;
  confidence: number | null;
  provider_start: number;
  provider_end: number;
  start_server_ms: number;
  end_server_ms: number;
  is_final: boolean;
  speech_final: boolean;
  words: MultiChannelLiveWord[];
}

export interface MultiChannelLiveState {
  session_id: string | null;
  status: MultiChannelLiveStatus;
  provider?: string;
  model?: string;
  language?: string;
  channel_count: number;
  channels: MultiChannelLiveChannel[];
  started_at?: string | null;
  start_frame_index?: number | null;
  start_server_ms?: number | null;
  chunks_sent?: number;
  frames_sent?: number;
  bytes_sent?: number;
  provider_queue_depth?: number;
  provider_request_id?: string | null;
  silence_ratio_by_channel?: number[];
  error_code?: string | null;
  error_message?: string | null;
}

export interface MultiChannelLiveSnapshot {
  state: MultiChannelLiveState;
  final_segments: MultiChannelLiveSegment[];
  latest_interim_by_channel: Record<string, MultiChannelLiveSegment>;
}

// Этап 9.7: channel-aware reconciliation (evidence-слой; применение только вручную).
export type ReconciliationEntryKind = 'matched' | 'ambiguous' | 'channel_only' | 'primary_only';
export type ReconciliationSideAgreement = 'suggested' | 'confirmed' | 'conflict' | 'unknown';

export interface MultiChannelReconciliationAlternative {
  channel_segment_id: string;
  channel_index: number;
  match_score: number;
  temporal_score: number;
  text_score: number;
}

export interface MultiChannelReconciliationEntry {
  entry_id: string;
  kind: ReconciliationEntryKind;
  primary_segment_key: string | null;
  channel_segment_id: string | null;
  primary_text: string | null;
  channel_text: string | null;
  primary_start_server_ms: number | null;
  primary_end_server_ms: number | null;
  channel_start_server_ms: number | null;
  channel_end_server_ms: number | null;
  original_speaker_label: string | null;
  effective_speaker_label: string | null;
  current_side: PublicSpeakerSide | null;
  has_segment_correction: boolean;
  channel_index: number | null;
  track_id: string | null;
  source_connection_id: string | null;
  source_kind: string | null;
  generation: number | null;
  channel_label: string | null;
  channel_side: PublicSpeakerSide | null;
  provider_confidence: number | null;
  temporal_score: number;
  text_score: number;
  match_score: number;
  hint_confidence: number;
  side_agreement: ReconciliationSideAgreement;
  can_apply_side: boolean;
  requires_conflict_confirmation: boolean;
  alternatives: MultiChannelReconciliationAlternative[];
  warnings: string[];
}

export interface MultiChannelReconciliationSummary {
  primary_segments: number;
  channel_segments: number;
  matched: number;
  ambiguous: number;
  channel_only: number;
  primary_only: number;
  suggested: number;
  confirmed: number;
  conflicts: number;
  unknown_side: number;
  applicable: number;
}

export interface MultiChannelReconciliationState {
  session_id: string;
  meeting_id: number;
  revision: number;
  generated_at: string;
  truncated: boolean;
  summary: MultiChannelReconciliationSummary;
  entries: MultiChannelReconciliationEntry[];
  warnings: string[];
}

// --- Этап 9.8: production cutover (авторитетный источник транскрипта) ---
export type TranscriptionSource = 'single' | 'multi_channel';

export interface CutoverRolloutInfo {
  allowed: boolean;
  reason: string;
  bucket: number;
}

export interface CutoverQualityInfo {
  ok: boolean;
  score: number;
  reasons: string[];
  metrics: Record<string, unknown>;
}

export interface TranscriptionAuthorityState {
  meeting_id: number;
  current_source: TranscriptionSource;
  revision: number;
  fallback_used: boolean;
  epochs_count: number;
  can_promote: boolean;
  rollout: CutoverRolloutInfo;
  quality: CutoverQualityInfo | null;
  last_switch: Record<string, unknown> | null;
}

// Speaker negotiation side. SpeakerSide — legacy union (для парсинга старых данных сервера).
// Диаризация v1 использует две публичные стороны.
export type SpeakerSide = 'self' | 'opponent' | 'ally' | 'third_party';
export type PublicSpeakerSide = 'self' | 'opponent';

// Utterance turn (server-assembled from consecutive same-speaker segments)
export interface TurnWire {
  turn_id: string;
  speaker: string;
  text: string;
  start_time: number;
  end_time: number;
  timestamp: string;
  segment_count: number;
}

// --- Conversation Tree (дерево общения встречи) ---
export type ConversationTopicStatus = 'new' | 'updated' | 'resolved' | 'disputed' | 'needs_follow_up';

export interface ConversationTopicRef {
  segment_id: string;
  speaker: string;
  timecode: string;
  text: string;
}

export interface ConversationTopic {
  id: number;
  meeting_id: number;
  title: string;
  normalized_key: string;
  status: ConversationTopicStatus;
  our_summary: string | null;
  opponent_summary: string | null;
  our_last_text: string | null;
  opponent_last_text: string | null;
  our_refs: ConversationTopicRef[];
  opponent_refs: ConversationTopicRef[];
  last_updated_at: string;
  created_at: string;
}

export interface ConversationTree {
  meeting_id: number;
  tree_version: number;
  topics: ConversationTopic[];
  unassigned_speakers: string[];
}

export interface SpeakerRoleOut {
  id: number;
  meeting_id: number;
  speaker_label: string;
  side: SpeakerSide;
  display_name: string | null;
  assigned_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

// Этап 8: segment-level коррекция диаризации (overlay поверх raw STT)
export interface SpeakerSegmentCorrection {
  id: number;
  meeting_id: number;
  segment_key: string;
  original_speaker_label: string | null;
  corrected_speaker_label: string | null;
  side: string | null;
  note: string | null;
  created_by_user_id: number | null;
  updated_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

// Этап 9: observer-подсказка стороны реплики (эфемерная, по уровням звука второго телефона)
export interface SegmentSideHint {
  segment_key: string;
  side: PublicSpeakerSide | null;
  confidence: number;
  reason: string;
  device_count: number;
  window_ms: number;
  auto_apply: boolean;
}

export interface ConversationTopicUpdateInput {
  title?: string;
  status?: ConversationTopicStatus;
  our_summary?: string;
  opponent_summary?: string;
}

// WebSocket message types
export type WSMessageFromServer =
  | { type: 'transcript'; speaker: string; text: string; timestamp: string; is_partial: boolean }
  | { type: 'committed_transcript'; segment_id: string; segment_key: string; speaker: string; text: string; words: TranscriptWord[]; start_time: number; end_time: number; confidence: number | null; timestamp: string; server_ts_ms: number; speech_start_ms: number | null; speech_end_ms: number | null }
  | { type: 'batch_finalized'; segments: CommittedSegmentWire[] }
  | { type: 'suggestion'; text: string; is_auto: boolean; suggestion_type?: SuggestionType; trigger?: string; confidence?: number; context_info?: string; cards?: SuggestionCard[]; degraded?: boolean; source_mode?: string; raw_text?: string | null }
  | { type: 'strengthen_summary'; cards: SuggestionCard[] }
  | { type: 'suggestion_chunk'; text: string }
  | { type: 'suggestion_loading'; loading: boolean }
  | { type: 'strengthen_loading'; loading: boolean }
  | { type: 'analysis_status'; status: string | null }
  | { type: 'meeting_context'; title?: string; topic: string; notes: string; negotiation_type: string; meeting_role: string; opponent_weaknesses: string }
  | { type: 'meeting_context_updated'; title?: string; topic: string; notes: string; negotiation_type: string; meeting_role: string; opponent_weaknesses: string }
  | { type: 'meeting_saved'; meeting_id: number }
  | { type: 'speaker_roles_updated'; roles: Record<string, SpeakerSide> }
  | { type: 'speaker_corrections_updated'; meeting_id: number; corrections: SpeakerSegmentCorrection[] }
  | { type: 'segment_side_hint'; meeting_id: number; segment_key: string; side: PublicSpeakerSide | null; confidence: number; reason: string; device_count: number; window_ms: number; auto_apply: boolean }
  | { type: 'turn_update'; turn_id: string; speaker: string; text: string; start_time: number; end_time: number; timestamp: string; segment_count: number }
  | { type: 'turns_reset' }
  // --- Этап 2: MeetingRoom / multi-device ---
  | { type: 'room_joined'; meeting_id: number; connection_id: string; device_role: string; can_send_audio: boolean; active_audio_source: string | null }
  | { type: 'device_joined'; meeting_id: number; connection_id: string; device_role: string }
  | { type: 'device_left'; meeting_id: number; connection_id: string }
  | { type: 'audio_source_busy'; active_audio_source: string | null }
  | { type: 'audio_source_disconnected'; meeting_id?: number }
  | { type: 'recording_status'; recording: boolean; active_audio_source: string | null }
  | { type: 'room_status'; meeting_id: number; status: string }
  // --- Этап 3: право записи / телефон-диктофон ---
  | { type: 'record_permission_denied'; message: string }
  | { type: 'phone_recording_started'; connection_id: string }
  | { type: 'phone_recording_stopped'; connection_id: string }
  // --- Этап 5: финализация ---
  | { type: 'meeting_finalization_started'; meeting_id: number }
  | { type: 'meeting_finalized'; meeting_id: number; finalization_status: string }
  // --- Этап 8: источники контекста встречи обновлены ---
  | { type: 'meeting_context_sources_updated'; meeting_id: number }
  // --- Этап 9: AI-настройки встречи обновлены ---
  | { type: 'ai_settings_updated'; meeting_id: number; settings_summary: Record<string, unknown> }
  // --- Conversation Tree: обновление темы дерева общения ---
  | { type: 'conversation_tree_updated'; meeting_id: number; topic: ConversationTopic; tree_version: number }
  // --- Этап 9.1: device clock sync ---
  | { type: 'clock_pong'; seq: number; client_send_ms: number; server_receive_ms: number; server_send_ms: number }
  | { type: 'clock_sync_status'; connection_id: string; offset_ms: number; rtt_ms: number; quality: ClockSyncQuality; samples_count: number }
  // --- Этап 9.2: secondary audio shadow ---
  | { type: 'secondary_shadow_enabled'; connection_id: string; sample_rate: number; channels: number; codec: string; target_sample_rate: number; max_chunk_ms: number; max_chunk_bytes: number }
  | { type: 'secondary_shadow_disabled'; connection_id: string }
  | { type: 'secondary_shadow_error'; reason: string }
  | { type: 'secondary_shadow_diag'; connection_id: string } & SecondaryShadowDiag
  | { type: 'secondary_shadow_track'; meeting_id: number; tracks: SecondaryShadowTrackSummary[] }
  // --- Этап 9.3: multi-source ingest alignment ---
  | ({ type: 'multi_source_alignment' } & MultiSourceAlignment)
  // --- Этап 9.6: realtime multi-channel live STT shadow ---
  | ({ type: 'multi_channel_live_state' } & MultiChannelLiveState)
  | { type: 'multi_channel_live_result'; result: MultiChannelLiveSegment }
  | ({ type: 'multi_channel_live_snapshot' } & MultiChannelLiveSnapshot)
  // --- Этап 9.7: channel-aware reconciliation ---
  | { type: 'multi_channel_reconciliation_state'; state: MultiChannelReconciliationState | null }
  | { type: 'multi_channel_reconciliation_snapshot'; state: MultiChannelReconciliationState | null }
  // --- Этап 9.8: production cutover (авторитетный источник транскрипта) ---
  | ({ type: 'transcription_authority_state' } & TranscriptionAuthorityState)
  | { type: 'transcription_authority_error'; code: string | null; message: string | null; quality?: CutoverQualityInfo | null; state?: TranscriptionAuthorityState }
  | { type: 'error'; message: string }
  | { type: 'status'; message: string };

export type WSMessageToServer =
  | { type: 'start_listening' }
  | { type: 'stop_listening' }
  // Этап 2: нормализованные алиасы (предпочтительны), старые продолжают работать
  | { type: 'start_audio' }
  | { type: 'stop_audio' }
  | { type: 'finalize_meeting'; meeting_name?: string }
  | { type: 'request_suggestion' }
  | { type: 'strengthen_position' }
  | { type: 'request_batch_finalize' }
  | { type: 'mark_speaker'; name: string }
  | { type: 'update_meeting_context'; title?: string; topic: string; notes: string; negotiation_type: string; meeting_role: string; opponent_weaknesses: string }
  | { type: 'change_settings'; stt_provider?: string; llm_model?: string; temperature?: number; diarization?: boolean; silence_filter?: boolean }
  | { type: 'save_to_history'; meeting_name?: string }
  | { type: 'set_speaker_role'; name: string; side: PublicSpeakerSide | '' }
  | { type: 'audio_level'; rms: number; peak?: number; vad?: boolean; seq?: number; client_ts_ms?: number }
  | { type: 'observer_side'; side: PublicSpeakerSide | '' }
  | { type: 'change_role'; role_id: number }
  // Этап 9.1: device clock sync
  | { type: 'clock_ping'; seq: number; client_send_ms: number }
  | { type: 'clock_report'; offset_ms: number; rtt_ms: number; quality: ClockSyncQuality; samples_count: number }
  // Этап 9.2: secondary audio shadow (управление; аудио-чанки идут бинарными кадрами)
  | { type: 'enable_secondary_shadow'; sample_rate: number; channels: number; codec: string; side_hint?: PublicSpeakerSide }
  | { type: 'disable_secondary_shadow' }
  | { type: 'secondary_shadow_side'; side: PublicSpeakerSide | '' }
  // Этап 9.6: realtime multi-channel live STT shadow (управление)
  | { type: 'multi_channel_live_start'; track_ids: string[]; channel_side_overrides?: Record<string, PublicSpeakerSide | null>; consent_confirmed: boolean }
  | { type: 'multi_channel_live_stop' }
  | { type: 'multi_channel_live_clear' }
  | { type: 'multi_channel_live_get_snapshot' }
  // Этап 9.7: reconciliation
  | { type: 'multi_channel_reconciliation_refresh' }
  | { type: 'multi_channel_reconciliation_get_snapshot' }
  // Этап 9.8: production cutover (управление авторитетным источником)
  | { type: 'transcription_promote'; force?: boolean }
  | { type: 'transcription_fallback' }
  | { type: 'get_transcription_authority' };

// --- Справочники (Этап 1 MVP) ---

export interface Customer {
  id: number;
  owner_user_id: number;
  name: string;
  inn: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectObject {
  id: number;
  owner_user_id: number;
  customer_id: number;
  name: string;
  address: string | null;
  description: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  customer_name: string | null;
}

export interface MeetingParticipant {
  id: number;
  meeting_id: number;
  user_id: number;
  role: 'owner' | 'participant' | 'viewer';
  created_at: string;
  email: string | null;
  display_name: string | null;
}

// --- Этап 3: мобильный кабинет / live-state / recorder ---

export interface DeviceConnection {
  connection_id: string;
  user_id: number;
  device_role: string;
  can_send_audio: boolean;
  is_active_audio_source: boolean;
  connected_at: string;
}

export interface LiveState {
  meeting_id: number;
  status: string | null;
  customer_id: number | null;
  object_id: number | null;
  title: string | null;
  can_current_user_access: boolean;
  can_current_user_record: boolean;
  current_user_role: string;
  device_connections: DeviceConnection[];
  active_audio_source: string | null;
  phone_connected: boolean;
  phone_recording: boolean;
  desktop_connected: boolean;
}

export interface MobileMeetingListItem {
  id: number;
  title: string | null;
  micro_summary: string | null;
  status: string | null;
  customer_id: number | null;
  customer_name: string | null;
  object_id: number | null;
  object_name: string | null;
  meeting_topic: string | null;
  started_at: string;
  ended_at: string | null;
  created_at: string;
  created_by_user_id: number | null;
  current_user_role: string;
  can_record: boolean;
  is_live: boolean;
  phone_connected: boolean;
  desktop_connected: boolean;
  finalization_status: FinalizationStatus | null;
  tags: string[];
}

export interface MobileParticipant {
  user_id: number;
  role: string;
  email: string | null;
  display_name: string | null;
}

export interface MobileTranscriptLine {
  speaker: string;
  text: string;
  wall_clock: string;
}

export interface MobileMeetingDetail {
  id: number;
  title: string | null;
  status: string | null;
  customer_id: number | null;
  customer_name: string | null;
  object_id: number | null;
  object_name: string | null;
  meeting_topic: string | null;
  meeting_notes: string | null;
  negotiation_type: string | null;
  meeting_role: string | null;
  opponent_weaknesses: string | null;
  micro_summary: string | null;
  started_at: string;
  ended_at: string | null;
  created_by_user_id: number | null;
  participants: MobileParticipant[];
  can_current_user_record: boolean;
  current_user_role: string;
  live_state: LiveState;
  recent_segments: MobileTranscriptLine[];
  documents: MeetingDocument[];
  finalization_status: FinalizationStatus | null;
  finalization_error: string | null;
  tags: string[];
  has_protocol: boolean;
  decisions: MeetingDecision[];
  action_items: MeetingActionItem[];
  risks: MeetingRisk[];
  open_questions: MeetingOpenQuestion[];
  previous_context?: PreviousMeetingSummaryCard[];
  ai_settings_summary?: Record<string, unknown> | null;
}

export interface RecorderState {
  connecting: boolean;
  connected: boolean;
  canRecord: boolean;
  recording: boolean;
  isActiveSource: boolean;
  error: string | null;
}

// --- Этап 4: документы встречи на S3 ---

export type DocumentStatus = 'pending' | 'uploaded' | 'processing' | 'ready' | 'error';

export interface DocumentRecord {
  id: number;
  owner_user_id: number;
  customer_id: number | null;
  object_id: number | null;
  file_id: number | null;
  original_name: string;
  mime_type: string | null;
  file_ext: string;
  file_size: number | null;
  status: DocumentStatus;
  processing_error: string | null;
  page_count: number | null;
  sheet_count: number | null;
  created_by_user_id: number;
  created_at: string;
  updated_at: string;
  chunks_count: number;
}

export interface DocumentUploadSession {
  document_id: number;
  file_id: number;
  upload_url: string;
  s3_key: string;
  expires_in: number;
}

export interface MeetingDocument {
  id: number;
  document_id: number;
  original_name: string;
  file_ext: string | null;
  status: DocumentStatus;
  included: boolean;
  priority: number;
  chunks_count: number;
  page_count: number | null;
  sheet_count: number | null;
  processing_error: string | null;
}

export interface DocumentChunkPreview {
  chunk_id: number;
  text: string;
  page_number: number | null;
  sheet_name: string | null;
}

export interface RelevantDocumentChunk {
  document_id: number;
  document_name: string;
  chunk_id: number;
  text: string;
  page_number: number | null;
  sheet_name: string | null;
  score: number;
}

// --- Этап 5: финализация встречи / протокол ---

export type FinalizationStatus =
  | 'not_started' | 'queued' | 'running' | 'completed' | 'partial' | 'error';

export interface EvidenceRef {
  timecode?: string;
  speaker?: string;
  quote?: string;
}

export interface MeetingDecision {
  id: number;
  text: string;
  status: 'accepted' | 'preliminary' | 'rejected' | 'postponed' | 'unclear';
  evidence: EvidenceRef[];
  created_at: string;
}

export interface MeetingActionItem {
  id: number;
  task: string;
  owner_text: string | null;
  due_text: string | null;
  status: 'open' | 'done' | 'cancelled';
  evidence: EvidenceRef[];
  created_at: string;
}

export interface MeetingRisk {
  id: number;
  text: string;
  severity: 'low' | 'medium' | 'high';
  evidence: EvidenceRef[];
  created_at: string;
}

export interface MeetingOpenQuestion {
  id: number;
  text: string;
  evidence: EvidenceRef[];
  created_at: string;
}

export interface FinalizationStatusInfo {
  meeting_id: number;
  status: FinalizationStatus;
  error: string | null;
  finalized_at: string | null;
  has_protocol: boolean;
}

export interface MeetingProtocol {
  meeting_id: number;
  finalization_status: FinalizationStatus;
  title: string | null;
  micro_summary: string | null;
  tags: string[];
  protocol_markdown: string | null;
  protocol_json: Record<string, unknown> | null;
  decisions: MeetingDecision[];
  action_items: MeetingActionItem[];
  risks: MeetingRisk[];
  open_questions: MeetingOpenQuestion[];
}

export interface ProtocolPatch {
  title?: string;
  micro_summary?: string;
  tags?: string[];
  protocol_markdown?: string;
}

// --- Meeting history ---

export interface MeetingListItem {
  id: number;
  title: string | null;
  meeting_topic: string | null;
  negotiation_type: string | null;
  started_at: string;
  ended_at: string | null;
  recorded_seconds: number | null;
  segment_count: number;
  suggestion_count: number;
  status: string | null;
  is_recording: boolean;
  customer_id: number | null;
  object_id: number | null;
  customer_name: string | null;
  object_name: string | null;
  finalization_status: FinalizationStatus | null;
  micro_summary: string | null;
  tags: string[];
}

export interface MeetingSuggestionRecord {
  id: number;
  text: string;
  is_auto: boolean;
  suggestion_type: SuggestionType | null;
  trigger: string | null;
  confidence: number | null;
  context_info: string | null;
  source: 'suggestion' | 'strengthen';
  created_at: string;
}

export interface TranscriptSegmentRecord {
  segment_id: string;
  text: string;
  speaker_id: string;
  speaker_label: string | null;
  start_time: number;
  end_time: number;
  wall_clock: string;
  origin: string;
}

export interface MeetingDocumentRecord {
  filename: string;
  doc_type: string;
  doc_type_label: string;
  page_count: number;
}

export interface MeetingDetail {
  id: number;
  title: string | null;
  meeting_topic: string | null;
  meeting_notes: string | null;
  negotiation_type: string | null;
  meeting_role: string | null;
  opponent_weaknesses: string | null;
  started_at: string;
  ended_at: string | null;
  recorded_seconds: number | null;
  status: string | null;
  customer_id: number | null;
  object_id: number | null;
  customer_name: string | null;
  object_name: string | null;
  micro_summary: string | null;
  tags_json: string | null;
  segments: TranscriptSegmentRecord[];
  suggestions: MeetingSuggestionRecord[];
  documents: MeetingDocumentRecord[];
}

// --- Этап 7: controlled auto-learning / база знаний ---

export type LearningCandidateType =
  | 'term' | 'trigger_phrase' | 'playbook' | 'counterparty_trait' | 'forbidden_phrase';

export type KnowledgeScope = 'global' | 'customer' | 'object';

export interface LearningCandidate {
  id: number;
  owner_user_id: number;
  customer_id: number | null;
  object_id: number | null;
  meeting_id: number | null;
  candidate_type: LearningCandidateType;
  title: string;
  payload: Record<string, unknown>;
  source_text: string | null;
  source_refs: Array<Record<string, unknown>>;
  confidence: number | null;
  status: 'pending' | 'approved' | 'rejected';
  reviewed_by_user_id: number | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface GlossaryTerm {
  id: number;
  customer_id: number | null;
  object_id: number | null;
  term: string;
  definition: string;
  aliases_json: string | null;
  scope: KnowledgeScope;
  status: string;
  use_count: number;
  created_from_meeting_id: number | null;
  created_at: string;
}

export interface TriggerPhrase {
  id: number;
  customer_id: number | null;
  object_id: number | null;
  phrase: string;
  event_type: string;
  recommended_reaction: string;
  scope: KnowledgeScope;
  status: string;
  use_count: number;
  created_from_meeting_id: number | null;
  created_at: string;
}

export interface NegotiationPlaybook {
  id: number;
  customer_id: number | null;
  object_id: number | null;
  situation: string;
  recommended_phrase: string;
  technique: string;
  ask_in_return_json: string | null;
  risks_json: string | null;
  scope: KnowledgeScope;
  status: string;
  use_count: number;
  created_from_meeting_id: number | null;
  created_at: string;
}

export interface CounterpartyTrait {
  id: number;
  customer_id: number | null;
  object_id: number | null;
  trait: string;
  evidence: string | null;
  recommended_strategy: string | null;
  scope: 'customer' | 'object';
  status: string;
  confidence: number | null;
  created_from_meeting_id: number | null;
  created_at: string;
}

export interface ForbiddenPhrase {
  id: number;
  customer_id: number | null;
  object_id: number | null;
  phrase_or_risk: string;
  better_alternative: string | null;
  reason: string | null;
  scope: KnowledgeScope;
  status: string;
  created_from_meeting_id: number | null;
  created_at: string;
}

export type KnowledgeKind = 'terms' | 'triggers' | 'playbooks' | 'traits' | 'forbidden';

// --- Этап 8: предыдущие встречи как контекст ---

export interface PreviousMeetingSummaryCard {
  meeting_id: number;
  title: string | null;
  micro_summary: string | null;
  customer_id: number | null;
  customer_name: string | null;
  object_id: number | null;
  object_name: string | null;
  status: string | null;
  finalization_status: string | null;
  started_at: string | null;
  ended_at: string | null;
  tags: string[];
  has_protocol: boolean;
  decisions_count: number;
  action_items_count: number;
  risks_count: number;
  open_questions_count: number;
}

export interface PreviousMeetingCandidate extends PreviousMeetingSummaryCard {
  already_added: boolean;
}

export type ContextSourceType =
  | 'previous_meeting' | 'document' | 'manual' | 'customer_profile' | 'object_profile' | 'rag_folder';

export interface MeetingContextSource {
  id: number;
  meeting_id: number;
  source_type: ContextSourceType;
  source_id: number | null;
  included: boolean;
  priority: number;
  added_by_user_id: number | null;
  metadata_json: string | null;
  created_at: string;
  updated_at: string;
  summary: PreviousMeetingSummaryCard | null;
  access_lost: boolean;
}

export interface MeetingContextSourceCreate {
  source_type?: ContextSourceType;
  source_id?: number | null;
  included?: boolean;
  priority?: number;
  metadata_json?: string | null;
}

export interface MeetingContextSourceUpdate {
  included?: boolean;
  priority?: number;
  metadata_json?: string | null;
}

// --- Этап 9: AI-настройки (профили, режимы, настройки встречи) ---

export type SuggestionMode = 'fast' | 'balanced' | 'deep';

export interface AISettingsProfile {
  id: number;
  owner_user_id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  profile_type: string;
  stt_provider: string | null;
  stt_model: string | null;
  llm_provider: string | null;
  live_suggestion_model: string | null;
  strengthen_model: string | null;
  finalization_model: string | null;
  learning_model: string | null;
  suggestion_mode: SuggestionMode;
  auto_suggestions_enabled: boolean;
  document_context_enabled: boolean;
  knowledge_context_enabled: boolean;
  previous_meetings_context_enabled: boolean;
  suggestion_structured_enabled: boolean;
  finalization_enabled: boolean;
  learning_extraction_enabled: boolean;
  conversation_tree_enabled: boolean;
  max_auto_cards: number;
  max_manual_cards: number;
  auto_suggestion_min_interval_seconds: number;
  document_context_max_chunks: number | null;
  document_context_max_chars: number | null;
  previous_context_max_meetings: number | null;
  previous_context_max_chars: number | null;
  knowledge_context_max_items: number | null;
  settings_json: string | null;
  created_at: string;
  updated_at: string;
}

export type AISettingsProfileInput = Partial<Omit<AISettingsProfile,
  'id' | 'owner_user_id' | 'is_default' | 'profile_type' | 'settings_json' | 'created_at' | 'updated_at'>> & {
  name?: string;
};

export interface AISettingsResolved {
  stt_provider: string | null;
  stt_model: string | null;
  llm_provider: string | null;
  live_suggestion_model: string | null;
  strengthen_model: string | null;
  finalization_model: string | null;
  learning_model: string | null;
  mode: SuggestionMode;
  auto_suggestions_enabled: boolean;
  suggestion_structured_enabled: boolean;
  document_context_enabled: boolean;
  knowledge_context_enabled: boolean;
  previous_meetings_context_enabled: boolean;
  finalization_enabled: boolean;
  learning_extraction_enabled: boolean;
  conversation_tree_enabled: boolean;
  max_auto_cards: number;
  max_manual_cards: number;
  auto_suggestion_min_interval_seconds: number;
  document_context_max_chunks: number | null;
  document_context_max_chars: number | null;
  previous_context_max_meetings: number | null;
  previous_context_max_chars: number | null;
  knowledge_context_max_items: number | null;
  profile_id: number | null;
}

export interface MeetingAISettings {
  meeting_id: number;
  profile_id: number | null;
  resolved: AISettingsResolved;
  has_snapshot: boolean;
  can_edit: boolean;
}

export type MeetingAISettingsPatch = Partial<Pick<AISettingsResolved,
  'mode' | 'stt_provider' | 'stt_model' | 'llm_provider' | 'live_suggestion_model' | 'strengthen_model' |
  'finalization_model' | 'learning_model' | 'auto_suggestions_enabled' | 'suggestion_structured_enabled' |
  'document_context_enabled' | 'knowledge_context_enabled' | 'previous_meetings_context_enabled' |
  'finalization_enabled' | 'learning_extraction_enabled' | 'conversation_tree_enabled' | 'max_auto_cards' | 'max_manual_cards' |
  'auto_suggestion_min_interval_seconds' | 'document_context_max_chunks' | 'document_context_max_chars' |
  'previous_context_max_meetings' | 'previous_context_max_chars' | 'knowledge_context_max_items'>>;

export interface AISettingsOptions {
  available_stt_providers: string[];
  available_stt_models: Record<string, string[]>;
  available_llm_providers: string[];
  available_llm_models: string[];
  supported_modes: SuggestionMode[];
  defaults_from_config: AISettingsResolved;
  feature_flags: Record<string, boolean>;
}
