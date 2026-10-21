import { isSystemAudioSupported } from '../../audio/systemAudio';
import type { AudioSourceLevels, SystemAudioState } from '../../hooks/useAudioRecorder';
import { OnlineAudioMeter } from './OnlineAudioMeter';
import styles from './OnlineAudioPanel.module.css';
import tone from './Tone.module.css';

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
  const statusTone = !enabled || !supported ? tone.muted
    : active ? tone.green
      : state?.error ? tone.red : tone.amber;

  return (
    <div className={styles.wrap}>
      <label className={styles.row}>
        <input
          type="checkbox"
          checked={enabled && supported}
          disabled={!supported}
          onChange={(e) => onToggle(e.target.checked)}
        />
        <span className={styles.texts}>
          <span className={styles.title}>
            🖥 Звук онлайн-встречи (Zoom / Teams / Meet)
            <span className={`${styles.status} ${statusTone}`}>· {statusText()}</span>
          </span>
          <span className={styles.hint}>
            {supported
              ? 'При старте записи браузер спросит, чем поделиться: выберите вкладку встречи '
                + '(или весь экран для настольного Zoom/Teams) и ОБЯЗАТЕЛЬНО включите «Поделиться звуком». '
                + 'Без этого слышно только вас.'
              : 'Захват звука встречи умеют Chrome и Edge. В этом браузере запись пойдёт только с микрофона — '
                + 'для очной встречи этого достаточно.'}
          </span>
          {enabled && supported && (
            <span className={styles.hint}>
              В наушниках стороны разделяются точнее: через колонки голос собеседника попадает
              ещё и в микрофон.
            </span>
          )}
        </span>
      </label>

      {state?.error && state.message && <div className={styles.errorBox}>{state.message}</div>}

      {showMeters && (
        <div className={styles.meters}>
          <OnlineAudioMeter label="Вы" value={levels!.micRms} fillClass={tone.bgBlue} />
          <OnlineAudioMeter
            label="Оппонент"
            value={levels!.systemActive ? levels!.systemRms : 0}
            fillClass={levels!.systemActive ? tone.bgAmber : tone.bgMuted}
          />
        </div>
      )}
    </div>
  );
}
