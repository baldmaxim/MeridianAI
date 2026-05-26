import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';

interface Props {
  onStartListening: () => void;
  onStopListening: () => void;
  onRequestSuggestion: () => void;
  onStrengthenPosition: () => void;
  modelName?: string;
}

export function ControlButtons({
  onStartListening,
  onStopListening,
  onRequestSuggestion,
  onStrengthenPosition,
  modelName,
}: Props) {
  const isListening = useMeetingStore((s) => s.isListening);
  const suggestionLoading = useMeetingStore((s) => s.suggestionLoading);
  const strengthenLoading = useMeetingStore((s) => s.strengthenLoading);
  const isConnected = useMeetingStore((s) => s.isConnected);
  const lastError = useMeetingStore((s) => s.lastError);

  const shortModel = modelName
    ? modelName.split('/').pop() || modelName
    : '';

  return (
    <div className="control-buttons" style={styles.container}>
      <button
        className="control-btn-suggest"
        onClick={onRequestSuggestion}
        disabled={!isConnected || suggestionLoading}
        style={styles.btnSuggestion}
      >
        <span className="btn-ico">{'\u26A1'}</span>
        <span className="btn-text">{suggestionLoading ? 'Загрузка...' : 'Подсказка'}</span>
      </button>

      <button
        className="control-btn-main"
        onClick={isListening ? onStopListening : onStartListening}
        disabled={!isConnected}
        style={isListening ? styles.btnStop : styles.btnListen}
      >
        {isListening && <span className="mic-pulse" />}
        <span>{isListening ? 'Слушаю · Стоп' : '\u25B6 Начать'}</span>
      </button>

      <button
        className="control-btn-strengthen"
        onClick={onStrengthenPosition}
        disabled={!isConnected || strengthenLoading}
        style={styles.btnStrengthen}
      >
        <span className="btn-ico">{'\u2191'}</span>
        <span className="btn-text">{strengthenLoading ? 'Анализ...' : 'Усилить позицию'}</span>
      </button>

      <div className="control-spacer" style={styles.spacer} />

      <span className="control-hints" style={styles.hint}>
        <kbd style={styles.kbd}>Space</kbd> пауза · <kbd style={styles.kbd}>H</kbd> подсказка · <kbd style={styles.kbd}>S</kbd> усилить
      </span>

      <div className="control-status" style={styles.status}>
        <span style={statusDot(isConnected && !lastError)} />
        <span style={{ ...styles.statusText, color: lastError ? theme.accent.red : isConnected ? theme.accent.green : theme.accent.red }}>
          {lastError ? lastError : isConnected ? 'Подключено' : 'Отключено'}
          {!lastError && shortModel ? ` · ${shortModel}` : ''}
        </span>
      </div>
    </div>
  );
}

const statusDot = (connected: boolean): React.CSSProperties => ({
  width: 6,
  height: 6,
  borderRadius: '50%',
  background: connected ? theme.accent.green : theme.accent.red,
  flexShrink: 0,
  animation: connected ? 'pulse 1.4s ease-in-out infinite' : 'none',
});

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    height: 52,
    padding: '0 20px',
    background: theme.bg.secondary,
    borderTop: `1px solid ${theme.border.default}`,
    flexShrink: 0,
  },
  spacer: { flex: 1 },
  btnListen: {
    display: 'flex', alignItems: 'center', gap: 7,
    padding: '8px 18px',
    background: theme.accent.amber,
    color: '#080A0F',
    border: 'none',
    borderRadius: 7,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: theme.font.body,
    letterSpacing: '0.02em',
  },
  btnStop: {
    display: 'flex', alignItems: 'center', gap: 7,
    padding: '8px 18px',
    background: theme.accent.red,
    color: '#fff',
    border: 'none',
    borderRadius: 7,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: theme.font.body,
    letterSpacing: '0.02em',
  },
  btnSuggestion: {
    display: 'flex', alignItems: 'center', gap: 7,
    padding: '8px 18px',
    background: theme.bg.elevated,
    color: theme.text.secondary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    fontSize: 12,
    fontWeight: 500,
    cursor: 'pointer',
    fontFamily: theme.font.body,
    letterSpacing: '0.02em',
  },
  btnStrengthen: {
    display: 'flex', alignItems: 'center', gap: 7,
    padding: '8px 18px',
    background: 'transparent',
    color: theme.accent.green,
    border: `1px solid rgba(46,229,157,0.25)`,
    borderRadius: 7,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: theme.font.body,
    letterSpacing: '0.02em',
  },
  hint: {
    fontSize: 9,
    fontFamily: theme.font.mono,
    color: theme.text.muted,
    letterSpacing: '0.06em',
  },
  kbd: {
    display: 'inline-block',
    padding: '1px 5px',
    background: theme.bg.elevated,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 3,
    fontSize: 9,
    fontFamily: theme.font.mono,
    color: theme.text.muted,
  },
  status: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  statusText: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    letterSpacing: '0.06em',
  },
};
