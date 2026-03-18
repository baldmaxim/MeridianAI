import { useState } from 'react';
import { saveTranscription } from '../../api/meetings';
import { theme } from '../../styles/theme';

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
    } catch (err: any) {
      setMessage(err.response?.data?.detail || 'Ошибка сохранения');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={styles.container}>
      <input
        type="text"
        placeholder="Имя файла"
        value={filename}
        onChange={(e) => setFilename(e.target.value)}
        style={styles.input}
      />
      <div style={styles.buttons}>
        <button
          onClick={() => handleSave('txt')}
          disabled={!filename.trim() || saving}
          style={styles.btn}
        >
          TXT
        </button>
        <button
          onClick={() => handleSave('json')}
          disabled={!filename.trim() || saving}
          style={styles.btn}
        >
          JSON
        </button>
      </div>
      {message && <div style={styles.message}>{message}</div>}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    padding: '8px 0',
  },
  input: {
    padding: '8px 12px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 12,
    fontFamily: theme.font.body,
    outline: 'none',
  },
  buttons: {
    display: 'flex',
    gap: 6,
  },
  btn: {
    flex: 1,
    padding: '6px 0',
    background: theme.bg.elevated,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 5,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.body,
  },
  message: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.accent.green,
  },
};
