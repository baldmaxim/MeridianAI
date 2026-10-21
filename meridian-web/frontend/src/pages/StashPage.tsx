import { useState, useRef, useCallback } from 'react';
import axios from 'axios';
import { useStashFiles, useUploadStash, useDeleteStash } from '../hooks/queries/stash';
import type { StashFile } from '../api/stash';
import { downloadStashFile, getStashDownloadUrls } from '../api/stash';
import { formatFileSize } from '../lib/documentFiles';
import styles from './StashPage.module.css';
import { cx } from '../utils/cx';

interface Props {
  onBack: () => void;
}

/** Текст ошибки FastAPI (detail), если он есть. */
const detailOf = (e: unknown): string | undefined =>
  axios.isAxiosError<{ detail?: string }>(e) ? e.response?.data?.detail : undefined;

function expiryLabel(expires_at: string | null): string {
  if (!expires_at) return '';
  const ms = new Date(expires_at).getTime() - Date.now();
  if (ms <= 0) return 'истёк';
  const days = Math.ceil(ms / 86_400_000);
  if (days <= 1) return 'удалится сегодня';
  return `удалится через ${days} дн.`;
}

/** Уникальное имя в папке: при коллизии дописывает « (2)», « (3)» перед расширением. */
function uniqueName(name: string, used: Set<string>): string {
  const clean = name || 'file';
  if (!used.has(clean)) { used.add(clean); return clean; }
  const dot = clean.lastIndexOf('.');
  const base = dot > 0 ? clean.slice(0, dot) : clean;
  const ext = dot > 0 ? clean.slice(dot) : '';
  let i = 2;
  while (used.has(`${base} (${i})${ext}`)) i++;
  const final = `${base} (${i})${ext}`;
  used.add(final);
  return final;
}

export function StashPage({ onBack }: Props) {
  const { data: files = [] } = useStashFiles();
  const uploadMut = useUploadStash();
  const deleteMut = useDeleteStash();

  const [dragOver, setDragOver] = useState(false);
  const [pct, setPct] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [dlProgress, setDlProgress] = useState<{ done: number; total: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFiles = useCallback(
    async (list: FileList | File[]) => {
      const arr = Array.from(list);
      for (const file of arr) {
        try {
          setPct(0);
          await uploadMut.mutateAsync({ file, onProgress: (f) => setPct(Math.round(f * 100)) });
        } catch (e) {
          alert(detailOf(e) || (e instanceof Error ? e.message : '') || 'Ошибка загрузки');
        }
      }
      setPct(0);
    },
    [uploadMut]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files?.length) uploadFiles(e.dataTransfer.files);
    },
    [uploadFiles]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files?.length) uploadFiles(e.target.files);
      e.target.value = '';
    },
    [uploadFiles]
  );

  const handleDownload = async (id: number) => {
    setBusyId(id);
    try {
      await downloadStashFile(id);
    } catch (e) {
      alert(detailOf(e) || 'Не удалось скачать');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (f: StashFile) => {
    if (!window.confirm(`Удалить «${f.original_name}»?`)) return;
    try {
      await deleteMut.mutateAsync(f.id);
    } catch { /* список обновится сам */ }
  };

  const handleDownloadAll = async () => {
    let items;
    try {
      items = await getStashDownloadUrls();
    } catch {
      alert('Не удалось получить список файлов');
      return;
    }
    if (!items.length) return;

    const picker = (window as unknown as { showDirectoryPicker?: (opts: { mode: 'readwrite' }) => Promise<FileSystemDirectoryHandle> })
      .showDirectoryPicker;
    if (typeof picker === 'function') {
      // Chromium: нативный выбор папки + запись файлов туда
      let dir: FileSystemDirectoryHandle;
      try {
        dir = await picker.call(window, { mode: 'readwrite' });
      } catch {
        return; // пользователь отменил выбор папки
      }
      const used = new Set<string>();
      setDlProgress({ done: 0, total: items.length });
      try {
        for (let i = 0; i < items.length; i++) {
          const resp = await fetch(items[i].url);
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const name = uniqueName(items[i].original_name, used);
          const fh = await dir.getFileHandle(name, { create: true });
          const writable = await fh.createWritable();
          if (resp.body) {
            await resp.body.pipeTo(writable); // стрим на диск, без загрузки целиком в память
          } else {
            await writable.write(await resp.blob());
            await writable.close();
          }
          setDlProgress({ done: i + 1, total: items.length });
        }
      } catch (e) {
        alert('Ошибка при скачивании: ' + (e instanceof Error ? e.message : ''));
      } finally {
        setDlProgress(null);
      }
    } else {
      // Firefox/Safari: по очереди в папку загрузок
      for (const it of items) {
        const a = document.createElement('a');
        a.href = it.url;
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        a.remove();
        await new Promise((r) => setTimeout(r, 400));
      }
    }
  };

  const uploading = uploadMut.isPending;
  const downloadingAll = dlProgress !== null;

  return (
    <div className={styles.container}>
      <div className={styles.topBar}>
        <button onClick={onBack} className={styles.backBtn}>{'←'} Назад</button>
        <h2 className={styles.title}>Файлы</h2>
      </div>
      <p className={styles.subtitle}>
        Личное временное хранилище. Загрузите с одного устройства — скачайте с другого.
        Файлы автоматически удаляются по сроку; можно удалить вручную.
      </p>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !uploading && inputRef.current?.click()}
        className={cx(styles.dropZone, dragOver && styles.dropZoneActive, uploading && styles.dropZoneBusy)}
      >
        <input ref={inputRef} type="file" multiple onChange={handleChange} className={styles.fileInput} />
        <div className={styles.dropIcon}>{uploading ? '⏳' : '📁'}</div>
        <div className={styles.dropText}>
          {uploading ? `Загрузка… ${pct}%` : 'Перетащите файлы или нажмите для выбора'}
        </div>
        <div className={styles.dropHint}>
          Любой тип файла
        </div>
      </div>

      {files.length > 0 && (
        <div className={styles.listHeader}>
          <span className={styles.listCount}>{files.length} файл(ов)</span>
          <button onClick={handleDownloadAll} disabled={downloadingAll} className={styles.downloadAllBtn}>
            {downloadingAll ? `Скачивание ${dlProgress!.done}/${dlProgress!.total}…` : '⬇ Скачать все'}
          </button>
        </div>
      )}

      <div className={styles.list}>
        {files.length === 0 && (
          <div className={styles.empty}>Пока нет файлов</div>
        )}
        {files.map((f) => (
          <div key={f.id} className={styles.row}>
            <div className={styles.rowMain}>
              <div className={styles.name} title={f.original_name}>{f.original_name}</div>
              <div className={styles.meta}>
                {f.size != null ? formatFileSize(f.size) : '—'}
                {f.expires_at && <span className={styles.expiry}> · {expiryLabel(f.expires_at)}</span>}
              </div>
            </div>
            <div className={styles.actions}>
              <button
                onClick={() => handleDownload(f.id)}
                disabled={busyId === f.id}
                className={styles.downloadBtn}
              >
                {busyId === f.id ? '…' : 'Скачать'}
              </button>
              <button onClick={() => handleDelete(f)} className={styles.deleteBtn} aria-label="Удалить" title="Удалить">
                {'✕'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
