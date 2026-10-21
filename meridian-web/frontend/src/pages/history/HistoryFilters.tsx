import type { FC } from 'react';
import { Select, TextInput } from '../../components/common';
import type { SelectOption } from '../../components/common';
import styles from './HistoryFilters.module.css';

interface IHistoryFiltersProps {
  customerOptions: SelectOption[];
  objectOptions: SelectOption[];
  customerId: number | '';
  objectId: number | '';
  search: string;
  onCustomerChange: (value: number | '') => void;
  onObjectChange: (value: number | '') => void;
  onSearchChange: (value: string) => void;
  onApplySearch: () => void;
}

const toFilterValue = (v: string): number | '' => (v === '' ? '' : Number(v));

/** Фильтры списка: заказчик, объект, поиск (применяется по кнопке или Enter). */
export const HistoryFilters: FC<IHistoryFiltersProps> = ({
  customerOptions, objectOptions, customerId, objectId, search,
  onCustomerChange, onObjectChange, onSearchChange, onApplySearch,
}) => (
  <div className={styles.filters}>
    <Select
      className={styles.filterSelect}
      ariaLabel="Фильтр по заказчику"
      value={String(customerId)}
      onChange={(v) => onCustomerChange(toFilterValue(v))}
      options={[{ value: '', label: 'Все заказчики' }, ...customerOptions]}
    />
    <Select
      className={styles.filterSelect}
      ariaLabel="Фильтр по объекту"
      value={String(objectId)}
      onChange={(v) => onObjectChange(toFilterValue(v))}
      options={[{ value: '', label: 'Все объекты' }, ...objectOptions]}
    />
    <TextInput
      type="text"
      className={styles.searchField}
      placeholder="Поиск по названию/теме…"
      value={search}
      onChange={(e) => onSearchChange(e.target.value)}
      onClear={() => onSearchChange('')}
      clearLabel="поиск"
      onKeyDown={(e) => { if (e.key === 'Enter') onApplySearch(); }}
    />
    <button className={`t-btn t-btn-amber ${styles.filterBtn}`} onClick={onApplySearch}>Найти</button>
  </div>
);
