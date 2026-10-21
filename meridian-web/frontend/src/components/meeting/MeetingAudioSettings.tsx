import { useState } from 'react';
import { Dropdown } from '../common';
import { isSystemAudioSupported } from '../../audio/systemAudio';
import type { AudioRecorderCaptureConfig, AudioSourceLevels, SystemAudioState } from '../../hooks/useAudioRecorder';
import { AudioPreflightPanel } from './AudioPreflightPanel';
import { OnlineAudioPanel } from './OnlineAudioPanel';
import styles from './MeetingAudioSettings.module.css';
import tone from './Tone.module.css';

interface MeetingAudioSettingsProps {
  onConfigChange: (cfg: AudioRecorderCaptureConfig) => void;
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  state: SystemAudioState | null;
  levels: AudioSourceLevels | null;
  isListening: boolean;
}

/**
 * Кнопка «⚙ Настройки» в шапке встречи: микрофон/проверка звука и звук онлайн-встречи
 * в выпадающей панели, чтобы не занимать место над рабочей областью.
 * Закрытие панели размонтирует sound-check — микрофон освобождается.
 */
export function MeetingAudioSettings({
  onConfigChange, enabled, onToggle, state, levels, isListening,
}: MeetingAudioSettingsProps) {
  const [open, setOpen] = useState(false);

  // Точка на кнопке — статус захвата звука встречи (сам блок теперь скрыт в панели).
  const showDot = enabled && isSystemAudioSupported();
  const dotTone = state?.active ? tone.bgGreen
    : state?.error ? tone.bgRed : tone.bgAmber;

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={`t-btn ${styles.btn}`}
        // Иначе mousedown «вне панели» закроет её, а click тут же откроет снова.
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => setOpen((v) => !v)}
        aria-label="Настройки звука"
        aria-expanded={open}
        title="Микрофон и звук онлайн-встречи"
      >
        <span>⚙</span>
        <span className={styles.label}> Настройки</span>
        {showDot && <span className={`${styles.dot} ${dotTone}`} />}
      </button>
      <Dropdown
        open={open}
        onClose={() => setOpen(false)}
        origin="top-right"
        className={styles.pop}
      >
        <AudioPreflightPanel onConfigChange={onConfigChange} />
        <OnlineAudioPanel
          enabled={enabled}
          onToggle={onToggle}
          state={state}
          levels={levels}
          isListening={isListening}
        />
      </Dropdown>
    </div>
  );
}
