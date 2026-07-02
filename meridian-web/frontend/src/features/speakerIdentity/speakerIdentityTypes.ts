/**
 * Этап 21 — типы UI подтверждения ролей/сторон участников переговоров.
 *
 * Это НЕ AI-профиль и НЕ выбор режима ассистента. Оператор ЯВНО подтверждает, кто относится к
 * нашей стороне / контрагенту / третьей стороне и (опционально) функциональную роль. Результат
 * сохраняется в существующий скрытый механизм `speaker_identity_hints` (per-meeting snapshot),
 * НЕ создаёт «карточку человека» и НЕ угадывает сторону по тексту.
 *
 * `kind` — техническая зона источника:
 *   speaker_label  — метка диаризатора в транскрипте (SM_0 / Speaker 1) → группа speaker_labels
 *   audio_source   — канал записи (channel_0)                          → группа audio_sources
 *   channel_label  — метка канала (channel_0)                          → группа channel_labels
 * Канал/источник — техническая зона записи, НЕ сторона и НЕ личность.
 */

export type SpeakerSide = 'unknown' | 'our_side' | 'counterparty' | 'third_party';

export type FunctionalRole =
  | 'unknown'
  | 'decision_maker'
  | 'project_manager'
  | 'engineer'
  | 'technical_supervisor'
  | 'procurement'
  | 'legal'
  | 'finance'
  | 'sales'
  | 'contractor'
  | 'customer'
  | 'observer';

export type SpeakerIdentityHintKind = 'speaker_label' | 'audio_source' | 'channel_label';

/** Источник, который прописывается в backend hint (без PII). */
export type SpeakerIdentityHintSource = 'manual_correction' | 'audio_channel';

/**
 * Черновик одной строки в UI. `displayLabel` — только для показа (SM_0 / «Канал 1»), в backend hint
 * НЕ уходит (там нет display_name/organization/raw device id — только техническая зона + сторона).
 */
export interface SpeakerIdentityHintDraft {
  kind: SpeakerIdentityHintKind;
  key: string;
  displayLabel: string;
  side: SpeakerSide;
  functionalRole: FunctionalRole;
  confidence: number;
  source: SpeakerIdentityHintSource;
  enabled: boolean;
}

/** Одна запись в backend-формате speaker_identity_hints (без PII). */
export interface SpeakerIdentityHintEntryPatch {
  side: SpeakerSide;
  functional_role: FunctionalRole;
  confidence: number;
  source: SpeakerIdentityHintSource;
}

/** Тело `speaker_identity_hints` в PATCH (группы → key → запись). */
export interface SpeakerIdentityHintsPatch {
  speaker_labels?: Record<string, SpeakerIdentityHintEntryPatch>;
  stable_ids?: Record<string, unknown>;
  audio_sources?: Record<string, SpeakerIdentityHintEntryPatch>;
  channel_labels?: Record<string, SpeakerIdentityHintEntryPatch>;
}

/** Сырые hints, как они приходят из resolved.speaker_identity_hints (GET). */
export type RawSpeakerIdentityHints = Record<string, unknown> | null;

export const SIDE_OPTIONS: { value: SpeakerSide; label: string }[] = [
  { value: 'unknown', label: '— не указано —' },
  { value: 'our_side', label: 'Наша сторона' },
  { value: 'counterparty', label: 'Контрагент' },
  { value: 'third_party', label: 'Третья сторона' },
];

export const ROLE_OPTIONS: { value: FunctionalRole; label: string }[] = [
  { value: 'unknown', label: '— не указано —' },
  { value: 'decision_maker', label: 'ЛПР (принимает решение)' },
  { value: 'project_manager', label: 'Руководитель проекта' },
  { value: 'engineer', label: 'Инженер' },
  { value: 'technical_supervisor', label: 'Технадзор' },
  { value: 'procurement', label: 'Снабжение / закупки' },
  { value: 'legal', label: 'Юрист' },
  { value: 'finance', label: 'Финансы' },
  { value: 'sales', label: 'Продажи' },
  { value: 'contractor', label: 'Подрядчик' },
  { value: 'customer', label: 'Заказчик' },
  { value: 'observer', label: 'Наблюдатель' },
];

export function sideLabel(side: SpeakerSide): string {
  return SIDE_OPTIONS.find((o) => o.value === side)?.label ?? side;
}

export function roleLabel(role: FunctionalRole): string {
  return ROLE_OPTIONS.find((o) => o.value === role)?.label ?? role;
}
