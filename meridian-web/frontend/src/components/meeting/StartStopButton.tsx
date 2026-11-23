import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import styles from './StartStopButton.module.css';

interface IStartStopButtonProps {
  onStart: () => void;
  onStop: () => void;
  /** top — верхняя строка встречи (≥769px); footer — нижняя панель (на телефоне под пальцем). */
  placement: 'top' | 'footer';
}

/** «Начать / Слушаю · Стоп». Два экземпляра (верх и низ) — видимость переключает CSS. */
export const StartStopButton: FC<IStartStopButtonProps> = ({ onStart, onStop, placement }) => {
  const isListening = useMeetingStore((s) => s.isListening);

  // Старт — bootstrap встречи (создаёт встречу и подключается), поэтому НЕ гейтим
  // по isConnected: иначе на новой встрече кнопка заблокирована до соединения,
  // а соединение невозможно без созданной встречи (дедлок). Стоп тоже доступен.
  return (
    <button
      type="button"
      className={`${placement === 'footer' ? 'control-btn-main ' : ''}t-btn ${isListening ? 't-btn-red' : 't-btn-amber'} ${styles.btn} ${isListening ? styles.stop : styles.listen} ${placement === 'top' ? styles.top : styles.footer}`}
      onClick={isListening ? onStop : onStart}
    >
      <span className="t-icon-swap" data-state={isListening ? 'b' : 'a'} aria-hidden="true">
        <span className="t-icon" data-icon="a">{'▶'}</span>
        <span className="t-icon" data-icon="b"><span className="mic-pulse" /></span>
      </span>
      <span>{isListening ? 'Слушаю · Стоп' : 'Начать'}</span>
    </button>
  );
};
