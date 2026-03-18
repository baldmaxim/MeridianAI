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

export interface Suggestion {
  text: string;
  is_auto: boolean;
  timestamp: Date;
  type?: SuggestionType;
  trigger?: string;
  confidence?: number;
  context_info?: string;
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

// WebSocket message types
export type WSMessageFromServer =
  | { type: 'transcript'; speaker: string; text: string; timestamp: string; is_partial: boolean }
  | { type: 'committed_transcript'; segment_id: string; speaker: string; text: string; words: TranscriptWord[]; start_time: number; end_time: number; confidence: number | null; timestamp: string }
  | { type: 'batch_finalized'; segments: CommittedSegmentWire[] }
  | { type: 'suggestion'; text: string; is_auto: boolean; suggestion_type?: SuggestionType; trigger?: string; confidence?: number; context_info?: string }
  | { type: 'suggestion_chunk'; text: string }
  | { type: 'suggestion_loading'; loading: boolean }
  | { type: 'strengthen_loading'; loading: boolean }
  | { type: 'analysis_status'; status: string | null }
  | { type: 'meeting_context'; topic: string; notes: string; negotiation_type: string; meeting_role: string; opponent_weaknesses: string }
  | { type: 'meeting_saved'; meeting_id: number }
  | { type: 'error'; message: string }
  | { type: 'status'; message: string };

export type WSMessageToServer =
  | { type: 'start_listening' }
  | { type: 'stop_listening' }
  | { type: 'request_suggestion' }
  | { type: 'strengthen_position' }
  | { type: 'request_batch_finalize' }
  | { type: 'mark_speaker'; name: string }
  | { type: 'update_meeting_context'; topic: string; notes: string; negotiation_type: string; meeting_role: string; opponent_weaknesses: string }
  | { type: 'change_settings'; stt_provider?: string; llm_model?: string; temperature?: number; diarization?: boolean; silence_filter?: boolean }
  | { type: 'save_to_history' };

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
  segments: TranscriptSegmentRecord[];
  suggestions: MeetingSuggestionRecord[];
  documents: MeetingDocumentRecord[];
}
