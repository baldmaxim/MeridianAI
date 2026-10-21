import { theme } from '../../styles/theme';
import { Select } from '../common';
import { SettingToggle } from './SettingToggle';
import styles from './STTSettings.module.css';

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

export function STTSettings({ value, onChange, useStreaming, onStreamingChange, diarization, onDiarizationChange, silenceFilter, onSilenceFilterChange, activeServices }: Props) {
  const available = activeServices
    ? PROVIDERS.filter((p) => activeServices.includes(p.value))
    : [];
  const diarizationCapable = value === 'deepgram' || value === 'speechmatics';

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <span className={styles.dot} />
        <span className={styles.cardTitle}>STT Провайдер</span>
        {available.length > 0 ? (
          <span className={styles.activeBadge}>Активно</span>
        ) : (
          <span className={styles.inactiveBadge}>Нет провайдеров</span>
        )}
      </div>

      <label className={styles.label}>Провайдер распознавания</label>
      {available.length > 0 ? (
        <Select
          value={value}
          onChange={onChange}
          options={available.map((p) => ({ value: p.value, label: p.label }))}
          style={selectStyle}
          ariaLabel="STT провайдер"
        />
      ) : (
        <div className={styles.noProviders}>Администратор не активировал STT-провайдеры</div>
      )}

      <div className={styles.toggles}>
        <SettingToggle
          checked={useStreaming}
          onToggle={() => onStreamingChange(!useStreaming)}
          label="Стриминг в реальном времени"
          description="Транскрипция без задержки, partial results"
        />
        <SettingToggle
          checked={diarization}
          onToggle={() => onDiarizationChange(!diarization)}
          label="Разделение спикеров"
          description={diarizationCapable ? 'Diarization — различать отдельных говорящих (число спикеров задаётся во встрече)' : 'Только для Deepgram / Speechmatics'}
          disabled={!diarizationCapable}
        />
        <SettingToggle
          checked={silenceFilter}
          onToggle={() => onSilenceFilterChange(!silenceFilter)}
          label="Фильтр тишины"
          description="Не отправлять пустые фрагменты на сервер"
        />
      </div>
    </div>
  );
}

/** Стиль триггера <Select>: компонент принимает только style (не className). */
const selectStyle: React.CSSProperties = {
  padding: '10px 14px',
  background: theme.bg.input,
  border: `1px solid ${theme.border.default}`,
  borderRadius: 7,
  color: theme.text.primary,
  fontSize: 13,
  fontFamily: theme.font.body,
};
