import type { FC } from 'react';
import type { ProjectObject } from '../../types';
import { Modal } from '../common/Modal';
import { cx } from '../../utils/cx';
import styles from './ObjectInfoModal.module.css';

interface IObjectInfoModalProps {
  open: boolean;
  /** Объект держим и после закрытия — иначе содержимое пропадает на exit-анимации */
  object: ProjectObject | null;
  meetingsCount: number;
  onClose: () => void;
  onOpenObject: (id: number) => void;
}

/** Карточка объекта для мобильного списка: адрес не помещается в строку, поэтому он здесь. */
export const ObjectInfoModal: FC<IObjectInfoModalProps> = ({ open, object, meetingsCount, onClose, onOpenObject }) => (
  <Modal open={open} onClose={onClose} maxWidth={420}>
    {object && (
      <>
        <div className={styles.head}>
          <span className={styles.title}>{object.name}</span>
          <button type="button" className={cx('t-btn', styles.close)} onClick={onClose} aria-label="Закрыть">×</button>
        </div>
        <dl className={styles.list}>
          {object.customer_name && (
            <div className={styles.item}>
              <dt className={styles.label}>Заказчик</dt>
              <dd className={styles.value}>{object.customer_name}</dd>
            </div>
          )}
          {object.address && (
            <div className={styles.item}>
              <dt className={styles.label}>Адрес</dt>
              <dd className={cx(styles.value, styles.selectable)}>{object.address}</dd>
            </div>
          )}
          {object.tender_won && (
            <div className={styles.item}>
              <dt className={styles.label}>Тендер</dt>
              <dd className={styles.value}>выигран</dd>
            </div>
          )}
        </dl>
        <div className={styles.value}>Встреч: {meetingsCount}</div>
        <button
          type="button"
          className={cx('t-btn t-btn-amber', styles.openBtn)}
          onClick={() => { onClose(); onOpenObject(object.id); }}
        >
          Открыть объект
        </button>
      </>
    )}
  </Modal>
);
