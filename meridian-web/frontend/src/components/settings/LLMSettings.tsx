import { theme } from '../../styles/theme';

const MODELS = [
  'google/gemini-3-flash-preview',
  'google/gemini-2.5-flash',
  'deepseek/deepseek-v3.2',
  'deepseek/deepseek-chat',
  'anthropic/claude-3.5-sonnet',
  'openai/gpt-4o',
  'openai/gpt-4o-mini',
  'qwen/qwen-2.5-72b-instruct',
];

interface Props {
  model: string;
  temperature: number;
  onModelChange: (model: string) => void;
  onTemperatureChange: (temp: number) => void;
  activeServices?: string[];
}

export function LLMSettings({ model, temperature, onModelChange, onTemperatureChange, activeServices }: Props) {
  const disabled = !activeServices || !activeServices.includes('openrouter');

  return (
    <div style={{ ...styles.card, opacity: disabled ? 0.5 : 1 }}>
      <div style={styles.cardHeader}>
        <span style={styles.dot} />
        <span style={styles.cardTitle}>Языковая модель (OpenRouter)</span>
        {disabled && (
          <span style={styles.inactiveBadge}>Отключено</span>
        )}
      </div>

      {disabled ? (
        <div style={styles.noProvider}>Администратор отключил OpenRouter</div>
      ) : (
        <>
      <label style={styles.label}>Модель</label>
      <select value={model} onChange={(e) => onModelChange(e.target.value)} style={styles.select}>
        {MODELS.map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>

      <div style={styles.sliderRow}>
        <label style={styles.label}>Температура</label>
        <span style={styles.sliderValue}>{temperature}</span>
      </div>
      <input
        type="range"
        min={0}
        max={1}
        step={0.1}
        value={temperature}
        onChange={(e) => onTemperatureChange(parseFloat(e.target.value))}
        style={styles.range}
      />

      <div style={styles.sliderRow}>
        <label style={styles.label}>Макс. токенов ответа</label>
        <span style={styles.sliderValue}>512</span>
      </div>
      <input
        type="range"
        min={64}
        max={2048}
        step={64}
        defaultValue={512}
        style={styles.range}
      />
        </>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 24,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent.amber,
    flexShrink: 0,
  },
  cardTitle: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
    flex: 1,
  },
  inactiveBadge: {
    padding: '3px 10px',
    background: 'rgba(255,75,110,0.12)',
    border: '1px solid rgba(255,75,110,0.25)',
    borderRadius: 5,
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.accent.red,
  },
  noProvider: {
    padding: '10px 14px',
    background: theme.bg.elevated,
    borderRadius: 7,
    color: theme.text.muted,
    fontSize: 12,
    fontFamily: theme.font.body,
  },
  label: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.text.muted,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    marginTop: 8,
  },
  select: {
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 13,
    fontFamily: theme.font.body,
  },
  sliderRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 8,
  },
  sliderValue: {
    fontSize: 13,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    color: theme.accent.amber,
  },
  range: {
    width: '100%',
    accentColor: theme.accent.amber,
  },
};
