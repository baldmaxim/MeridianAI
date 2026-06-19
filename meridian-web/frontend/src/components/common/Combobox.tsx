import { useMemo, useRef, useState } from 'react';
import { theme } from '../../styles/theme';
import { Dropdown } from './Dropdown';

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
}

export function Combobox({
  value, onChange, options, placeholder, disabled,
  style, wrapperStyle, className = '',
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
    <div style={{ position: 'relative', ...wrapperStyle }} className={className}>
      <input
        ref={inputRef}
        type="text"
        disabled={disabled}
        value={value}
        placeholder={placeholder}
        onMouseDown={(e) => e.stopPropagation()} /* клик по input не считается «вне» для Dropdown */
        onFocus={() => setOpen(true)}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1); }}
        onKeyDown={onKeyDown}
        style={{ width: '100%', boxSizing: 'border-box', ...style }}
      />

      <Dropdown
        open={shouldOpen}
        onClose={close}
        origin="top-left"
        style={cbStyles.menu}
      >
        <div role="listbox" style={cbStyles.list}>
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
                style={{
                  ...cbStyles.opt,
                  background: isActive ? theme.bg.hover : 'transparent',
                  color: isSel ? theme.accent.amber : theme.text.primary,
                }}
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

const cbStyles: Record<string, React.CSSProperties> = {
  menu: {
    position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 50,
    maxHeight: 240, overflowY: 'auto',
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`,
    borderRadius: 8, boxShadow: '0 12px 32px rgba(0,0,0,0.45)', padding: 4,
  },
  list: { display: 'flex', flexDirection: 'column' },
  opt: {
    display: 'flex', alignItems: 'center', minHeight: 40, padding: '8px 12px',
    border: 'none', borderRadius: 6, background: 'transparent', textAlign: 'left',
    cursor: 'pointer', fontSize: 13, fontFamily: theme.font.body, lineHeight: 1.3,
    transition: 'background 0.12s ease',
  },
};
