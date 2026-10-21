import { useMemo, useRef, useState } from 'react';
import { Dropdown } from './Dropdown';
import styles from './SelectShared.module.css';

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
  triggerClassName?: string;         // класс триггера (CSS Modules вместо style)
  ariaLabel?: string;
}

export function Select({
  value, onChange, options, placeholder, disabled,
  style, wrapperStyle, className = '', triggerClassName = '', ariaLabel,
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
    <div className={`${styles.wrap} ${className}`.trim()} style={wrapperStyle}>
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
        className={`${styles.trigger} ${triggerClassName}`.trim()}
        style={style}
      >
        <span className={selected ? styles.value : styles.placeholder}>
          {selected ? selected.label : (placeholder ?? '')}
        </span>
        <span className={`${styles.chev} ${open ? styles.chevOpen : ''}`}>
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
        className={`${styles.menu} ${styles.menuSelect}`}
      >
        <div role="listbox" className={styles.list}>
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
                className={`${styles.opt} ${isActive ? styles.optActive : ''} ${isSel ? styles.optSelected : ''}`}
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
