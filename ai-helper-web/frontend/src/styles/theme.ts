/* MERIDIAN Design System — branding/meridian.html */

export const theme = {
  bg: {
    primary: '#080A0F',     // void
    secondary: '#0D1018',   // deep
    tertiary: '#111520',    // surface
    elevated: '#161C2C',    // elevated
    card: '#1A2135',        // card
    chat: '#0D1018',
    suggestion: '#0D1018',
    input: '#111520',
    hover: '#161C2C',
  },
  text: {
    primary: '#EDF2FF',
    secondary: '#8896B3',
    suggestion: '#F5A623',
    muted: '#4A5568',
  },
  accent: {
    amber: '#F5A623',
    amberDim: '#C4851A',
    amberGlow: 'rgba(245,166,35,0.12)',
    blue: '#5B9CF6',
    red: '#FF4B6E',
    redDim: 'rgba(255,75,110,0.15)',
    green: '#2EE59D',
    greenDim: 'rgba(46,229,157,0.15)',
    // Legacy aliases
    blueHover: '#4A8BE5',
    greenHover: '#26CC8A',
    yellow: '#F5A623',
  },
  speaker: {
    'Заказчик': 'rgba(91,156,246,0.08)',
    'Субподрядчик': 'rgba(46,229,157,0.08)',
    'Вы': 'rgba(245,166,35,0.08)',
    'System': '#111520',
    'Unknown': '#0D1018',
  } as Record<string, string>,
  border: {
    default: 'rgba(255,255,255,0.06)',
    focus: '#F5A623',
    amber: 'rgba(245,166,35,0.25)',
  },
  disabled: '#2A3040',
  font: {
    heading: "'Syne', sans-serif",
    mono: "'JetBrains Mono', monospace",
    body: "'Inter', sans-serif",
  },
} as const;

/* Speaker text colors */
export const speakerTextColors: Record<string, string> = {
  'Заказчик': '#5B9CF6',
  'Субподрядчик': '#2EE59D',
  'Вы': '#F5A623',
  'System': '#4A5568',
  'Unknown': '#8896B3',
};

/* Get speaker bg, with fallback for DG_S0, GM_S0 etc */
export function getSpeakerBg(speaker: string): string {
  if (theme.speaker[speaker]) return theme.speaker[speaker];
  if (speaker.startsWith('DG_S') || speaker.startsWith('GM_S') || speaker.startsWith('EL_S')) {
    const idx = parseInt(speaker.split('S')[1] || '0');
    const colors = ['rgba(91,156,246,0.08)', 'rgba(255,75,110,0.08)', 'rgba(46,229,157,0.08)', 'rgba(245,166,35,0.08)'];
    return colors[idx % colors.length];
  }
  return theme.speaker['Unknown'];
}

export function getSpeakerTextColor(speaker: string): string {
  if (speakerTextColors[speaker]) return speakerTextColors[speaker];
  if (speaker.startsWith('DG_S') || speaker.startsWith('GM_S') || speaker.startsWith('EL_S')) {
    const idx = parseInt(speaker.split('S')[1] || '0');
    const colors = ['#5B9CF6', '#FF4B6E', '#2EE59D', '#F5A623'];
    return colors[idx % colors.length];
  }
  return '#8896B3';
}
