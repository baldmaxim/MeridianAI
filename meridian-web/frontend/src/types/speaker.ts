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
  side: SpeakerSide | null;
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
  // источник подсказки: 'observer' (числовые метрики) | 'shadow' (rms второго телефона)
  source?: string | null;
  device_count: number;
  window_ms: number;
  auto_apply: boolean;
}

// Участник live-комнаты встречи (одно WS-соединение). Дедуп по user_id — на UI.
export interface RoomParticipant {
  connection_id: string;
  user_id: number | null;
  device_role: string;
  // Ярлык устройства из User-Agent (напр. «iPhone · Safari»); null — не распознан.
  device_label: string | null;
  user_label: string | null;
  can_send_audio: boolean;
  is_active_audio_source: boolean;
  is_helper: boolean;
}

export interface ConversationTopicUpdateInput {
  title?: string;
  status?: ConversationTopicStatus;
  our_summary?: string;
  opponent_summary?: string;
}
