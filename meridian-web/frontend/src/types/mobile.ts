import type { MeetingDocument } from './documents';
import type { FinalizationStatus, MeetingActionItem, MeetingDecision, MeetingOpenQuestion, MeetingRisk } from './finalization';
import type { PreviousMeetingSummaryCard } from './knowledge';

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
