import { useState, useCallback } from 'react';
import { pickFolder } from '../../api/settings';
import { theme } from '../../styles/theme';

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
    } catch {} finally {
      setLoading(false);
    }
  }, [onChange]);

  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>Локальное хранилище</span>
      </div>
      <p style={styles.desc}>
        Путь на сервере для сохранения документов и транскрипций встреч.
      </p>
      <label style={styles.label}>Путь к папке</label>
      <div style={styles.inputRow}>
        <input
          type="text"
          placeholder="C:\Meetings или /home/user/meetings"
          value={localPath}
          onChange={(e) => onChange(e.target.value)}
          style={styles.input}
        />
        <button onClick={handlePickFolder} disabled={loading} style={styles.browseBtn}>
          {loading ? '...' : 'Обзор'}
        </button>
      </div>
      <p style={styles.hint}>
        Структура: /путь/ID_название/documents/, transcription.txt, context.json
      </p>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 20,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent.amber,
    flexShrink: 0,
  },
  title: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
  },
  desc: {
    fontSize: 12,
    fontFamily: theme.font.body,
    color: theme.text.secondary,
    lineHeight: 1.5,
    margin: 0,
  },
  label: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.accent.amber,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    marginTop: 4,
  },
  inputRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'stretch',
  },
  input: {
    flex: 1,
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 13,
    fontFamily: theme.font.mono,
    outline: 'none',
    minWidth: 0,
  },
  browseBtn: {
    padding: '8px 16px',
    background: theme.bg.elevated,
    border: `1px solid ${theme.border.amber}`,
    borderRadius: 7,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.06em',
    whiteSpace: 'nowrap' as const,
    flexShrink: 0,
  },
  hint: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.text.muted,
    margin: 0,
  },
};
