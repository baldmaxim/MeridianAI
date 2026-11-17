import type { FC } from 'react';
import { ThemeSegment } from '../layout/ThemeSegment';
import styles from './AppearanceSettings.module.css';

/** Оформление: выбор темы Система / Светлая / Тёмная. Применяется сразу (хранится в браузере, а не на сервере). */
export const AppearanceSettings: FC = () => (
  <div className={styles.card}>
    <div className={styles.header}>
      <span className={styles.dot} />
      <span className={styles.title}>Оформление</span>
    </div>
    <p className={styles.desc}>
      Тема интерфейса. «Система» следует настройке устройства. Выбор сохраняется в этом браузере и применяется сразу.
    </p>
    <ThemeSegment />
  </div>
);
