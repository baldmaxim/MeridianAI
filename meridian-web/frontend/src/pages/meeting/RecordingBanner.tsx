import type { FC } from 'react';
import styles from './RecordingBanner.module.css';

interface IRecordingBannerProps {
  recordingPaused: boolean;
  isListening: boolean;
  onResume: () => void;
}

/**
 * Баннер записи: после прерывания ОС — кнопка «Продолжить»; иначе во время записи —
 * подсказка «не блокируйте экран» (только мобильные, через CSS). Wake Lock держит
 * экран сам; iPhone в фоне при выключенном экране писать не может — об этом и предупреждаем.
 */
export const RecordingBanner: FC<IRecordingBannerProps> = ({ recordingPaused, isListening, onResume }) => {
  if (recordingPaused) {
    return (
      <div className={styles.recoveryBanner} role="alert">
        <span>Запись приостановлена (экран был заблокирован).</span>
        <button className={styles.recoveryBtn} onClick={onResume}>Продолжить запись</button>
      </div>
    );
  }
  if (isListening) {
    return (
      <div className={styles.recHint}>
        Не блокируйте экран. На iPhone запись в фоне при выключенном экране невозможна.
      </div>
    );
  }
  return null;
};
