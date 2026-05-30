import { theme } from '../../styles/theme';

/**
 * SuccessCheck — success-check (transitions.dev 10).
 * Галочка проявляется: fade + rotate + blur + Y-bob + рисование штриха.
 * data-state управляется чисто через React (show ? 'in' : 'out'), без
 * императивного манипулирования атрибутом — поэтому ре-рендер не сбивает
 * анимацию. Reduced-motion гасится CSS-guard'ом. stroke-dasharray задан
 * инлайном под нашу галочку (длина пути ≈ 24 → 26 с запасом).
 */
interface Props {
  show: boolean;
  size?: number;
  color?: string;
}

export function SuccessCheck({ show, size = 16, color = theme.accent.green }: Props) {
  return (
    <span
      className="t-success-check"
      data-state={show ? 'in' : 'out'}
      aria-hidden="true"
      style={{ width: size, height: size, lineHeight: 0, flexShrink: 0 }}
    >
      <svg viewBox="0 0 24 24" fill="none" style={{ width: size, height: size }}>
        <path
          d="M4 12.5 L10 18 L20 6"
          stroke={color}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ strokeDasharray: 26, strokeDashoffset: 26 }}
        />
      </svg>
    </span>
  );
}
