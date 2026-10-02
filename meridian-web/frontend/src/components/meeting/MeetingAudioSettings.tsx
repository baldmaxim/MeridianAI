import React, { useState } from 'react';
import { theme } from '../../styles/theme';
import { Dropdown } from '../common';
import { isSystemAudioSupported } from '../../audio/systemAudio';
import type { AudioRecorderCaptureConfig, AudioSourceLevels, SystemAudioState } from '../../hooks/useAudioRecorder';
import { AudioPreflightPanel } from './AudioPreflightPanel';
import { OnlineAudioPanel } from './OnlineAudioPanel';

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
  const dotColor = state?.active ? theme.accent.green
    : state?.error ? theme.accent.red : theme.accent.amber;

  return (
    <div style={styles.wrap}>
      <style>{`
        @media (max-width: 767px) {
          .mas-label { display: none !important; }
          .mas-pop select { font-size: 16px !important; }
        }
      `}</style>
      <button
        type="button"
        className="t-btn"
        style={styles.btn}
        // Иначе mousedown «вне панели» закроет её, а click тут же откроет снова.
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => setOpen((v) => !v)}
        aria-label="Настройки звука"
        aria-expanded={open}
        title="Микрофон и звук онлайн-встречи"
      >
        <span>⚙</span>
        <span className="mas-label"> Настройки</span>
        {showDot && <span style={{ ...styles.dot, background: dotColor }} />}
      </button>
      <Dropdown
        open={open}
        onClose={() => setOpen(false)}
        origin="top-right"
        className="mas-pop"
        style={styles.pop}
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

const styles: Record<string, React.CSSProperties> = {
  wrap: { position: 'relative', flexShrink: 0 },
  btn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px',
    background: 'transparent', border: `1px solid ${theme.border.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em',
  },
  dot: { width: 7, height: 7, borderRadius: '50%', flexShrink: 0 },
  pop: {
    position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 60,
    width: 'min(380px, calc(100vw - 24px))', maxHeight: 'calc(100dvh - 96px)',
    overflowY: 'auto', overscrollBehavior: 'contain',
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`,
    borderRadius: 8, padding: 8, boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
  },
};
