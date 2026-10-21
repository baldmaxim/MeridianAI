import type { SuggestionTypeConfig, TriggerKeywordConfig } from './suggestion';

export interface UserSettings {
  stt_provider: string;
  batch_stt_provider?: string | null;
  llm_model: string;
  temperature: number;
  user_role: string;
  use_streaming: boolean;
  diarization: boolean;
  diarization_max_speakers: number;
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

export interface LMStudioTestResult {
  ok: boolean;
  base_url: string;
  models?: string[];
  expected_present?: Record<string, boolean>;
  error?: string;
}
