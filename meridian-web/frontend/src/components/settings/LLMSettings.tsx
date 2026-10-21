import { theme } from '../../styles/theme';
import { Select } from '../common';
import styles from './LLMSettings.module.css';
import { cx } from '../../utils/cx';

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
    <div className={cx(styles.card, disabled && styles.cardDisabled)}>
      <div className={styles.cardHeader}>
        <span className={styles.dot} />
        <span className={styles.cardTitle}>Языковая модель (OpenRouter)</span>
        {disabled && (
          <span className={styles.inactiveBadge}>Отключено</span>
        )}
      </div>

      {disabled ? (
        <div className={styles.noProvider}>Администратор отключил OpenRouter</div>
      ) : (
        <>
      <label className={styles.label}>Модель</label>
      <Select
        value={model}
        onChange={onModelChange}
        options={MODELS.map((m) => ({ value: m, label: m }))}
        style={selectStyle}
        ariaLabel="Языковая модель"
      />

      <div className={styles.sliderRow}>
        <label className={styles.label}>Температура</label>
        <span className={styles.sliderValue}>{temperature}</span>
      </div>
      <input
        type="range"
        min={0}
        max={1}
        step={0.1}
        value={temperature}
        onChange={(e) => onTemperatureChange(parseFloat(e.target.value))}
        className={styles.range}
      />

      <div className={styles.sliderRow}>
        <label className={styles.label}>Макс. токенов ответа</label>
        <span className={styles.sliderValue}>512</span>
      </div>
      <input
        type="range"
        min={64}
        max={2048}
        step={64}
        defaultValue={512}
        className={styles.range}
      />
        </>
      )}
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
