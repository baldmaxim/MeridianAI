import { useMemo, useRef, useState } from 'react';
import { Dropdown } from './Dropdown';
import { TextInput } from './TextInput';
import styles from './SelectShared.module.css';

/**
 * Combobox — анимированная замена <input list> + <datalist> (transitions.dev 05).
 * Свободный ввод текста + «выпадающий» список подсказок (Dropdown: scale+opacity,
 * закрытие по Esc/клику вне, reduced-motion-guard). Можно выбрать подсказку
 * ИЛИ вписать своё значение.
 *
 *   <Combobox value={v} onChange={setV} options={names}
 *             placeholder="выберите или впишите нового" style={s.input} />
 */
interface Props {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder?: string;
  disabled?: boolean;
  style?: React.CSSProperties;       // на input (передавать существующий s.input)
  wrapperStyle?: React.CSSProperties;
  className?: string;
  inputClassName?: string;           // класс input (CSS Modules вместо style)
}

export function Combobox({
  value, onChange, options, placeholder, disabled,
  style, wrapperStyle, className = '', inputClassName,
}: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.toLowerCase().includes(q));
  }, [options, value]);

  const shouldOpen = open && filtered.length > 0;

  function close() { setOpen(false); setActive(-1); }
  function pick(opt: string) {
    onChange(opt);
    close();
    inputRef.current?.focus();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!shouldOpen) { setOpen(true); return; }
      e.preventDefault();
      const dir = e.key === 'ArrowDown' ? 1 : -1;
      setActive((a) => (a + dir + filtered.length) % filtered.length);
    } else if (e.key === 'Enter') {
      if (shouldOpen && active >= 0 && filtered[active]) { e.preventDefault(); pick(filtered[active]); }
    } else if (e.key === 'Escape') {
      if (shouldOpen) { e.preventDefault(); close(); }
    }
  }

  return (
    <div className={`${styles.wrap} ${className}`.trim()} style={wrapperStyle}>
      <TextInput
        ref={inputRef}
        type="text"
        disabled={disabled}
        value={value}
        placeholder={placeholder}
        onMouseDown={(e) => e.stopPropagation()} /* клик по input не считается «вне» для Dropdown */
        onFocus={() => setOpen(true)}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1); }}
        onClear={() => { onChange(''); setOpen(true); setActive(-1); }}
        clearLabel="значение"
        onKeyDown={onKeyDown}
        inputClassName={inputClassName}
        style={style}
      />

      <Dropdown
        open={shouldOpen}
        onClose={close}
        origin="top-left"
        className={`${styles.menu} ${styles.menuCombobox}`}
      >
        <div role="listbox" className={styles.list}>
          {filtered.map((o, i) => {
            const isSel = o === value;
            const isActive = i === active;
            return (
              <button
                key={o}
                type="button"
                role="option"
                aria-selected={isSel}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(o)}
                className={`${styles.opt} ${isActive ? styles.optActive : ''} ${isSel ? styles.optSelected : ''}`}
              >
                {o}
              </button>
            );
          })}
        </div>
      </Dropdown>
    </div>
  );
}
