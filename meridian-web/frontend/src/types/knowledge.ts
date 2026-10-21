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
