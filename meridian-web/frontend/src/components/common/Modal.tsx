import { useEffect } from 'react';
import { useOpenClose } from '../../hooks/useOpenClose';
import { theme } from '../../styles/theme';

/**
 * Modal — modal open/close (transitions.dev 06).
 * Backdrop с blur + диалог, масштабирующийся 0.96→1 на открытии и обратно
 * на закрытии. Оркестрация .is-open/.is-closing — через useOpenClose,
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

  return (
    <div style={styles.overlay} onClick={closeOnBackdrop ? onClose : undefined}>
      <div
        className={`t-modal ${m.cls}`.trim()}
        role="dialog"
        aria-modal="true"
        style={{ ...styles.modal, maxWidth }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(8,10,15,0.7)',
    backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center',
    justifyContent: 'center', padding: 16,
  },
  modal: {
    width: '100%', maxHeight: '90vh', overflow: 'auto',
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`,
    borderRadius: 14, padding: 20, display: 'flex', flexDirection: 'column', gap: 14,
  },
};
