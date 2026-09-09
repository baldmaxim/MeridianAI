import React from 'react';
import { theme } from '../../styles/theme';
import { isSystemAudioSupported } from '../../audio/systemAudio';
import type { AudioSourceLevels, SystemAudioState } from '../../hooks/useAudioRecorder';

interface OnlineAudioPanelProps {
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  state: SystemAudioState | null;
  levels: AudioSourceLevels | null;
  isListening: boolean;
}

/**
 * Захват звука онлайн-встречи (Zoom / Teams / Google Meet).
 *
 * Без него ассистент слышит только нас: голос второй стороны идёт в наушники, а не в
 * микрофон. Переключатель влияет на СЛЕДУЮЩИЙ старт записи — окно выбора вкладки/экрана
 * браузер показывает только по клику «Начать».
 */
export function OnlineAudioPanel({
  enabled, onToggle, state, levels, isListening,
}: OnlineAudioPanelProps) {
  const supported = isSystemAudioSupported();
  const active = !!state?.active;
  const showMeters = isListening && enabled && !!levels;

  const statusText = (): string => {
    if (!supported) return 'браузер не поддерживает';
    if (!enabled) return 'выключено';
    if (!isListening) return 'включится при старте записи';
    if (active) return 'звук встречи пишется';
    if (state?.error) return 'только микрофон';
    return 'ожидание доступа';
  };
  const statusColor = !enabled || !supported ? theme.text.muted
    : active ? theme.accent.green
      : state?.error ? theme.accent.red : theme.accent.amber;

  return (
    <div style={styles.wrap}>
      <label style={styles.row}>
        <input
          type="checkbox"
          checked={enabled && supported}
          disabled={!supported}
          onChange={(e) => onToggle(e.target.checked)}
        />
        <span style={styles.texts}>
          <span style={styles.title}>
            🖥 Звук онлайн-встречи (Zoom / Teams / Meet)
            <span style={{ ...styles.status, color: statusColor }}>· {statusText()}</span>
          </span>
          <span style={styles.hint}>
            {supported
              ? 'При старте записи браузер спросит, чем поделиться: выберите вкладку встречи '
                + '(или весь экран для настольного Zoom/Teams) и ОБЯЗАТЕЛЬНО включите «Поделиться звуком». '
                + 'Без этого слышно только вас.'
              : 'Захват звука встречи умеют Chrome и Edge. В этом браузере запись пойдёт только с микрофона — '
                + 'для очной встречи этого достаточно.'}
          </span>
          {enabled && supported && (
            <span style={styles.hint}>
              В наушниках стороны разделяются точнее: через колонки голос собеседника попадает
              ещё и в микрофон.
            </span>
          )}
        </span>
      </label>

      {state?.error && state.message && <div style={styles.errorBox}>{state.message}</div>}

      {showMeters && (
        <div style={styles.meters}>
          <Meter label="Вы" value={levels!.micRms} color={theme.accent.blue} />
          <Meter
            label="Оппонент"
            value={levels!.systemActive ? levels!.systemRms : 0}
            color={levels!.systemActive ? theme.accent.amber : theme.text.muted}
          />
        </div>
      )}
    </div>
  );
}

function Meter({ label, value, color }: { label: string; value: number; color: string }) {
  // rms обычно сильно ниже 1 — растягиваем, чтобы полоса была читаемой.
  const width = Math.min(100, Math.round(value * 250));
  return (
    <div style={styles.meterRow}>
      <span style={styles.meterLabel}>{label}</span>
      <span style={styles.meterTrack}>
        <span style={{ ...styles.meterFill, width: `${width}%`, background: color }} />
      </span>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    background: theme.bg.secondary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
    margin: '0 12px 8px',
    padding: '10px 14px',
    flexShrink: 0,
  },
  row: { display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' },
  texts: { display: 'flex', flexDirection: 'column', gap: 3 },
  title: {
    color: theme.text.primary, fontSize: 13, fontWeight: 600,
    fontFamily: theme.font.body, display: 'flex', flexWrap: 'wrap', gap: 6,
  },
  status: { fontFamily: theme.font.mono, fontSize: 11, fontWeight: 400 },
  hint: { color: theme.text.muted, fontSize: 11, lineHeight: 1.5, fontFamily: theme.font.body },
  errorBox: {
    marginTop: 8, background: 'rgba(255,75,110,0.1)', color: theme.accent.red,
    borderRadius: 6, padding: '7px 10px', fontSize: 11.5,
  },
  meters: { marginTop: 10, display: 'flex', flexDirection: 'column', gap: 5 },
  meterRow: { display: 'flex', alignItems: 'center', gap: 8 },
  meterLabel: {
    width: 74, flexShrink: 0, color: theme.text.secondary,
    fontSize: 11, fontFamily: theme.font.mono,
  },
  meterTrack: {
    flex: 1, height: 6, background: theme.bg.input, borderRadius: 3,
    overflow: 'hidden', display: 'block',
  },
  meterFill: { height: '100%', display: 'block', borderRadius: 3, transition: 'width 100ms linear' },
};
