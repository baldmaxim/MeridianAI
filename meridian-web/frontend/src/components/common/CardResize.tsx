/**
 * CardResize — card-resize (transitions.dev 01).
 * Твинит width/height контейнера при смене layout-состояния (compact ↔
 * expanded, сворачивающаяся панель). Чистый CSS: размер меняет вызывающий
 * код (через style/класс), переход проигрывается сам. Reduced-motion — CSS-guard.
 *
 *   <CardResize style={{ height: open ? 240 : 64 }}>…</CardResize>
 */
interface Props {
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}

export function CardResize({ children, style, className = '' }: Props) {
  return (
    <div className={`t-resize ${className}`.trim()} style={style}>
      {children}
    </div>
  );
}
