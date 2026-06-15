export interface User {
  id: number;
  email: string;
  role: 'user' | 'admin';
  display_name: string | null;
  is_active: boolean;
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
  speaker: string;
  text: string;
  words: TranscriptWord[];
  start_time: number;
  end_time: number;
  confidence: number | null;
  timestamp: string;
}

// Speaker negotiation side
export type SpeakerSide = 'self' | 'opponent' | 'ally' | 'third_party';

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

// WebSocket message types
export type WSMessageFromServer =
  | { type: 'transcript'; speaker: string; text: string; timestamp: string; is_partial: boolean }
  | { type: 'committed_transcript'; segment_id: string; speaker: string; text: string; words: TranscriptWord[]; start_time: number; end_time: number; confidence: number | null; timestamp: string }
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
  | { type: 'set_speaker_role'; name: string; side: SpeakerSide }
  | { type: 'change_role'; role_id: number };

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

export interface Department {
  id: number;
  owner_user_id: number;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface DepartmentUser {
  membership_id: number;
  user_id: number;
  email: string;
  display_name: string | null;
  created_at: string;
}

export type GranteeType = 'user' | 'department';
export type AccessLevel = 'view' | 'edit' | 'manage';

export interface ObjectAccessGrant {
  id: number;
  object_id: number;
  grantee_type: GranteeType;
  grantee_user_id: number | null;
  grantee_department_id: number | null;
  access_level: AccessLevel;
  created_by_user_id: number;
  created_at: string;
  grantee_name: string | null;
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
  segment_count: number;
  suggestion_count: number;
  status: string | null;
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
