import { Select } from '../common';
import styles from './BatchSttSelect.module.css';

const BATCH_PROVIDERS = [
  { value: 'gigaam', label: 'GigaAM (сервер компании, говорящие + таймкоды)' },
  { value: 'deepgram', label: 'Deepgram' },
  { value: 'elevenlabs', label: 'ElevenLabs' },
];

interface Props {
  value: string | null | undefined;
  onChange: (value: string) => void;
  activeServices?: string[];
}

export const BatchSttSelect = ({ value, onChange, activeServices }: Props) => {
  const current = value ?? '';
  const services = activeServices ?? [];
  const options = [
    { value: '', label: 'Как в живой встрече' },
    ...BATCH_PROVIDERS.filter((p) => services.includes(p.value)),
  ];
  // сохранённое значение, которого нет среди доступных, показываем, чтобы не потерять
  if (current && !options.some((o) => o.value === current)) {
    const known = BATCH_PROVIDERS.find((p) => p.value === current);
    options.push({ value: current, label: `${known ? known.label : current} (недоступно)` });
  }

  return (
    <div className={styles.wrap}>
      <label className={styles.label}>Оффлайн-распознавание (загрузка записей)</label>
      <Select
        value={current}
        onChange={onChange}
        options={options}
        triggerClassName={styles.select}
        ariaLabel="Оффлайн-распознавание"
      />
      <span className={styles.hint}>Только для загруженных записей. Живые встречи используют провайдера выше.</span>
    </div>
  );
};
