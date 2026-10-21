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
