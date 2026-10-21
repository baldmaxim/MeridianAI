import type { FC } from 'react';
import styles from './RoleSwitch.module.css';

interface IRoleSwitchProps {
  /** true — админ смотрит интерфейс как обычный пользователь */
  viewAsUser: boolean;
  onToggle: () => void;
}

/** Слайдер «Админ ⟷ Пользователь» — визуальный предпросмотр интерфейса не-админа (только фронт). */
export const RoleSwitch: FC<IRoleSwitchProps> = ({ viewAsUser, onToggle }) => (
  <button
    type="button"
    onClick={onToggle}
    title={viewAsUser ? 'Вернуться к виду администратора' : 'Посмотреть интерфейс как пользователь'}
    className={styles.wrap}
  >
    <span className={`${styles.label} ${viewAsUser ? '' : styles.labelActive}`}>Админ</span>
    <span className={styles.track}>
      <span className={`${styles.knob} ${viewAsUser ? styles.knobUser : ''}`} />
    </span>
    <span className={`${styles.label} ${viewAsUser ? styles.labelActive : ''}`}>Пользователь</span>
  </button>
);
