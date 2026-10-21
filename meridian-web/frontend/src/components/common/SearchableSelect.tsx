import { useEffect, useMemo, useRef, useState } from 'react';
import { Dropdown } from './Dropdown';
import { TextInput } from './TextInput';
import styles from './SelectShared.module.css';

/**
 * SearchableSelect — value-based выбор из списка с поиском (transitions.dev 05).
 * Триггер как у <Select>, но в выпадающем меню сверху — поле-фильтр: можно искать
 * вводом ИЛИ просто листать список. Возвращает `value` (в отличие от Combobox, который
 * отдаёт свободную строку). Анимация/закрытие — общий Dropdown (scale+opacity, Esc/клик
 * вне, reduced-motion-guard).
 *
 *   <SearchableSelect value={v} onChange={setV}
 *     options={[{ value:'1', label:<…/>, search:'имя заказчик' }]}
 *     placeholder="— выберите —" searchPlaceholder="Поиск…" style={styles.select} />
 */
export type SearchableOption = {
  value: string;
  label: React.ReactNode;
  search?: string;   // строка для фильтра (если label — не просто текст)
  disabled?: boolean;
};

interface Props {
  value: string;
  onChange: (value: string) => void;
  options: SearchableOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  emptyText?: string;
  style?: React.CSSProperties;        // на триггер (передавать существующий styles.select)
  wrapperStyle?: React.CSSProperties; // на relative-обёртку
  className?: string;
  triggerClassName?: string;         // класс триггера (CSS Modules вместо style)
  ariaLabel?: string;
}

function optText(o: SearchableOption): string {
  if (o.search != null) return o.search;
  return typeof o.label === 'string' ? o.label : '';
}

export function SearchableSelect({
  value, onChange, options, placeholder, searchPlaceholder = 'Поиск…', disabled,
  emptyText = 'Ничего не найдено', style, wrapperStyle, className = '', triggerClassName = '', ariaLabel,
}: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [query, setQuery] = useState('');
  const btnRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const selected = useMemo(() => options.find((o) => o.value === value), [options, value]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => optText(o).toLowerCase().includes(q));
  }, [options, query]);

  // При открытии — фокус в поле поиска, активна выбранная (или первая) опция.
  useEffect(() => {
    if (!open) return;
    const idx = filtered.findIndex((o) => o.value === value);
    setActive(idx >= 0 ? idx : (filtered.length ? 0 : -1));
    const t = setTimeout(() => searchRef.current?.focus(), 20);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function close() { setOpen(false); setQuery(''); setActive(-1); btnRef.current?.focus(); }
  function openMenu() { if (!disabled) setOpen(true); }
  function pick(opt: SearchableOption) {
    if (opt.disabled) return;
    onChange(opt.value);
    close();
  }

  function onSearchKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!filtered.length) return;
      const dir = e.key === 'ArrowDown' ? 1 : -1;
      let i = active;
      for (let step = 0; step < filtered.length; step++) {
        i = (i + dir + filtered.length) % filtered.length;
        if (!filtered[i].disabled) break;
      }
      setActive(i);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (active >= 0 && filtered[active]) pick(filtered[active]);
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

      <Dropdown open={open} onClose={close} origin="top-left" className={`${styles.menu} ${styles.menuSearchable}`}>
        <TextInput
          ref={searchRef}
          type="text"
          value={query}
          placeholder={searchPlaceholder}
          onChange={(e) => { setQuery(e.target.value); setActive(0); }}
          onClear={() => { setQuery(''); setActive(0); }}
          clearLabel="поиск"
          onKeyDown={onSearchKey}
          className={styles.search}
          inputClassName={styles.searchInput}
        />
        <div role="listbox" className={styles.list}>
          {filtered.length === 0 && <div className={styles.empty}>{emptyText}</div>}
          {filtered.map((o, i) => {
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
