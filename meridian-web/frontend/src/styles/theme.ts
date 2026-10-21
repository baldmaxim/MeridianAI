/* MERIDIAN Design System — branding/meridian.html
   Значения — CSS-переменные (определены в index.css для тёмной и светлой темы).
   Склеивать цвет с alpha-суффиксом нельзя: используйте withAlpha() из utils/cssVar.ts. */

export const theme = {
  bg: {
    primary: 'var(--bg)',               // void
    secondary: 'var(--bg-secondary)',   // deep
    tertiary: 'var(--bg-tertiary)',     // surface
    elevated: 'var(--bg-elevated)',     // elevated
    card: 'var(--bg-card)',             // card
    chat: 'var(--bg-chat)',
    suggestion: 'var(--bg-suggestion)',
    input: 'var(--bg-input)',
    hover: 'var(--bg-hover)',
  },
  text: {
    primary: 'var(--text)',
    secondary: 'var(--text-secondary)',
    suggestion: 'var(--text-suggestion)',
    muted: 'var(--text-muted)',
  },
  accent: {
    amber: 'var(--accent-amber)',
    amberDim: 'var(--accent-amber-dim)',
    amberGlow: 'var(--accent-amber-glow)',
    blue: 'var(--accent-blue)',
    red: 'var(--accent-red)',
    redDim: 'var(--accent-red-dim)',
    green: 'var(--accent-green)',
    greenDim: 'var(--accent-green-dim)',
    // Legacy aliases
    blueHover: 'var(--accent-blue-hover)',
    greenHover: 'var(--accent-green-hover)',
    yellow: 'var(--accent-yellow)',
  },
  speaker: {
    'Заказчик': 'var(--speaker-customer)',
    'Субподрядчик': 'var(--speaker-subcontractor)',
    'Вы': 'var(--speaker-you)',
    'System': 'var(--speaker-system)',
    'Unknown': 'var(--speaker-unknown)',
  } as Record<string, string>,
  border: {
    default: 'var(--border-default)',
    focus: 'var(--border-focus)',
    amber: 'var(--border-amber)',
  },
  disabled: 'var(--disabled)',
  /** Текст на заливке акцентом/опасным цветом (кнопки): тёмный в dark, белый в light */
  onAccent: 'var(--on-accent)',
  onDanger: 'var(--on-danger)',
  font: {
    heading: "'Syne', sans-serif",
    mono: "'JetBrains Mono', monospace",
    body: "'Inter', sans-serif",
  },
} as const;

/* Speaker text colors */
export const speakerTextColors: Record<string, string> = {
  'Заказчик': 'var(--speaker-text-customer)',
  'Субподрядчик': 'var(--speaker-text-subcontractor)',
  'Вы': 'var(--speaker-text-you)',
  'System': 'var(--speaker-text-system)',
  'Unknown': 'var(--speaker-text-unknown)',
};

/* Палитра для DG_S0, GM_S0, EL_S0…: синий, красный, зелёный, янтарный */
const SPEAKER_BG_CYCLE = ['var(--speaker-customer)', 'var(--speaker-red)', 'var(--speaker-subcontractor)', 'var(--speaker-you)'];
const SPEAKER_TEXT_CYCLE = ['var(--accent-blue)', 'var(--accent-red)', 'var(--accent-green)', 'var(--accent-amber)'];

/* Get speaker bg, with fallback for DG_S0, GM_S0 etc */
export function getSpeakerBg(speaker: string): string {
  if (theme.speaker[speaker]) return theme.speaker[speaker];
  if (speaker.startsWith('DG_S') || speaker.startsWith('GM_S') || speaker.startsWith('EL_S')) {
    const idx = parseInt(speaker.split('S')[1] || '0');
    return SPEAKER_BG_CYCLE[idx % SPEAKER_BG_CYCLE.length];
  }
  return theme.speaker['Unknown'];
}

export function getSpeakerTextColor(speaker: string): string {
  if (speakerTextColors[speaker]) return speakerTextColors[speaker];
  if (speaker.startsWith('DG_S') || speaker.startsWith('GM_S') || speaker.startsWith('EL_S')) {
    const idx = parseInt(speaker.split('S')[1] || '0');
    return SPEAKER_TEXT_CYCLE[idx % SPEAKER_TEXT_CYCLE.length];
  }
  return speakerTextColors['Unknown'];
}
