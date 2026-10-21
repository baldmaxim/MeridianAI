import { useMeetingStore } from '../../store/meetingStore';
import { TextSwap } from '../common/TextSwap';
import { SyncBadge } from './SyncBadge';
import styles from './ControlButtons.module.css';

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

      <button
        className={`control-btn-main t-btn ${isListening ? 't-btn-red' : 't-btn-amber'} ${isListening ? styles.btnStop : styles.btnListen}`}
        onClick={isListening ? onStopListening : onStartListening}
        /* Старт — bootstrap встречи (создаёт встречу и подключается), поэтому НЕ гейтим
           по isConnected: иначе на новой встрече кнопка заблокирована до соединения,
           а соединение невозможно без созданной встречи (дедлок). Стоп тоже доступен. */
      >
        <span className="t-icon-swap" data-state={isListening ? 'b' : 'a'} aria-hidden="true">
          <span className="t-icon" data-icon="a">{'▶'}</span>
          <span className="t-icon" data-icon="b"><span className="mic-pulse" /></span>
        </span>
        <span>{isListening ? 'Слушаю · Стоп' : 'Начать'}</span>
      </button>

      <button
        className={`control-btn-strengthen t-btn t-btn-green ${styles.btnStrengthen}`}
        onClick={onStrengthenPosition}
        disabled={!isConnected || strengthenLoading}
      >
        <span className="btn-ico">{'↑'}</span>
        <span className="btn-text">{strengthenLoading ? 'Анализ...' : 'Усилить позицию'}</span>
      </button>

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
