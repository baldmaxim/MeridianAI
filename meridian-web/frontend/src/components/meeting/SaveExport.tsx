import { useState } from 'react';
import { isAxiosError } from 'axios';
import { saveTranscription } from '../../api/meetings';
import { TextInput } from '../common';
import styles from './SaveExport.module.css';

export function SaveExport() {
  const [filename, setFilename] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const handleSave = async (format: 'txt' | 'json') => {
    if (!filename.trim()) return;
    setSaving(true);
    setMessage('');
    try {
      await saveTranscription(filename.trim(), format);
      setMessage(`Сохранено: ${filename}.${format}`);
      setFilename('');
    } catch (err) {
      const detail = isAxiosError(err) ? err.response?.data?.detail : undefined;
      setMessage(typeof detail === 'string' && detail ? detail : 'Ошибка сохранения');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.container}>
      <TextInput
        type="text"
        placeholder="Имя файла"
        value={filename}
        clearLabel="имя файла"
        onClear={() => setFilename('')}
        onChange={(e) => setFilename(e.target.value)}
        inputClassName={styles.input}
      />
      <div className={styles.buttons}>
        <button
          onClick={() => handleSave('txt')}
          disabled={!filename.trim() || saving}
          className={styles.btn}
        >
          TXT
        </button>
        <button
          onClick={() => handleSave('json')}
          disabled={!filename.trim() || saving}
          className={styles.btn}
        >
          JSON
        </button>
      </div>
      {message && <div className={styles.message}>{message}</div>}
    </div>
  );
}
