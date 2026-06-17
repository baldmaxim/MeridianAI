/**
 * IconSwap — icon-swap (transitions.dev 09-icon-swap).
 * Два значка в одном слоте кросс-фейдятся с блюром и масштабом.
 * Чистый CSS, без JS-оркестрации: меняется только data-state.
 *
 *   <IconSwap state={open ? 'b' : 'a'} a={<ChevronRight/>} b={<ChevronDown/>} />
 */
interface Props {
  state: 'a' | 'b';
  a: React.ReactNode;
  b: React.ReactNode;
  style?: React.CSSProperties;
  className?: string;
}

export function IconSwap({ state, a, b, style, className = '' }: Props) {
  return (
    <span className={`t-icon-swap ${className}`.trim()} data-state={state} style={style}>
      <span className="t-icon" data-icon="a">{a}</span>
      <span className="t-icon" data-icon="b">{b}</span>
    </span>
  );
}
