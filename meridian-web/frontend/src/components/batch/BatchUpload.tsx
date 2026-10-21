import { useState, useRef, useCallback } from 'react';
import styles from './BatchUpload.module.css';
import { cx } from '../../utils/cx';

interface Props {
  onUpload: (file: File) => void;
  uploading: boolean;
}

const ACCEPT = '.mp3,.wav,.m4a,.ogg,.flac,.opus,.webm';

export function BatchUpload({ onUpload, uploading }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) onUpload(file);
    },
    [onUpload]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onUpload(file);
      e.target.value = '';
    },
    [onUpload]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => !uploading && inputRef.current?.click()}
      className={cx(styles.dropZone, dragOver && styles.dropZoneActive, uploading && styles.dropZoneBusy)}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        onChange={handleChange}
        className={styles.fileInput}
      />
      <div className={styles.dropIcon}>
        {uploading ? '\u23F3' : '\uD83C\uDFA4'}
      </div>
      <div className={styles.dropText}>
        {uploading
          ? 'Загрузка...'
          : 'Перетащите аудиофайл или нажмите для выбора'}
      </div>
      <div className={styles.dropHint}>
        MP3, WAV, M4A, OGG, FLAC, OPUS, WEBM (макс. 500MB)
      </div>
    </div>
  );
}
