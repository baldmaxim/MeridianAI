import type { AudioCaptureMetadataClient } from '../audio/audioCaptureTypes';
import type { SuggestionCard, SuggestionType } from './suggestion';
import type { ClockSyncQuality, CommittedSegmentWire, MultiSourceAlignment, SecondaryShadowDiag, SecondaryShadowTrackSummary, TranscriptWord } from './transcript';
import type { MultiChannelLiveSegment, MultiChannelLiveSnapshot, MultiChannelLiveState, MultiChannelReconciliationState } from './multiChannel';
import type { ConversationTopic, CutoverQualityInfo, PublicSpeakerSide, RoomParticipant, SpeakerSegmentCorrection, SpeakerSide, TranscriptionAuthorityState } from './speaker';

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
  | { type: 'speaker_roles_updated'; roles: Record<string, SpeakerSide>; names?: Record<string, string> }
  | { type: 'meeting_settings_updated'; diarization_max_speakers: number }
  | { type: 'speaker_corrections_updated'; meeting_id: number; corrections: SpeakerSegmentCorrection[] }
  | { type: 'segment_side_hint'; meeting_id: number; segment_key: string; side: PublicSpeakerSide | null; confidence: number; reason: string; source?: string | null; device_count: number; window_ms: number; auto_apply: boolean }
  | { type: 'turn_update'; turn_id: string; speaker: string; text: string; start_time: number; end_time: number; timestamp: string; segment_count: number }
  | { type: 'turns_reset' }
  // --- Этап 2: MeetingRoom / multi-device ---
  | { type: 'room_joined'; meeting_id: number; connection_id: string; device_role: string; can_send_audio: boolean; active_audio_source: string | null }
  | { type: 'device_joined'; meeting_id: number; connection_id: string; device_role: string }
  | { type: 'device_left'; meeting_id: number; connection_id: string }
  | { type: 'room_participants'; meeting_id: number; participants: RoomParticipant[]; active_audio_source: string | null }
  | { type: 'audio_source_busy'; active_audio_source: string | null }
  | { type: 'audio_source_disconnected'; meeting_id?: number }
  | { type: 'recording_status'; recording: boolean; active_audio_source: string | null; active_audio_user_label?: string | null; recording_started_at_ms?: number | null }
  | { type: 'room_status'; meeting_id: number; status: string }
  | { type: 'meeting_closed'; meeting_id: number; reason?: string }
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
  | { type: 'change_settings'; stt_provider?: string; llm_model?: string; temperature?: number; diarization?: boolean; diarization_max_speakers?: number; silence_filter?: boolean }
  | { type: 'save_to_history'; meeting_name?: string }
  | { type: 'set_speaker_role'; name: string; side: PublicSpeakerSide | ''; display_name?: string }
  // Очная встреча: держат кнопку, пока говорит наша сторона (калибровка сторон голосов)
  | { type: 'self_hold'; holding: boolean; client_ts_ms: number }
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
  | { type: 'get_transcription_authority' }
  // Этап 15: безопасная audio capture route metadata (диагностика; без raw label/id)
  | { type: 'audio_capture_metadata'; payload: AudioCaptureMetadataClient }
  // Онлайн-встреча: уровни микрофона (мы) и звука вкладки/экрана (оппонент). Числа, не аудио —
  // по ним backend помечает сторону реплики.
  | {
      type: 'audio_source_levels';
      mic_rms: number;
      mic_peak: number;
      system_rms: number;
      system_peak: number;
      system_active: boolean;
      seq: number;
      client_ts_ms: number;
    };
