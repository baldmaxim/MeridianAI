import styles from './BatchStatusBadge.module.css';
import { cx } from '../../utils/cx';

/** Цвет и подпись по статусу; цвета — токены темы (классы в BatchStatusBadge.module.css). */
const STATUS_MAP: Record<string, { label: string; tone: string }> = {
  uploaded: { label: 'Загружено', tone: styles.toneNeutral },
  compressing: { label: 'Сжатие...', tone: styles.toneBlue },
  transcribing: { label: 'Транскрипция...', tone: styles.toneAmber },
  translating: { label: 'Перевод...', tone: styles.toneAmber },
  generating_protocol: { label: 'Протокол...', tone: styles.toneAmber },
  done: { label: 'Готово', tone: styles.toneGreen },
  error: { label: 'Ошибка', tone: styles.toneRed },
};

const IN_PROGRESS = ['compressing', 'transcribing', 'translating', 'generating_protocol'];

export function BatchStatusBadge({ status }: { status: string }) {
  const info = STATUS_MAP[status] || STATUS_MAP.uploaded;
  return (
    <span className={cx(styles.badge, info.tone)}>
      {IN_PROGRESS.includes(status) && <span className={styles.pulseDot} />}
      {info.label}
    </span>
  );
}
