import { useState, useEffect, useCallback } from 'react';
import { apiErrorMessage } from '../../lib/apiError';
import {
  getMeetingAISettings, patchMeetingAISettings, applyProfileToMeeting, listProfiles,
} from '../../api/aiSettings';
import type { AISettingsProfile, MeetingAISettings, MeetingAISettingsPatch, SuggestionMode } from '../../types';
import { Select } from '../common';
import styles from './MeetingAISettings.module.css';

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

  if (!data) return <div className={styles.card}><div className={styles.muted}>Загрузка AI-настроек…</div></div>;

  const r = data.resolved;
  const canEdit = data.can_edit;

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.dot} />
        <span className={styles.title}>AI-настройки встречи</span>
        <span className={styles.spacer} />
        <span className={styles.modeBadge}>{r.mode}</span>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {info && <div className={styles.info}>{info}</div>}
      {!canEdit && <div className={styles.muted}>Только просмотр — у вас нет прав на изменение настроек этой встречи.</div>}

      <label className={styles.lbl}>Профиль</label>
      <Select triggerClassName={styles.input} disabled={!canEdit || busy} value={String(data.profile_id ?? '')}
              ariaLabel="Профиль AI-настроек"
              onChange={(v) => { if (v) applyProfile(Number(v)); }}
              placeholder="— не выбран —"
              options={profiles.map((p) => ({ value: String(p.id), label: `${p.name}${p.is_default ? ' (по умолч.)' : ''}` }))} />

      <label className={styles.lbl}>Режим</label>
      <div className={styles.modeRow}>
        {MODES.map((m) => (
          <button key={m.key} disabled={!canEdit || busy}
                  className={r.mode === m.key ? styles.modeOn : styles.modeOff}
                  onClick={() => patch({ mode: m.key })}>{m.label}</button>
        ))}
      </div>

      <label className={styles.lbl}>Контекст и подсказки</label>
      <div className={styles.toggles}>
        {TOGGLES.map((t) => (
          <label key={t.key} className={styles.toggle}>
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
