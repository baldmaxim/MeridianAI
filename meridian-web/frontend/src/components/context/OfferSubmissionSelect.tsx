import { useEffect, useMemo, useState } from 'react';
import type { FC } from 'react';
import { listObjectOfferSubmissions } from '../../api/objects';
import type { IOfferSubmission } from '../../types';
import { Select } from '../common/Select';
import type { SelectOption } from '../common/Select';
import styles from './OfferSubmissionSelect.module.css';

interface IOfferSubmissionSelectProps {
  objectId: number;
  /** Текущая подача встречи: null — все документы объекта; "" — «Вне папок подач». */
  value: string | null;
  onChange: (value: string | null) => void;
  disabled?: boolean;
}

// Пустая строка — валидный ключ подачи, поэтому «все документы» кодируем отдельным значением.
const ALL_VALUE = '__all__';
const NO_FOLDER_LABEL = 'Вне папок подач';
const toOptionValue = (key: string | null): string => (key == null ? ALL_VALUE : `s:${key}`);
const fromOptionValue = (v: string): string | null => (v === ALL_VALUE ? null : v.slice(2));

/** Селект «Подача КП»: какие документы объекта идут в подсказки — все или только одной подачи. */
export const OfferSubmissionSelect: FC<IOfferSubmissionSelectProps> = ({
  objectId, value, onChange, disabled = false,
}) => {
  const [submissions, setSubmissions] = useState<IOfferSubmission[]>([]);

  useEffect(() => {
    let cancelled = false;
    listObjectOfferSubmissions(objectId)
      .then((list) => { if (!cancelled) setSubmissions(list); })
      .catch(() => { if (!cancelled) setSubmissions([]); });
    return () => { cancelled = true; };
  }, [objectId]);

  const options = useMemo<SelectOption[]>(() => {
    const list: SelectOption[] = [{ value: ALL_VALUE, label: 'Все документы объекта' }];
    submissions.forEach((s, i) => {
      list.push({ value: toOptionValue(s.key), label: i === 0 ? `${s.label} (последняя)` : s.label });
    });
    // Сохранённая подача могла пропасть из списка — не теряем текущее значение.
    if (value != null && !submissions.some((s) => s.key === value)) {
      list.push({ value: toOptionValue(value), label: value || NO_FOLDER_LABEL });
    }
    return list;
  }, [submissions, value]);

  if (submissions.length === 0 && value == null) return null;

  return (
    <div className={styles.wrap}>
      <div className={styles.label}>Подача КП</div>
      <Select
        value={toOptionValue(value)}
        onChange={(v) => onChange(fromOptionValue(v))}
        options={options}
        disabled={disabled}
        triggerClassName={styles.trigger}
        ariaLabel="Подача КП"
      />
      {value == null && (
        <div className={styles.hint}>Выберите подачу, которую обсуждаете</div>
      )}
    </div>
  );
};
