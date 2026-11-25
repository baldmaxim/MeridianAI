import type { FC } from 'react';
import styles from './TenderWonBadge.module.css';

/** Бейдж «Выигран»: тендер по объекту выигран. */
export const TenderWonBadge: FC = () => <span className={styles.badge}>Выигран</span>;
