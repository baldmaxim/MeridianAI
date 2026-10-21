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
  check_reasons?: string[];  // почему проверить: не найден пункт, цитата дописана и т.п.
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
