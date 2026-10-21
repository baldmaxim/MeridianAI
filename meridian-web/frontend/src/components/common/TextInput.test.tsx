import { describe, expect, it, vi, afterEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { TextInput } from './TextInput';

afterEach(cleanup);

const Controlled = ({ initial = '', onClear }: { initial?: string; onClear?: () => void }) => {
  const [v, setV] = useState(initial);
  return (
    <TextInput
      aria-label="поле"
      value={v}
      onChange={(e) => setV(e.target.value)}
      onClear={onClear ? () => { onClear(); setV(''); } : undefined}
      clearLabel="имя"
    />
  );
};

describe('TextInput', () => {
  it('крестик скрыт у пустого поля и появляется после ввода', async () => {
    render(<Controlled />);
    expect(screen.queryByRole('button')).toBeNull();
    await userEvent.type(screen.getByRole('textbox'), 'a');
    expect(screen.getByRole('button')).toBeTruthy();
  });

  it('крестик скрыт у disabled и readOnly', () => {
    const { rerender } = render(<TextInput aria-label="x" value="abc" onChange={() => {}} disabled />);
    expect(screen.queryByRole('button')).toBeNull();
    rerender(<TextInput aria-label="x" value="abc" onChange={() => {}} readOnly />);
    expect(screen.queryByRole('button')).toBeNull();
    rerender(<TextInput aria-label="x" value="abc" onChange={() => {}} />);
    expect(screen.getByRole('button')).toBeTruthy();
  });

  it('клик очищает контролируемое поле без onClear и оставляет фокус', async () => {
    render(<Controlled initial="привет" />);
    const input = screen.getByRole<HTMLInputElement>('textbox');
    await userEvent.click(screen.getByRole('button'));
    expect(input.value).toBe('');
    expect(document.activeElement).toBe(input);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('вызывает onClear и оставляет фокус', async () => {
    const onClear = vi.fn();
    render(<Controlled initial="abc" onClear={onClear} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(screen.getByRole('textbox'));
  });

  it('очищает неконтролируемое поле', async () => {
    render(<TextInput aria-label="u" defaultValue="abc" />);
    const input = screen.getByRole<HTMLInputElement>('textbox');
    await userEvent.click(screen.getByRole('button'));
    expect(input.value).toBe('');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('aria-label: по умолчанию и с clearLabel; type="button"', () => {
    const { rerender } = render(<TextInput aria-label="x" value="a" onChange={() => {}} />);
    expect(screen.getByRole('button').getAttribute('aria-label')).toBe('Очистить поле');
    expect(screen.getByRole('button').getAttribute('type')).toBe('button');
    rerender(<TextInput aria-label="x" value="a" onChange={() => {}} clearLabel="логин" />);
    expect(screen.getByRole('button', { name: 'Очистить логин' })).toBeTruthy();
  });

  it('пробрасывает ref и className на нужные элементы', () => {
    const ref = { current: null as HTMLInputElement | null };
    const { container } = render(
      <TextInput ref={ref} aria-label="x" className="wrap" inputClassName="inp" value="" onChange={() => {}} />,
    );
    expect(ref.current).toBe(screen.getByRole('textbox'));
    expect(container.querySelector('.wrap')).toBeTruthy();
    expect(ref.current?.classList.contains('inp')).toBe(true);
  });
});
