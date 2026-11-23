import { useMeetingStore } from '../../store/meetingStore';
import { TextSwap } from '../common/TextSwap';
import { StartStopButton } from './StartStopButton';
import { SaveToHistoryButton } from './SaveToHistoryButton';
import { SyncBadge } from './SyncBadge';
import styles from './ControlButtons.module.css';

interface Props {
  onStartListening: () => void;
  onStopListening: () => void;
  onRequestSuggestion: () => void;
  onStrengthenPosition: () => void;
  onSaveToHistory: () => void;
  modelName?: string;
}

/**
 * Нижняя панель вкладки «Переговоры» (footer): «Подсказка»/«Усилить позицию» слева,
 * хоткеи и статус подключения справа. На телефоне (<769px) между ними встаёт «Начать/Стоп»
 * (на десктопе он в верхней строке встречи), хоткеи скрыты.
 */
export function ControlButtons({
  onStartListening,
  onStopListening,
  onRequestSuggestion,
  onStrengthenPosition,
  onSaveToHistory,
  modelName,
}: Props) {
  const suggestionLoading = useMeetingStore((s) => s.suggestionLoading);
  const strengthenLoading = useMeetingStore((s) => s.strengthenLoading);
  const isConnected = useMeetingStore((s) => s.isConnected);
  const lastError = useMeetingStore((s) => s.lastError);
  const deviceSync = useMeetingStore((s) => s.deviceSync);

  const shortModel = modelName
    ? modelName.split('/').pop() || modelName
    : '';

  return (
    <div className={`control-buttons ${styles.container}`}>
      <button
        className={`control-btn-suggest t-btn ${styles.btnSuggestion}`}
        onClick={onRequestSuggestion}
        disabled={!isConnected || suggestionLoading}
      >
        <span className="btn-ico">{'⚡'}</span>
        <span className="btn-text">{suggestionLoading ? 'Загрузка...' : 'Подсказка'}</span>
      </button>

      <StartStopButton placement="footer" onStart={onStartListening} onStop={onStopListening} />

      <button
        className={`control-btn-strengthen t-btn t-btn-green ${styles.btnStrengthen}`}
        onClick={onStrengthenPosition}
        disabled={!isConnected || strengthenLoading}
      >
        <span className="btn-ico">{'↑'}</span>
        <span className="btn-text">{strengthenLoading ? 'Анализ...' : 'Усилить позицию'}</span>
      </button>

      <SaveToHistoryButton onSave={onSaveToHistory} />

      <div className={`control-spacer ${styles.spacer}`} />

      <span className={`control-hints ${styles.hint}`}>
        <kbd className={styles.kbd}>Space</kbd> пауза · <kbd className={styles.kbd}>H</kbd> подсказка · <kbd className={styles.kbd}>S</kbd> усилить · <kbd className={styles.kbd}>M</kbd> говорим мы
      </span>

      <div className={`control-status ${styles.status}`}>
        <span className={`${styles.statusDot} ${isConnected && !lastError ? `pulse-dot ${styles.statusDotOn}` : styles.statusDotOff}`} />
        <TextSwap
          value={`${lastError ? lastError : isConnected ? 'Подключено' : 'Отключено'}${!lastError && shortModel ? ` · ${shortModel}` : ''}`}
          className={`${styles.statusText} ${lastError ? styles.statusTextBad : isConnected ? styles.statusTextOk : styles.statusTextBad}`}
        />
        {isConnected && !lastError && <SyncBadge sync={deviceSync} compact />}
      </div>
    </div>
  );
}
