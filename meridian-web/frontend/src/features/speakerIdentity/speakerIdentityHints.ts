/**
 * Этап 21 — чистые утилиты сборки `speaker_identity_hints` из UI-черновиков.
 *
 * Принципы:
 * - сторона НЕ угадывается: любой черновик по умолчанию side='unknown', пока оператор не выбрал явно;
 * - в backend hint уходят только техническая зона (speaker label / channel) + сторона + функц. роль +
 *   confidence + source. НИКАКИХ display_name / organization / raw device id;
 * - метки транскрипта берём СТРОГО (машинные: SM_0 / Speaker 1 / SPEAKER_1 / S_1 / МЫ / НЕ МЫ / …),
 *   произвольные «Иван:» / «Менеджер:» игнорируем (это PII / свободный текст, не стабильный ключ);
 * - канал/источник = техническая зона записи, НЕ сторона и НЕ личность.
 *
 * Формат совпадает с backend `normalize_identity_hints` (speaker_identity.py):
 *   speaker_labels → source manual_correction (conf 0.95), audio_sources/channel_labels →
 *   source audio_channel (conf 0.75). При side='unknown'/disabled запись пропускается.
 */

import type {
  FunctionalRole,
  RawSpeakerIdentityHints,
  SpeakerIdentityHintDraft,
  SpeakerIdentityHintEntryPatch,
  SpeakerIdentityHintKind,
  SpeakerIdentityHintSource,
  SpeakerIdentityHintsPatch,
  SpeakerSide,
} from './speakerIdentityTypes';

const _SIDE_VALUES: SpeakerSide[] = ['unknown', 'our_side', 'counterparty', 'third_party'];
const _ROLE_VALUES: FunctionalRole[] = [
  'unknown', 'decision_maker', 'project_manager', 'engineer', 'technical_supervisor',
  'procurement', 'legal', 'finance', 'sales', 'contractor', 'customer', 'observer',
];

// Легаси/алиасы сторон (зеркало backend _SIDE_ALIASES, только для чтения существующих hints).
const _SIDE_ALIASES: Record<string, SpeakerSide> = {
  self: 'our_side', me: 'our_side', us: 'our_side', our: 'our_side', ours: 'our_side', we: 'our_side',
  opponent: 'counterparty', not_self: 'counterparty', not_us: 'counterparty', them: 'counterparty',
  client: 'counterparty', customer: 'counterparty',
  observer: 'third_party', external: 'third_party', third: 'third_party',
};

export function normalizeSpeakerSide(value: unknown): SpeakerSide {
  if (typeof value !== 'string') return 'unknown';
  const s = value.trim().toLowerCase();
  if ((_SIDE_VALUES as string[]).includes(s)) return s as SpeakerSide;
  return _SIDE_ALIASES[s] ?? 'unknown';
}

export function normalizeFunctionalRole(value: unknown): FunctionalRole {
  if (typeof value !== 'string') return 'unknown';
  const s = value.trim().toLowerCase();
  if ((_ROLE_VALUES as string[]).includes(s)) return s as FunctionalRole;
  return 'unknown';
}

// --- строгие метки транскрипта ---

const _STRICT_LABEL_PATTERNS: RegExp[] = [
  /^sm_\d{1,3}$/i,              // Speechmatics SM_0, SM_1
  /^speaker[_ ]?\d{1,3}$/i,     // Speaker 1 / SPEAKER_1 / SPEAKER1
  /^s_\d{1,3}$/i,               // S_1
  /^spk[_ ]?\d{1,3}$/i,         // SPK_1
];
const _STRICT_EXACT = new Set([
  'мы', 'не мы', 'our_side', 'counterparty', 'opponent', 'third_party',
]);

/** Строгая метка спикера (машинная), а не свободный текст/имя. */
export function isStrictSpeakerLabel(label: unknown): boolean {
  if (typeof label !== 'string') return false;
  const s = label.replace(/\s+/g, ' ').trim().replace(/:$/, '');
  if (!s) return false;
  if (_STRICT_EXACT.has(s.toLowerCase())) return true;
  return _STRICT_LABEL_PATTERNS.some((re) => re.test(s));
}

/** Уникальные строгие метки спикеров из транскрипта (порядок появления). Имена/произвольный текст отброшены. */
export function extractStrictSpeakerLabelsFromTranscript(
  items: Array<{ speaker?: string | null }> | null | undefined,
): string[] {
  if (!Array.isArray(items)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const it of items) {
    const raw = it?.speaker;
    if (typeof raw !== 'string') continue;
    const label = raw.replace(/\s+/g, ' ').trim().replace(/:$/, '');
    if (!label || !isStrictSpeakerLabel(label)) continue;
    if (seen.has(label)) continue;
    seen.add(label);
    out.push(label);
  }
  return out;
}

// --- черновики ---

function _channelDisplayLabel(key: string): string {
  const m = /^channel_(\d+)$/.exec(key);
  return m ? `Канал ${Number(m[1]) + 1}` : key;
}

function _groupForKind(kind: SpeakerIdentityHintKind): 'speaker_labels' | 'audio_sources' | 'channel_labels' {
  if (kind === 'speaker_label') return 'speaker_labels';
  if (kind === 'channel_label') return 'channel_labels';
  return 'audio_sources';
}

function _sourceForKind(kind: SpeakerIdentityHintKind): SpeakerIdentityHintSource {
  return kind === 'speaker_label' ? 'manual_correction' : 'audio_channel';
}

function _defaultConfidenceForKind(kind: SpeakerIdentityHintKind): number {
  return kind === 'speaker_label' ? 0.95 : 0.75;
}

/** Черновики из строгих меток спикеров (kind=speaker_label, side по умолчанию unknown). */
export function buildSpeakerLabelHintDrafts(labels: string[]): SpeakerIdentityHintDraft[] {
  return labels.map((label) => ({
    kind: 'speaker_label' as const,
    key: label,
    displayLabel: label,
    side: 'unknown' as SpeakerSide,
    functionalRole: 'unknown' as FunctionalRole,
    confidence: _defaultConfidenceForKind('speaker_label'),
    source: _sourceForKind('speaker_label'),
    enabled: true,
  }));
}

/** Черновики каналов записи (channel_0..channel_{n-1}, kind=audio_source). */
export function buildChannelHintDrafts(actualChannelCount: number): SpeakerIdentityHintDraft[] {
  const n = Number.isFinite(actualChannelCount) ? Math.max(0, Math.min(8, Math.floor(actualChannelCount))) : 0;
  if (n < 2) return [];
  const out: SpeakerIdentityHintDraft[] = [];
  for (let i = 0; i < n; i++) {
    const key = `channel_${i}`;
    out.push({
      kind: 'audio_source',
      key,
      displayLabel: _channelDisplayLabel(key),
      side: 'unknown',
      functionalRole: 'unknown',
      confidence: _defaultConfidenceForKind('audio_source'),
      source: _sourceForKind('audio_source'),
      enabled: true,
    });
  }
  return out;
}

/** Развернуть сохранённые hints в черновики (для показа/слияния). Читает только управляемые группы. */
export function existingHintsToDrafts(existingHints: RawSpeakerIdentityHints): SpeakerIdentityHintDraft[] {
  if (!existingHints || typeof existingHints !== 'object') return [];
  const drafts: SpeakerIdentityHintDraft[] = [];
  const groups: [string, SpeakerIdentityHintKind][] = [
    ['speaker_labels', 'speaker_label'],
    ['audio_sources', 'audio_source'],
    ['channel_labels', 'channel_label'],
  ];
  for (const [group, kind] of groups) {
    const g = (existingHints as Record<string, unknown>)[group];
    if (!g || typeof g !== 'object') continue;
    for (const [key, rawEntry] of Object.entries(g as Record<string, unknown>)) {
      const e = (rawEntry && typeof rawEntry === 'object' ? rawEntry : {}) as Record<string, unknown>;
      drafts.push({
        kind,
        key,
        displayLabel: kind === 'speaker_label' ? key : _channelDisplayLabel(key),
        side: normalizeSpeakerSide(e.side),
        functionalRole: normalizeFunctionalRole(e.functional_role),
        confidence: typeof e.confidence === 'number' ? e.confidence : _defaultConfidenceForKind(kind),
        source: _sourceForKind(kind),
        enabled: true,
      });
    }
  }
  return drafts;
}

function _draftKey(d: { kind: SpeakerIdentityHintKind; key: string }): string {
  return `${d.kind}::${d.key}`;
}

/**
 * Наложить сохранённые значения (side/role/confidence) на базовые черновики по (kind,key) и
 * добавить сохранённые ключи, которых нет в базе. Значения из hints перекрывают базовые.
 */
export function mergeHintsIntoDrafts(
  base: SpeakerIdentityHintDraft[],
  existingHints: RawSpeakerIdentityHints,
): SpeakerIdentityHintDraft[] {
  const byKey = new Map<string, SpeakerIdentityHintDraft>();
  for (const d of base) byKey.set(_draftKey(d), { ...d });
  for (const d of existingHintsToDrafts(existingHints)) {
    const k = _draftKey(d);
    const cur = byKey.get(k);
    if (cur) {
      cur.side = d.side;
      cur.functionalRole = d.functionalRole;
      cur.confidence = d.confidence;
      cur.enabled = true;
    } else {
      byKey.set(k, d);
    }
  }
  return [...byKey.values()];
}

/**
 * Собрать тело speaker_identity_hints из черновиков. Пропускает disabled/side='unknown'.
 * Неуправляемые группы существующих hints (например stable_ids) переносятся как есть, чтобы PATCH
 * (полная замена snapshot-значения) их не затёр. Возвращает null, если сохранять нечего.
 */
export function buildSpeakerIdentityHintsPatch(
  drafts: SpeakerIdentityHintDraft[],
  existingHints?: RawSpeakerIdentityHints,
): SpeakerIdentityHintsPatch | null {
  const out: SpeakerIdentityHintsPatch = {};
  // сохранить неуправляемые группы (stable_ids и любые незнакомые) без изменений
  if (existingHints && typeof existingHints === 'object') {
    for (const [group, value] of Object.entries(existingHints)) {
      if (group === 'speaker_labels' || group === 'audio_sources' || group === 'channel_labels') continue;
      if (value && typeof value === 'object') {
        (out as Record<string, unknown>)[group] = value;
      }
    }
  }
  const buckets: Record<string, Record<string, SpeakerIdentityHintEntryPatch>> = {};
  for (const d of drafts) {
    if (!d.enabled) continue;
    const side = normalizeSpeakerSide(d.side);
    if (side === 'unknown') continue;
    const group = _groupForKind(d.kind);
    (buckets[group] ??= {})[d.key] = {
      side,
      functional_role: normalizeFunctionalRole(d.functionalRole),
      // сохраняем confidence черновика (round-trip): у новых строк это дефолт по kind,
      // у загруженных — значение с сервера. Backend всё равно клампит по группе.
      confidence: typeof d.confidence === 'number' ? d.confidence : _defaultConfidenceForKind(d.kind),
      source: _sourceForKind(d.kind),
    };
  }
  for (const [group, bucket] of Object.entries(buckets)) {
    (out as Record<string, unknown>)[group] = bucket;
  }
  return Object.keys(out).length ? out : null;
}

/** Тело PATCH для полной очистки назначений: {speaker_identity_hints: null}. */
export function buildClearSpeakerIdentityHintsPatch(): { speaker_identity_hints: null } {
  return { speaker_identity_hints: null };
}
