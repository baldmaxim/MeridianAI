import { useRef } from 'react';

/**
 * AvatarGroup — avatar-group-hover (transitions.dev 11).
 * Наведение на элемент горизонтального ряда поднимает его и с power-falloff
 * приподнимает соседей; на mouseleave всё возвращается с пружинкой.
 * Ключевой приём (см. SKILL.md): transition-timing-function ставится инлайном
 * ДО записи --shift/--scale-active — ease-in на вход, bouncy ease-out на возврат.
 * Reduced-motion гасится CSS-guard'ом класса .t-avatar.
 *
 *   <AvatarGroup items={users.map(u => <Avatar key={u.id} user={u} />)} />
 */
interface Props {
  items: React.ReactNode[];
  style?: React.CSSProperties;
  className?: string;
  itemStyle?: React.CSSProperties;
}

export function AvatarGroup({ items, style, className = '', itemStyle }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);

  const setShifts = (activeIdx: number | null, phase: 'in' | 'out') => {
    if (!rootRef.current) return;
    const cs = getComputedStyle(document.documentElement);
    const num = (name: string, fb: number) => {
      const v = parseFloat(cs.getPropertyValue(name));
      return Number.isFinite(v) ? v : fb;
    };
    const ease = (name: string, fb: string) => cs.getPropertyValue(name).trim() || fb;

    const lift = num('--avatar-lift', -4);
    const falloff = num('--avatar-falloff', 0.45);
    const scale = num('--avatar-scale', 1.05);
    const tf =
      phase === 'out'
        ? ease('--avatar-ease-out', 'cubic-bezier(0.34, 3.85, 0.64, 1)')
        : ease('--avatar-ease-in', 'cubic-bezier(0.22, 1, 0.36, 1)');

    rootRef.current.querySelectorAll<HTMLElement>('.t-avatar').forEach((el, i) => {
      el.style.transitionTimingFunction = tf;
      if (activeIdx == null) {
        el.style.setProperty('--shift', '0px');
        el.style.setProperty('--scale-active', '1');
        return;
      }
      const dist = Math.abs(i - activeIdx);
      el.style.setProperty('--shift', (lift * Math.pow(falloff, dist)).toFixed(3) + 'px');
      el.style.setProperty('--scale-active', i === activeIdx ? String(scale) : '1');
    });
  };

  return (
    <div
      ref={rootRef}
      className={className}
      style={style}
      onMouseLeave={() => setShifts(null, 'out')}
    >
      {items.map((node, i) => (
        <div
          key={i}
          className="t-avatar"
          style={itemStyle}
          onMouseEnter={() => setShifts(i, 'in')}
        >
          {node}
        </div>
      ))}
    </div>
  );
}
