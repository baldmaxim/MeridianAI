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
import { useMeetingStore } from '../../store/meetingStore';
import type { FinalizationStatus, MeetingProtocol } from '../../types';

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

function statusColor(s: FinalizationStatus): string {
  if (s === 'completed') return theme.accent.green;
  if (s === 'error') return theme.accent.red;
  if (s === 'partial') return theme.accent.amber;
  if (s === 'queued' || s === 'running') return theme.accent.blue;
  return theme.text.muted;
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
    <div style={styles.card}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>Итоги встречи</span>
        <span style={{ flex: 1 }} />
        <span style={{ ...styles.statusBadge, color: statusColor(status), borderColor: statusColor(status) }}>
          {STATUS_TEXT[status]}
        </span>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {status === 'not_started' && (
        <button style={styles.primaryBtn} onClick={doFinalize} disabled={busy}>
          Завершить и сформировать протокол
        </button>
      )}

      {(status === 'queued' || status === 'running') && (
        <div style={styles.muted}>Формируется протокол — подождите…</div>
      )}

      {status === 'error' && (
        <button style={styles.retryBtn} onClick={doRetry} disabled={busy}>Повторить формирование</button>
      )}

      {(status === 'completed' || status === 'partial') && (
        <>
          {/* Редактирование */}
          <label style={styles.lbl}>Название</label>
          <input style={styles.input} value={title} onChange={(e) => setTitle(e.target.value)} />
          <label style={styles.lbl}>Краткое описание</label>
          <textarea style={styles.textarea} rows={2} value={micro} onChange={(e) => setMicro(e.target.value)} />
          <label style={styles.lbl}>Теги (через запятую)</label>
          <input style={styles.input} value={tags} onChange={(e) => setTags(e.target.value)} />
          <label style={styles.lbl}>Протокол (markdown)</label>
          <textarea style={styles.textarea} rows={8} value={markdown} onChange={(e) => setMarkdown(e.target.value)} />
          <div style={styles.actions}>
            <button style={styles.primaryBtn} onClick={saveEdits} disabled={busy}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <SuccessCheck show={saved} size={14} color="#080A0F" />
                {saved ? 'Сохранено' : 'Сохранить правки'}
              </span>
            </button>
            <button style={styles.retryBtn} onClick={doRetry} disabled={busy}>Сформировать заново</button>
          </div>

          {protocol && <ProtocolView p={protocol} />}

          {/* Этап 7: кандидаты в базу знаний по итогам встречи */}
          <div style={styles.learnHeader}>
            <span style={styles.dot} />
            <span style={styles.title}>AI нашёл новые элементы для базы знаний</span>
          </div>
          <div style={styles.muted}>Проверьте и одобрите нужное — применяется только вручную.</div>
          <LearningCandidates meetingId={meetingId} compact />
        </>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: { background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 20, display: 'flex', flexDirection: 'column', gap: 10 },
  header: { display: 'flex', alignItems: 'center', gap: 8 },
  learnHeader: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 14, paddingTop: 14, borderTop: `1px solid ${theme.border.default}` },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  title: { fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: theme.text.primary },
  statusBadge: { padding: '3px 10px', border: '1px solid', borderRadius: 12, fontFamily: theme.font.mono, fontSize: 10 },
  lbl: { fontSize: 10, fontFamily: theme.font.mono, color: theme.accent.amber, letterSpacing: '0.08em', textTransform: 'uppercase' as const, marginTop: 6 },
  input: { padding: '9px 12px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none' },
  textarea: { padding: '9px 12px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none', resize: 'vertical' as const },
  actions: { display: 'flex', gap: 10, flexWrap: 'wrap' as const, marginTop: 4 },
  primaryBtn: { padding: '10px 18px', background: theme.accent.amber, border: 'none', borderRadius: 8, color: '#080A0F', cursor: 'pointer', fontSize: 12, fontWeight: 600, fontFamily: theme.font.body },
  retryBtn: { padding: '10px 16px', background: 'transparent', border: `1px solid ${theme.border.amber}`, borderRadius: 8, color: theme.accent.amber, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 12 },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
};
