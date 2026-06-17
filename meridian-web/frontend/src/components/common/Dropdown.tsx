import { useEffect, useRef } from 'react';
import { useOpenClose } from '../../hooks/useOpenClose';

/**
 * Dropdown — menu-dropdown (transitions.dev 05).
 * Меню растёт из триггера (origin-aware через data-origin), закрывается с
 * .is-closing-доводкой. Оркестрация — useOpenClose. Закрытие по клику вне
 * и по Esc. Позиционирование задаёт вызывающий код через style (компонент
 * владеет только transform/opacity-переходом). Reduced-motion — CSS-guard.
 *
 *   <Dropdown open={menuOpen} onClose={() => setMenuOpen(false)}
 *             origin="top-right" style={{ position:'absolute', top:40, right:0 }}>
 *     …пункты…
 *   </Dropdown>
 */
type Origin =
  | 'top-left' | 'top-center' | 'top-right'
  | 'bottom-left' | 'bottom-center' | 'bottom-right';

interface Props {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  origin?: Origin;
  style?: React.CSSProperties;
  className?: string;
}

export function Dropdown({ open, onClose, children, origin = 'top-left', style, className = '' }: Props) {
  const d = useOpenClose(open, { closeVar: '--dropdown-close-dur', fallbackMs: 150 });
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    // mousedown в следующем тике, чтобы открывающий клик не закрыл сразу
    const t = setTimeout(() => document.addEventListener('mousedown', onDoc), 0);
    window.addEventListener('keydown', onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener('mousedown', onDoc);
      window.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  if (!d.mounted) return null;

  return (
    <div
      ref={ref}
      className={`t-dropdown ${d.cls} ${className}`.trim()}
      data-origin={origin}
      style={style}
    >
      {children}
    </div>
  );
}
