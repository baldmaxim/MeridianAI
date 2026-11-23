import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useOpenClose } from '../../hooks/useOpenClose';
import styles from './Modal.module.css';

/**
 * Modal — modal open/close (transitions.dev 06).
 * Backdrop с blur + диалог, масштабирующийся 0.96→1 на открытии и обратно
 * на закрытии. Рендерится порталом в document.body: иначе position:fixed
 * оказывается внутри stacking context предков (transform/filter у t-page-enter,
 * t-panel-slide) и поля страницы рисуются поверх модалки. Оркестрация .is-open/.is-closing — через useOpenClose,
 * поэтому exit-анимация не срезается размонтажем. Закрытие по Esc и клику
 * на backdrop. Reduced-motion гасится CSS-guard'ом.
 *
 *   <Modal open={show} onClose={() => setShow(false)} maxWidth={460}>…</Modal>
 */
interface Props {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  maxWidth?: number;
  /** Закрытие по клику на backdrop (по умолчанию включено). */
  closeOnBackdrop?: boolean;
}

export function Modal({ open, onClose, children, maxWidth = 460, closeOnBackdrop = true }: Props) {
  const m = useOpenClose(open, { closeVar: '--modal-close-dur', fallbackMs: 150 });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!m.mounted) return null;

  return createPortal(
    <div className={styles.overlay} onClick={closeOnBackdrop ? onClose : undefined}>
      <div
        className={`t-modal ${m.cls} ${styles.modal}`.trim()}
        role="dialog"
        aria-modal="true"
        style={{ maxWidth }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}
