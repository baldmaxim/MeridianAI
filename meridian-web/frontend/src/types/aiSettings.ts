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
  // Этап 21: скрытый per-meeting маппинг speaker labels/каналов → сторона (подтверждается оператором).
  // Не профильная настройка, без PII. null = нет назначений. См. features/speakerIdentity.
  speaker_identity_hints?: Record<string, unknown> | null;
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
