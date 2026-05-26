import { useState, useRef, useCallback } from 'react';
import { theme } from '../../styles/theme';

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
      style={{
        border: `2px dashed ${dragOver ? theme.accent.amber : theme.border.default}`,
        borderRadius: 12,
        padding: '32px 24px',
        textAlign: 'center',
        cursor: uploading ? 'wait' : 'pointer',
        background: dragOver ? theme.accent.amberGlow : theme.bg.card,
        transition: 'all 0.2s',
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        onChange={handleChange}
        style={{ display: 'none' }}
      />
      <div
        style={{
          fontSize: 28,
          marginBottom: 8,
          opacity: 0.6,
        }}
      >
        {uploading ? '\u23F3' : '\uD83C\uDFA4'}
      </div>
      <div
        style={{
          fontFamily: theme.font.body,
          fontSize: 13,
          color: theme.text.secondary,
          marginBottom: 4,
        }}
      >
        {uploading
          ? 'Загрузка...'
          : 'Перетащите аудиофайл или нажмите для выбора'}
      </div>
      <div
        style={{
          fontFamily: theme.font.mono,
          fontSize: 10,
          color: theme.text.muted,
        }}
      >
        MP3, WAV, M4A, OGG, FLAC, OPUS, WEBM (макс. 500MB)
      </div>
    </div>
  );
}
