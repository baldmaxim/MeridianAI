import { useMeetingStore } from '../../store/meetingStore';
import { removeDocument as apiRemove } from '../../api/documents';
import { theme } from '../../styles/theme';

function getDocColor(ext: string): string {
  switch (ext.toUpperCase()) {
    case 'PDF': return '#FF4B6E';
    case 'DOCX': return '#5B9CF6';
    case 'XLSX': return '#2EE59D';
    default: return '#8896B3';
  }
}

function DocIcon({ ext }: { ext: string }) {
  const color = getDocColor(ext);
  return (
    <div style={{
      width: 38,
      height: 38,
      borderRadius: 8,
      background: color + '14',
      border: `1px solid ${color}28`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: 10,
      color,
      fontFamily: theme.font.mono,
      fontWeight: 700,
      flexShrink: 0,
    }}>
      {ext.toUpperCase()}
    </div>
  );
}

export function DocumentList() {
  const documents = useMeetingStore((s) => s.documents);
  const removeDoc = useMeetingStore((s) => s.removeDocument);

  const handleRemove = async (filename: string) => {
    try {
      await apiRemove(filename);
      removeDoc(filename);
    } catch (err) {
      console.error('Failed to remove document:', err);
    }
  };

  if (documents.length === 0) {
    return null;
  }

  return (
    <div style={styles.list}>
      {documents.map((doc) => {
        const ext = doc.filename.split('.').pop() || 'PDF';
        const extLower = ext.toLowerCase();
        const countLabel = extLower === 'xlsx' ? `${doc.page_count} лист.`
          : ['txt', 'md'].includes(extLower) ? '' : `${doc.page_count} стр.`;
        return (
          <div key={doc.filename} style={styles.item}>
            <DocIcon ext={ext} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={styles.name}>{doc.filename}</div>
              <div style={styles.meta}>{doc.doc_type_label}{countLabel ? ` · ${countLabel}` : ''}</div>
            </div>
            <button onClick={() => handleRemove(doc.filename)} style={styles.removeBtn}>
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  item: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '12px 14px',
    background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
  },
  name: {
    color: theme.text.primary,
    fontSize: 13,
    fontWeight: 500,
    fontFamily: theme.font.body,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  meta: {
    color: theme.text.muted,
    fontSize: 10,
    fontFamily: theme.font.mono,
    marginTop: 2,
  },
  removeBtn: {
    width: 24,
    height: 24,
    borderRadius: 5,
    background: theme.accent.redDim,
    border: '1px solid rgba(255,75,110,0.15)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    fontSize: 11,
    color: theme.accent.red,
    flexShrink: 0,
  },
};
