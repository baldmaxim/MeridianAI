import { useMemo, useRef, useState } from 'react';
import { theme } from '../../styles/theme';
import { Dropdown } from './Dropdown';

/**
 * Select — анимированная замена нативного <select> (transitions.dev 05).
 * Триггер-кнопка в стиле формы + список опций, который «выпадает» из триггера
 * (Dropdown: scale+opacity, закрытие по Esc/клику вне, reduced-motion-guard).
 * Кастомный на всех устройствах — единый бренд и анимация на тач/десктоп.
 *
 *   <Select value={v} onChange={setV} options={[{value:'a',label:'A'}]}
 *           placeholder="— выберите —" style={styles.select} />
 */
export type SelectOption = { value: string; label: React.ReactNode; disabled?: boolean };

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  style?: React.CSSProperties;       // на триггер (передавать существующий styles.select)
  wrapperStyle?: React.CSSProperties; // на relative-обёртку (ширина/выравнивание)
  className?: string;
  ariaLabel?: string;
}

export function Select({
  value, onChange, options, placeholder, disabled,
  style, wrapperStyle, className = '', ariaLabel,
}: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const btnRef = useRef<HTMLButtonElement>(null);

  const selected = useMemo(() => options.find((o) => o.value === value), [options, value]);

  function close() { setOpen(false); }
  function openMenu() {
    if (disabled) return;
    setActive(options.findIndex((o) => o.value === value));
    setOpen(true);
  }
  function pick(opt: SelectOption) {
    if (opt.disabled) return;
    onChange(opt.value);
    close();
    btnRef.current?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;
    if (!open) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
        e.preventDefault();
        openMenu();
      }
      return;
    }
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const dir = e.key === 'ArrowDown' ? 1 : -1;
      let i = active;
      for (let step = 0; step < options.length; step++) {
        i = (i + dir + options.length) % options.length;
        if (!options[i].disabled) break;
      }
      setActive(i);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (active >= 0 && options[active]) pick(options[active]);
    }
  }

  return (
    <div style={{ position: 'relative', ...wrapperStyle }} className={className}>
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onMouseDown={(e) => e.stopPropagation()} /* чтобы Dropdown не считал клик по триггеру «вне» */
        onClick={() => (open ? close() : openMenu())}
        onKeyDown={onKeyDown}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 8, width: '100%', boxSizing: 'border-box', textAlign: 'left',
          cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1,
          ...style,
        }}
      >
        <span style={selected ? trigStyles.value : trigStyles.placeholder}>
          {selected ? selected.label : (placeholder ?? '')}
        </span>
        <span style={{ ...trigStyles.chev, transform: open ? 'rotate(180deg)' : 'rotate(0deg)' }}>
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
            <path d="M1 3l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5"
              strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </button>

      <Dropdown
        open={open}
        onClose={close}
        origin="top-left"
        style={trigStyles.menu}
      >
        <div role="listbox" style={trigStyles.list}>
          {options.map((o, i) => {
            const isSel = o.value === value;
            const isActive = i === active;
            return (
              <button
                key={o.value}
                type="button"
                role="option"
                aria-selected={isSel}
                disabled={o.disabled}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(o)}
                style={{
                  ...trigStyles.opt,
                  background: isActive ? theme.bg.hover : 'transparent',
                  color: isSel ? theme.accent.amber : theme.text.primary,
                  cursor: o.disabled ? 'not-allowed' : 'pointer',
                  opacity: o.disabled ? 0.45 : 1,
                }}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      </Dropdown>
    </div>
  );
}

const trigStyles: Record<string, React.CSSProperties> = {
  value: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  placeholder: { color: theme.text.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  chev: { display: 'inline-flex', color: theme.text.secondary, flexShrink: 0, transition: 'transform 0.18s ease' },
  menu: {
    position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 50,
    maxHeight: 280, overflowY: 'auto',
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`,
    borderRadius: 8, boxShadow: '0 12px 32px rgba(0,0,0,0.45)', padding: 4,
  },
  list: { display: 'flex', flexDirection: 'column' },
  opt: {
    display: 'flex', alignItems: 'center', minHeight: 40, padding: '8px 12px',
    border: 'none', borderRadius: 6, background: 'transparent', textAlign: 'left',
    fontSize: 13, fontFamily: theme.font.body, lineHeight: 1.3,
    transition: 'background 0.12s ease',
  },
};
