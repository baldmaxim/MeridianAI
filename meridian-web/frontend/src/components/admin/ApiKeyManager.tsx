import { useState } from 'react';
import { useApiKeys, useCreateApiKey, useUpdateApiKey, useDeleteApiKey } from '../../hooks/queries/admin';
import type { ApiKeyInfo } from '../../types';
import { Select, TextInput } from '../common';
import { theme } from '../../styles/theme';
import styles from './ApiKeyManager.module.css';
import { cx } from '../../utils/cx';

const SERVICES = ['openrouter', 'deepgram', 'elevenlabs', 'speechmatics', 'lm_studio'];

/** Цветовой вариант бейджа сервиса (цвета — токены темы, см. ApiKeyManager.module.css). */
const SERVICE_TONES: Record<string, string> = {
  openrouter: styles.toneOpenrouter,
  deepgram: styles.toneDeepgram,
  elevenlabs: styles.toneElevenlabs,
  speechmatics: styles.toneSpeechmatics,
  lm_studio: styles.toneLmStudio,
};

export function ApiKeyManager() {
  const [service, setService] = useState('openrouter');
  const [apiKey, setApiKey] = useState('');

  const { data: keys = [] } = useApiKeys();
  const createKey = useCreateApiKey();
  const updateKey = useUpdateApiKey();
  const deleteKey = useDeleteApiKey();

  const handleAdd = async () => {
    if (!apiKey.trim()) return;
    try {
      await createKey.mutateAsync({ service, apiKey });
      setApiKey('');
    } catch {
      // ошибку мутации показывает глобальный обработчик запросов
    }
  };

  const handleToggle = async (k: ApiKeyInfo) => {
    try {
      await updateKey.mutateAsync({ id: k.id, updates: { is_active: !k.is_active } });
    } catch {
      // ошибку мутации показывает глобальный обработчик запросов
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteKey.mutateAsync(id);
    } catch {
      // ошибку мутации показывает глобальный обработчик запросов
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>API Ключи</span>
      </div>

      <div className={cx('admin-add-row', styles.addRow)}>
        <Select
          value={service}
          onChange={setService}
          options={SERVICES.map((s) => ({ value: s, label: s }))}
          style={selectStyle}
          ariaLabel="Сервис"
        />
        <TextInput
          type="password"
          placeholder="API ключ"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          onClear={() => setApiKey('')}
          clearLabel="API ключ"
          inputClassName={styles.input}
        />
        <button onClick={handleAdd} disabled={createKey.isPending} className={cx('t-btn t-btn-amber', styles.addBtn)}>
          Добавить
        </button>
      </div>

      <div className={styles.list}>
        {keys.map((k) => {
          return (
            <div key={k.id} className={cx('admin-item', styles.item)}>
              <span className={cx(styles.serviceBadge, SERVICE_TONES[k.service])}>
                {k.service.toUpperCase()}
              </span>
              <span className={styles.masked}>{k.key_masked}</span>
              <span className={cx(styles.statusDot, k.is_active ? styles.statusOn : styles.statusOff)} />
              <button
                onClick={() => handleToggle(k)}
                className={cx('t-btn', styles.toggleBtn, k.is_active ? styles.toggleOn : styles.toggleOff)}
              >
                {k.is_active ? 'Вкл' : 'Выкл'}
              </button>
              <button onClick={() => handleDelete(k.id)} className={cx('t-btn t-btn-red', styles.delBtn)}>Отозвать</button>
            </div>
          );
        })}
        {keys.length === 0 && <div className={styles.empty}>Нет ключей. Добавьте API ключи для работы сервисов.</div>}
      </div>
    </div>
  );
}

/** Стиль триггера <Select>: компонент принимает только style (не className). */
const selectStyle: React.CSSProperties = {
  padding: '8px 12px',
  background: theme.bg.input,
  border: `1px solid ${theme.border.default}`,
  borderRadius: 7,
  color: theme.text.primary,
  fontSize: 12,
  fontFamily: theme.font.body,
};
