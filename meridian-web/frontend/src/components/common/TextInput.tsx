import { forwardRef, useCallback, useRef, useState } from 'react';
import type { ChangeEvent, InputHTMLAttributes, MouseEvent } from 'react';
import styles from './TextInput.module.css';

export interface ITextInputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Вызывается по клику на «×». Без него поле очищается нативно (value='' + событие input). */
  onClear?: () => void;
  /** Название поля для aria-label: «Очистить ${clearLabel}». По умолчанию — «Очистить поле». */
  clearLabel?: string;
  /** Класс самого <input> (className уходит на обёртку). */
  inputClassName?: string;
}

const cx = (...parts: Array<string | false | undefined>): string => parts.filter(Boolean).join(' ');

/**
 * Текстовое поле с кнопкой-крестиком «Очистить» (правило проекта для всех текстовых полей).
 * Крестик виден только у непустого поля, не у disabled/readOnly; после очистки фокус остаётся в поле.
 * Работает и с контролируемым (value), и с неконтролируемым (defaultValue) вводом.
 */
export const TextInput = forwardRef<HTMLInputElement, ITextInputProps>(
  ({ onClear, clearLabel, className, inputClassName, onChange, value, defaultValue, disabled, readOnly, ...rest }, ref) => {
    const innerRef = useRef<HTMLInputElement | null>(null);
    const isControlled = value !== undefined;
    const [uncontrolledHasValue, setUncontrolledHasValue] = useState(
      () => defaultValue !== undefined && String(defaultValue).length > 0,
    );
    const hasValue = isControlled ? String(value).length > 0 : uncontrolledHasValue;
    const showClear = hasValue && !disabled && !readOnly;

    const setRefs = useCallback(
      (node: HTMLInputElement | null) => {
        innerRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
      },
      [ref],
    );

    const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
      if (!isControlled) setUncontrolledHasValue(e.target.value.length > 0);
      onChange?.(e);
    };

    const handleClear = () => {
      const input = innerRef.current;
      if (!input) return;
      if (onClear) {
        onClear();
        if (!isControlled) {
          input.value = '';
          setUncontrolledHasValue(false);
        }
      } else {
        // React отслеживает value через нативный сеттер: прямое присваивание не вызовет onChange
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
        setter?.call(input, '');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
      input.focus();
    };

    // Не даём кнопке забрать фокус у поля (на iOS иначе закрывается клавиатура)
    const keepFocus = (e: MouseEvent<HTMLButtonElement>) => e.preventDefault();

    return (
      <div className={cx(styles.wrapper, className)}>
        <input
          {...rest}
          ref={setRefs}
          value={value}
          defaultValue={defaultValue}
          disabled={disabled}
          readOnly={readOnly}
          onChange={handleChange}
          className={cx(styles.input, showClear && styles.hasClear, inputClassName)}
        />
        {showClear && (
          <button
            type="button"
            className={styles.clear}
            aria-label={clearLabel ? `Очистить ${clearLabel}` : 'Очистить поле'}
            tabIndex={-1}
            onMouseDown={keepFocus}
            onClick={handleClear}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>
    );
  },
);

TextInput.displayName = 'TextInput';
