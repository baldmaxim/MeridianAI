import type { SuggestionType } from './suggestion';
import type { FinalizationStatus } from './finalization';

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
