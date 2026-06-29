import { theme } from '../../styles/theme';
import { Select } from '../common';

const PROVIDERS = [
  { value: 'deepgram', label: 'Deepgram (streaming + диаризация)' },
  { value: 'elevenlabs', label: 'ElevenLabs (streaming)' },
  { value: 'speechmatics', label: 'Speechmatics (streaming + диаризация)' },
];

interface Props {
  value: string;
  onChange: (value: string) => void;
  useStreaming: boolean;
  onStreamingChange: (v: boolean) => void;
  diarization: boolean;
  onDiarizationChange: (v: boolean) => void;
  silenceFilter: boolean;
  onSilenceFilterChange: (v: boolean) => void;
  activeServices?: string[];
}

function Toggle({ checked, onToggle, label, description, disabled }: {
  checked: boolean; onToggle: () => void; label: string; description: string; disabled?: boolean;
}) {
  return (
    <div
      style={{ ...styles.toggleRow, opacity: disabled ? 0.4 : 1, cursor: disabled ? 'not-allowed' : 'pointer' }}
      onClick={disabled ? undefined : onToggle}
    >
      <div>
        <div style={styles.toggleLabel}>{label}</div>
        <div style={styles.toggleDesc}>{description}</div>
      </div>
      <div style={{
        ...styles.toggle,
        background: checked && !disabled ? theme.accent.amber : theme.bg.elevated,
        justifyContent: checked && !disabled ? 'flex-end' : 'flex-start',
      }}>
        <div style={styles.toggleKnob} />
      </div>
    </div>
  );
}

export function STTSettings({ value, onChange, useStreaming, onStreamingChange, diarization, onDiarizationChange, silenceFilter, onSilenceFilterChange, activeServices }: Props) {
  const available = activeServices
    ? PROVIDERS.filter((p) => activeServices.includes(p.value))
    : [];
  const diarizationCapable = value === 'deepgram' || value === 'speechmatics';

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <span style={styles.dot} />
        <span style={styles.cardTitle}>STT Провайдер</span>
        {available.length > 0 ? (
          <span style={styles.activeBadge}>Активно</span>
        ) : (
          <span style={styles.inactiveBadge}>Нет провайдеров</span>
        )}
      </div>

      <label style={styles.label}>Провайдер распознавания</label>
      {available.length > 0 ? (
        <Select
          value={value}
          onChange={onChange}
          options={available.map((p) => ({ value: p.value, label: p.label }))}
          style={styles.select}
          ariaLabel="STT провайдер"
        />
      ) : (
        <div style={styles.noProviders}>Администратор не активировал STT-провайдеры</div>
      )}

      <div style={styles.toggles}>
        <Toggle
          checked={useStreaming}
          onToggle={() => onStreamingChange(!useStreaming)}
          label="Стриминг в реальном времени"
          description="Транскрипция без задержки, partial results"
        />
        <Toggle
          checked={diarization}
          onToggle={() => onDiarizationChange(!diarization)}
          label="Разделение спикеров"
          description={diarizationCapable ? 'Diarization — различать отдельных говорящих (число спикеров задаётся во встрече)' : 'Только для Deepgram / Speechmatics'}
          disabled={!diarizationCapable}
        />
        <Toggle
          checked={silenceFilter}
          onToggle={() => onSilenceFilterChange(!silenceFilter)}
          label="Фильтр тишины"
          description="Не отправлять пустые фрагменты на сервер"
        />
      </div>
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
  activeBadge: {
    padding: '3px 10px',
    background: 'rgba(46,229,157,0.12)',
    border: '1px solid rgba(46,229,157,0.25)',
    borderRadius: 5,
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.accent.green,
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
  noProviders: {
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
  toggles: {
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
    marginTop: 12,
  },
  toggleRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 0',
    borderTop: `1px solid ${theme.border.default}`,
    cursor: 'pointer',
    userSelect: 'none' as const,
  },
  toggleLabel: {
    fontSize: 13,
    fontWeight: 500,
    color: theme.text.primary,
    fontFamily: theme.font.body,
  },
  toggleDesc: {
    fontSize: 11,
    color: theme.text.muted,
    fontFamily: theme.font.body,
    marginTop: 2,
  },
  toggle: {
    width: 42,
    height: 24,
    borderRadius: 12,
    display: 'flex',
    alignItems: 'center',
    padding: 3,
    flexShrink: 0,
    transition: 'background 0.2s',
  },
  toggleKnob: {
    width: 18,
    height: 18,
    borderRadius: '50%',
    background: '#fff',
    transition: 'margin 0.2s',
  },
};
