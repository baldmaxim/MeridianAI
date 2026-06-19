import { useExitTransition } from '../../hooks/useExitTransition';

/**
 * Collapse — раскрытие/сворачивание тела секции (transitions.dev 07 panel-reveal).
 * Держит тело смонтированным на время exit-анимации (useExitTransition) и
 * прогоняет slide+fade+blur через класс t-panel-slide. Reduced-motion — CSS-guard.
 * Безопасно вызывать в .map (каждый Collapse — свой инстанс хука).
 *
 *   <Collapse open={expanded} style={styles.body}>…</Collapse>
 */
interface Props {
  open: boolean;
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}

export function Collapse({ open, children, style, className = '' }: Props) {
  const body = useExitTransition(open, { closeVar: '--panel-close-dur' });
  if (!body.mounted) return null;
  return (
    <div className={`t-panel-slide ${className}`.trim()} data-open={body.open} style={style}>
      {children}
    </div>
  );
}
