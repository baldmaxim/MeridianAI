import { useMeetingStore } from '../../store/meetingStore';
import { removeDocument as apiRemove } from '../../api/documents';
import { DocumentIcon } from './DocumentIcon';
import styles from './DocumentList.module.css';

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
    <div className={styles.list}>
      {documents.map((doc) => {
        const ext = doc.filename.split('.').pop() || 'PDF';
        const extLower = ext.toLowerCase();
        const countLabel = extLower === 'pdf' ? `${doc.page_count} стр.` : '';
        return (
          <div key={doc.filename} className={styles.item}>
            <DocumentIcon ext={ext} />
            <div className={styles.info}>
              <div className={styles.name}>{doc.filename}</div>
              <div className={styles.meta}>{doc.doc_type_label}{countLabel ? ` · ${countLabel}` : ''}</div>
            </div>
            <button onClick={() => handleRemove(doc.filename)} className={styles.removeBtn}>
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
