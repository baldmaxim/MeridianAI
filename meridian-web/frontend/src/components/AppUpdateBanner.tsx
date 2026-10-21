import { useState } from 'react';
import { useMeetingStore } from '../store/meetingStore';
import { useAppUpdate } from '../hooks/useAppUpdate';
import styles from './AppUpdateBanner.module.css';
import { cx } from '../utils/cx';

/**
 * Плавающий тост поверх интерфейса: появляется по центру сверху, когда service worker
 * скачал новую версию фронтенда (needRefresh). Монтируется один раз в корне приложения —
 * он же регистрирует SW. «Обновить» → updateServiceWorker(true) (активация + перезагрузка);
 * при активной записи (isListening) сначала спрашивает подтверждение. «Позже» скрывает тост.
 */
export function AppUpdateBanner() {
  const { updateAvailable, applyUpdate } = useAppUpdate();
  const isListening = useMeetingStore((s) => s.isListening);
  const [dismissed, setDismissed] = useState(false);

  if (!updateAvailable || dismissed) return null;

  const handleUpdate = () => {
    if (
      isListening &&
      !window.confirm(
        'Идёт активная сессия. Обновление перезагрузит страницу и прервёт запись. Обновить сейчас?'
      )
    ) {
      return;
    }
    void applyUpdate();
  };

  return (
    <div className={cx('t-update-banner', styles.bar)}>
      <span className={styles.icon}>⬇</span>
      <div className={styles.body}>
        <span className={styles.title}>Доступно обновление приложения</span>
        {isListening && (
          <span className={styles.warn}>идёт запись — обновление прервёт сессию</span>
        )}
      </div>
      <div className={styles.actions}>
        <button onClick={handleUpdate} className={styles.update}>
          Обновить
        </button>
        <button onClick={() => setDismissed(true)} className={styles.dismiss}>
          Позже
        </button>
      </div>
    </div>
  );
}
