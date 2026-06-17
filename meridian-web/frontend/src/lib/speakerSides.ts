import { theme } from '../styles/theme';

// Диаризация v1 — две публичные стороны: «Мы» / «Не мы».
// ЕДИНСТВЕННОЕ место во фронте, где legacy ally/third_party маппятся к двум сторонам.

export type PublicSpeakerSide = 'self' | 'opponent';

const SELF_ALIASES = new Set(['self', 'ally', 'we', 'our', 'ours', 'us', 'me']);
const OPPONENT_ALIASES = new Set([
  'opponent', 'third_party', 'third', 'customer', 'client',
  'not_us', 'not-we', 'not_we', 'them', 'they', 'other',
]);

/** Любое значение/alias/legacy → 'self' | 'opponent' | '' (не назначено). */
export function toPublicSpeakerSide(side: string | null | undefined): PublicSpeakerSide | '' {
  if (!side) return '';
  const s = String(side).trim().toLowerCase();
  if (SELF_ALIASES.has(s)) return 'self';
  if (OPPONENT_ALIASES.has(s)) return 'opponent';
  return '';
}

/** Цикл переключения стороны: '' → self → opponent → ''. */
export function nextPublicSpeakerSide(side: string | null | undefined): PublicSpeakerSide | '' {
  const cur = toPublicSpeakerSide(side);
  if (cur === '') return 'self';
  if (cur === 'self') return 'opponent';
  return '';
}

export function isPublicSpeakerSide(side: string | null | undefined): side is PublicSpeakerSide {
  return toPublicSpeakerSide(side) !== '';
}

export function speakerSideLabel(side: string | null | undefined): string {
  const s = toPublicSpeakerSide(side);
  if (s === 'self') return 'Мы';
  if (s === 'opponent') return 'Не мы';
  return 'Не назначено';
}

export function speakerSideBadge(side: string | null | undefined): string {
  const s = toPublicSpeakerSide(side);
  if (s === 'self') return 'МЫ';
  if (s === 'opponent') return 'НЕ МЫ';
  return '';
}

export function speakerSideTitle(side: string | null | undefined): string {
  const s = toPublicSpeakerSide(side);
  if (s === 'self') return 'Наша сторона';
  if (s === 'opponent') return 'Другая сторона / оппонент';
  return 'Сторона не назначена';
}

export function speakerSideColor(side: string | null | undefined): string {
  const s = toPublicSpeakerSide(side);
  if (s === 'self') return theme.accent.green;
  if (s === 'opponent') return theme.accent.red;
  return theme.text.muted;
}
