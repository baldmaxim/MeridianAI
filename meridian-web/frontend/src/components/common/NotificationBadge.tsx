/**
 * NotificationBadge — notification-badge (transitions.dev 03).
 * Бейдж въезжает по диагонали на триггер, точка «выскакивает» пружинкой.
 * Родитель должен быть position: relative — бейдж позиционируется
 * абсолютно (top/right переопределяются через style при необходимости).
 *
 *   <button style={{ position:'relative' }}>
 *     🔔 <NotificationBadge show={hasUnread} />
 *   </button>
 */
interface Props {
  show: boolean;
  children?: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}

export function NotificationBadge({ show, children, style, className = '' }: Props) {
  return (
    <span className={`t-badge ${className}`.trim()} data-open={show} style={style}>
      <span className="t-badge-dot">{children}</span>
    </span>
  );
}
