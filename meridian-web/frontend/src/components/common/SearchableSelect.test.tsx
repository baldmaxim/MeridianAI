import { describe, expect, it, vi, afterEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SearchableSelect } from './SearchableSelect';

afterEach(cleanup);

const OPTIONS = [
  { value: 'a', label: 'Объект А' },
  { value: 'b', label: 'Объект Б' },
];

describe('SearchableSelect', () => {
  it('меню рендерится в document.body, не внутри обёртки; клик по опции вызывает onChange', async () => {
    const onChange = vi.fn();
    const { container } = render(
      <SearchableSelect value="" onChange={onChange} options={OPTIONS} ariaLabel="Объект" />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Объект' }));

    const opt = await screen.findByRole('option', { name: 'Объект Б' });
    expect(container.contains(opt)).toBe(false);
    expect(document.body.contains(opt)).toBe(true);
    expect(opt.closest('.t-dropdown')?.parentElement).toBe(document.body);

    await userEvent.click(opt);
    expect(onChange).toHaveBeenCalledWith('b');
  });
});
