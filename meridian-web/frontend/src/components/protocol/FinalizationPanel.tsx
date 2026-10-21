import { useState, useEffect, useCallback, useRef } from 'react';
import { theme } from '../../styles/theme';
import {
  getFinalizationStatus, finalizeMeeting, retryFinalization,
  getMeetingProtocol, updateMeetingProtocol,
} from '../../api/finalization';
import { apiErrorMessage } from '../../lib/apiError';
import { ProtocolView } from './ProtocolView';
import { LearningCandidates } from '../learning/LearningCandidates';
import { SuccessCheck } from '../common/SuccessCheck';
import { TextInput } from '../common';
import { useMeetingStore } from '../../store/meetingStore';
import type { FinalizationStatus, MeetingProtocol } from '../../types';
import styles from './FinalizationPanel.module.css';
import { cx } from '../../utils/cx';

interface Props {
  meetingId: number | null;
  // Вызывается один раз при первой загрузке готового протокола — чтобы подтянуть
  // сгенерированную тему/название в стор (read-only поле «Тема/цель встречи»).
  onFinalized?: () => void;
}

const STATUS_TEXT: Record<FinalizationStatus, string> = {
  not_started: 'Протокол не сформирован',
  queued: 'Встреча сохраняется…',
  running: 'Формируется протокол…',
  completed: 'Протокол готов',
  partial: 'Протокол сформирован частично',
  error: 'Ошибка формирования протокола',
};

function statusTone(s: FinalizationStatus): string {
  if (s === 'completed') return styles.toneGreen;
  if (s === 'error') return styles.toneRed;
  if (s === 'partial') return styles.toneAmber;
  if (s === 'queued' || s === 'running') return styles.toneBlue;
  return styles.toneMuted;
}

export function FinalizationPanel({ meetingId, onFinalized }: Props) {
  const [status, setStatus] = useState<FinalizationStatus>('not_started');
  const [error, setError] = useState<string | null>(null);
  const [protocol, setProtocol] = useState<MeetingProtocol | null>(null);
  const [busy, setBusy] = useState(false);
  // editable fields
  const [title, setTitle] = useState('');
  const [micro, setMicro] = useState('');
  const [tags, setTags] = useState('');
  const [markdown, setMarkdown] = useState('');
  const [saved, setSaved] = useState(false);
  const loadedFor = useRef<number | null>(null);

  const onFinalizedRef = useRef(onFinalized);
  onFinalizedRef.current = onFinalized;

  const loadProtocol = useCallback(async (id: number) => {
    try {
      const p = await getMeetingProtocol(id);
      setProtocol(p);
      if (loadedFor.current !== id) {
        setTitle(p.title || '');
        setMicro(p.micro_summary || '');
        setTags((p.tags || []).join(', '));
        setMarkdown(p.protocol_markdown || '');
        loadedFor.current = id;
        onFinalizedRef.current?.();
      }
    } catch { /* ignore */ }
  }, []);

  const refresh = useCallback(async () => {
    if (meetingId == null) return;
    try {
      const s = await getFinalizationStatus(meetingId);
      setStatus(s.status);
      setError(s.error);
      if ((s.status === 'completed' || s.status === 'partial') && s.has_protocol) {
        await loadProtocol(meetingId);
      }
    } catch { /* ignore */ }
  }, [meetingId, loadProtocol]);

  useEffect(() => { refresh(); }, [refresh]);

  // после WS-сохранения встречи (meeting_saved → meetingSavedId) — перечитать статус
  const meetingSavedId = useMeetingStore((s) => s.meetingSavedId);
  useEffect(() => {
    if (meetingSavedId != null && meetingSavedId === meetingId) refresh();
  }, [meetingSavedId, meetingId, refresh]);

  // polling пока идёт формирование
  useEffect(() => {
    if (meetingId == null) return;
    if (status !== 'queued' && status !== 'running') return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [status, meetingId, refresh]);

  async function doFinalize() {
    if (meetingId == null) return;
    setBusy(true); setError(null);
    try {
      const s = await finalizeMeeting(meetingId);
      setStatus(s.status);
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось запустить финализацию')); }
    finally { setBusy(false); }
  }

  async function doRetry() {
    if (meetingId == null) return;
    setBusy(true); setError(null);
    try {
      const s = await retryFinalization(meetingId);
      setStatus(s.status);
      setProtocol(null);
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось перезапустить')); }
    finally { setBusy(false); }
  }

  async function saveEdits() {
    if (meetingId == null) return;
    setBusy(true); setSaved(false);
    try {
      const p = await updateMeetingProtocol(meetingId, {
        title, micro_summary: micro,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        protocol_markdown: markdown,
      });
      setProtocol(p);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) { setError(apiErrorMessage(e, 'Не удалось сохранить')); }
    finally { setBusy(false); }
  }

  if (meetingId == null) return null;

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>Итоги встречи</span>
        <span className={styles.spacer} />
        <span className={cx(styles.statusBadge, statusTone(status))}>
          {STATUS_TEXT[status]}
        </span>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      {status === 'not_started' && (
        <button className={styles.primaryBtn} onClick={doFinalize} disabled={busy}>
          Завершить и сформировать протокол
        </button>
      )}

      {(status === 'queued' || status === 'running') && (
        <div className={styles.muted}>Формируется протокол — подождите…</div>
      )}

      {status === 'error' && (
        <button className={styles.retryBtn} onClick={doRetry} disabled={busy}>Повторить формирование</button>
      )}

      {(status === 'completed' || status === 'partial') && (
        <>
          {/* Редактирование */}
          <label className={styles.lbl}>Название</label>
          <TextInput inputClassName={styles.input} value={title} onChange={(e) => setTitle(e.target.value)} onClear={() => setTitle('')} clearLabel="название" />
          <label className={styles.lbl}>Краткое описание</label>
          <textarea className={styles.textarea} rows={2} value={micro} onChange={(e) => setMicro(e.target.value)} />
          <label className={styles.lbl}>Теги (через запятую)</label>
          <TextInput inputClassName={styles.input} value={tags} onChange={(e) => setTags(e.target.value)} onClear={() => setTags('')} clearLabel="теги" />
          <label className={styles.lbl}>Протокол (markdown)</label>
          <textarea className={styles.textarea} rows={8} value={markdown} onChange={(e) => setMarkdown(e.target.value)} />
          <div className={styles.actions}>
            <button className={styles.primaryBtn} onClick={saveEdits} disabled={busy}>
              <span className={styles.saveLabel}>
                <SuccessCheck show={saved} size={14} color={theme.onAccent} />
                {saved ? 'Сохранено' : 'Сохранить правки'}
              </span>
            </button>
            <button className={styles.retryBtn} onClick={doRetry} disabled={busy}>Сформировать заново</button>
          </div>

          {protocol && <ProtocolView p={protocol} />}

          {/* Этап 7: кандидаты в базу знаний по итогам встречи */}
          <div className={styles.learnHeader}>
            <span className={styles.dot} />
            <span className={styles.title}>AI нашёл новые элементы для базы знаний</span>
          </div>
          <div className={styles.muted}>Проверьте и одобрите нужное — применяется только вручную.</div>
          <LearningCandidates meetingId={meetingId} compact />
        </>
      )}
    </div>
  );
}
