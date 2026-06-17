/**
 * PageTransition — enter-on-mount обёртка для смены роута.
 * App.tsx монтирует одну страницу за раз, поэтому полноценный t-page-slide
 * (две страницы side-by-side) не применим без удержания обеих в DOM. Здесь
 * при смене routeKey div ремоунтится (key=routeKey) и проигрывает только
 * вход — t-page-enter (slide-up + fade + de-blur). Reduced-motion — CSS-guard.
 *
 *   <PageTransition routeKey={route.name}>{renderPage()}</PageTransition>
 */
interface Props {
  routeKey: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}

export function PageTransition({ routeKey, children, style, className = '' }: Props) {
  return (
    <div key={routeKey} className={`t-page-enter ${className}`.trim()} style={style}>
      {children}
    </div>
  );
}
