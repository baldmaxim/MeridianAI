import { useState, useCallback } from 'react';
import { pickFolder } from '../../api/settings';
import { TextInput } from '../common';
import styles from './StorageSettings.module.css';

interface Props {
  localPath: string;
  onChange: (path: string) => void;
}

export function StorageSettings({ localPath, onChange }: Props) {
  const [loading, setLoading] = useState(false);

  const handlePickFolder = useCallback(async () => {
    setLoading(true);
    try {
      const path = await pickFolder();
      if (path) onChange(path);
    } catch {
      // диалог выбора папки недоступен/отменён — путь остаётся прежним
    } finally {
      setLoading(false);
    }
  }, [onChange]);

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>Локальное хранилище</span>
      </div>
      <p className={styles.desc}>
        Путь на сервере для сохранения документов и транскрипций встреч.
      </p>
      <label className={styles.label}>Путь к папке</label>
      <div className={styles.inputRow}>
        <TextInput
          type="text"
          placeholder="C:\Meetings или /home/user/meetings"
          value={localPath}
          onChange={(e) => onChange(e.target.value)}
          onClear={() => onChange('')}
          clearLabel="путь к папке"
          className={styles.inputField}
          inputClassName={styles.input}
        />
        <button onClick={handlePickFolder} disabled={loading} className={styles.browseBtn}>
          {loading ? '...' : 'Обзор'}
        </button>
      </div>
      <p className={styles.hint}>
        Структура: /путь/ID_название/documents/, transcription.txt, context.json
      </p>
    </div>
  );
}
