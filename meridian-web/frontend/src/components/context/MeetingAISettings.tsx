import { useState, useEffect, useCallback } from 'react';
import { theme } from '../../styles/theme';
import { apiErrorMessage } from '../../lib/apiError';
import {
  getMeetingAISettings, patchMeetingAISettings, applyProfileToMeeting, listProfiles,
} from '../../api/aiSettings';
import type { AISettingsProfile, MeetingAISettings, MeetingAISettingsPatch, SuggestionMode } from '../../types';
import { Select } from '../common';

interface Props { meetingId: number; }

const MODES: { key: SuggestionMode; label: string }[] = [
  { key: 'fast', label: 'Быстрый' },
  { key: 'balanced', label: 'Сбаланс.' },
  { key: 'deep', label: 'Глубокий' },
];

const TOGGLES: { key: keyof MeetingAISettingsPatch; label: string }[] = [
  { key: 'auto_suggestions_enabled', label: 'Авто-подсказки' },
  { key: 'document_context_enabled', label: 'Документы' },
  { key: 'knowledge_context_enabled', label: 'База знаний' },
  { key: 'previous_meetings_context_enabled', label: 'Прошлые встречи' },
];

export function MeetingAISettingsBlock({ meetingId }: Props) {
  const [data, setData] = useState<MeetingAISettings | null>(null);
  const [profiles, setProfiles] = useState<AISettingsProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setData(await getMeetingAISettings(meetingId)); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось загрузить AI-настройки встречи')); }
  }, [meetingId]);

  useEffect(() => { load(); listProfiles().then(setProfiles).catch(() => {}); }, [load]);

  const flash = (msg: string) => { setInfo(msg); setTimeout(() => setInfo(null), 2000); };

  async function patch(p: MeetingAISettingsPatch) {
    setBusy(true); setError(null);
    try { setData(await patchMeetingAISettings(meetingId, p)); flash('Настройки применены'); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось применить')); }
    finally { setBusy(false); }
  }

  async function applyProfile(profileId: number) {
    setBusy(true); setError(null);
    try { setData(await applyProfileToMeeting(meetingId, profileId)); flash('Профиль применён'); await load(); }
    catch (e) { setError(apiErrorMessage(e, 'Не удалось применить профиль')); }
    finally { setBusy(false); }
  }

  if (!data) return <div style={styles.card}><div style={styles.muted}>Загрузка AI-настроек…</div></div>;

  const r = data.resolved;
  const canEdit = data.can_edit;

  return (
    <div style={styles.card}>
      <div style={styles.header}>
        <span style={styles.dot} />
        <span style={styles.title}>AI-настройки встречи</span>
        <span style={{ flex: 1 }} />
        <span style={styles.modeBadge}>{r.mode}</span>
      </div>

      {error && <div style={styles.error}>{error}</div>}
      {info && <div style={styles.info}>{info}</div>}
      {!canEdit && <div style={styles.muted}>Только просмотр — у вас нет прав на изменение настроек этой встречи.</div>}

      <label style={styles.lbl}>Профиль</label>
      <Select style={styles.input} disabled={!canEdit || busy} value={String(data.profile_id ?? '')}
              ariaLabel="Профиль AI-настроек"
              onChange={(v) => { if (v) applyProfile(Number(v)); }}
              placeholder="— не выбран —"
              options={profiles.map((p) => ({ value: String(p.id), label: `${p.name}${p.is_default ? ' (по умолч.)' : ''}` }))} />

      <label style={styles.lbl}>Режим</label>
      <div style={styles.modeRow}>
        {MODES.map((m) => (
          <button key={m.key} disabled={!canEdit || busy}
                  style={r.mode === m.key ? styles.modeOn : styles.modeOff}
                  onClick={() => patch({ mode: m.key })}>{m.label}</button>
        ))}
      </div>

      <label style={styles.lbl}>Контекст и подсказки</label>
      <div style={styles.toggles}>
        {TOGGLES.map((t) => (
          <label key={t.key} style={styles.toggle}>
            <input type="checkbox" disabled={!canEdit || busy}
                   checked={!!r[t.key as keyof typeof r]}
                   onChange={(e) => patch({ [t.key]: e.target.checked } as MeetingAISettingsPatch)} />
            {t.label}
          </label>
        ))}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  card: { background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 20, display: 'flex', flexDirection: 'column', gap: 8 },
  header: { display: 'flex', alignItems: 'center', gap: 8 },
  dot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.amber, flexShrink: 0 },
  title: { fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase' as const, color: theme.text.primary },
  modeBadge: { padding: '3px 10px', border: `1px solid ${theme.accent.amber}`, borderRadius: 12, fontFamily: theme.font.mono, fontSize: 10, color: theme.accent.amber },
  lbl: { fontSize: 10, fontFamily: theme.font.mono, color: theme.accent.amber, letterSpacing: '0.08em', textTransform: 'uppercase' as const, marginTop: 6 },
  input: { padding: '9px 12px', background: theme.bg.input, border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none' },
  modeRow: { display: 'flex', gap: 8 },
  modeOn: { padding: '7px 14px', background: theme.accent.amberGlow, border: `1px solid ${theme.accent.amber}`, borderRadius: 7, color: theme.accent.amber, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono },
  modeOff: { padding: '7px 14px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 7, color: theme.text.secondary, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.mono },
  toggles: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 },
  toggle: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: theme.text.secondary, fontFamily: theme.font.body },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 12 },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 11 },
  info: { color: theme.accent.green, fontFamily: theme.font.mono, fontSize: 11 },
};
