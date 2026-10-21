import { useMeetingStore } from '../../store/meetingStore';
import styles from './ModeSwitch.module.css';

/**
 * Слайдер «Диктофон ⟷ Полный» — вид экрана встречи.
 * «Диктофон» = упрощённый вид записи (дефолт на мобильном),
 * «Полный» = детальный интерфейс. Переключатель доступен пользователю во встрече.
 */
export function ModeSwitch() {
  const uiMode = useMeetingStore((s) => s.uiMode);
  const setUiMode = useMeetingStore((s) => s.setUiMode);
  const simple = uiMode === 'simple';

  return (
    <button
      type="button"
      onClick={() => setUiMode(simple ? 'full' : 'simple')}
      title={simple ? 'Переключить в полный интерфейс' : 'Переключить в режим диктофона'}
      className={styles.wrap}
    >
      <span className={`${styles.label} ${simple ? styles.labelOn : styles.labelOff}`}>Диктофон</span>
      <span className={styles.track}>
        <span className={`${styles.knob} ${simple ? '' : styles.knobFull}`} />
      </span>
      <span className={`${styles.label} ${simple ? styles.labelOff : styles.labelOn}`}>Полный</span>
    </button>
  );
}
