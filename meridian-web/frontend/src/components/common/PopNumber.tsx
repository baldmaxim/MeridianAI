/**
 * PopNumber — number-pop-in (transitions.dev 02-number-pop-in).
 * Каждый символ ре-входит с блюром при смене значения.
 * Реализация: ремоунт t-digit-group по key={value} → CSS-анимация
 * t-digit-pop-in проигрывается на маунте. Reduced-motion гасится в CSS.
 */
interface Props {
  value: string | number;
  style?: React.CSSProperties;
  className?: string;
}

export function PopNumber({ value, style, className = '' }: Props) {
  const str = String(value);
  const chars = str.split('');
  return (
    <span
      key={str}
      className={`t-digit-group is-animating ${className}`.trim()}
      style={style}
    >
      {chars.map((ch, i) => {
        const stagger =
          i === chars.length - 2 ? '1' : i === chars.length - 1 ? '2' : undefined;
        return (
          <span className="t-digit" data-stagger={stagger} key={i}>
            {ch}
          </span>
        );
      })}
    </span>
  );
}
