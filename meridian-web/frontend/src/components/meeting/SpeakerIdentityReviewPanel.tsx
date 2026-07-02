import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { theme } from '../../styles/theme';
import { apiErrorMessage } from '../../lib/apiError';
import { Select } from '../common';
import { getMeetingAISettings, patchMeetingSpeakerIdentityHints } from '../../api/aiSettings';
import {
  buildChannelHintDrafts,
  buildSpeakerIdentityHintsPatch,
  buildSpeakerLabelHintDrafts,
  existingHintsToDrafts,
  extractStrictSpeakerLabelsFromTranscript,
  mergeHintsIntoDrafts,
} from '../../features/speakerIdentity/speakerIdentityHints';
import {
  ROLE_OPTIONS, SIDE_OPTIONS, roleLabel, sideLabel,
} from '../../features/speakerIdentity/speakerIdentityTypes';
import type {
  FunctionalRole, RawSpeakerIdentityHints, SpeakerIdentityHintDraft, SpeakerSide,
} from '../../features/speakerIdentity/speakerIdentityTypes';

/**
 * Этап 21 — «Роли и стороны». Оператор ЯВНО подтверждает сторону (наша / контрагент / третья) и
 * функциональную роль голосов транскрипта и каналов записи. Это НЕ AI-профиль и НЕ выбор режима
 * ассистента: сторона появляется только после подтверждения и сохраняется в скрытый
 * speaker_identity_hints. Сторона не угадывается по тексту; канал = техническая зона записи.
 */
interface Props {
  meetingId: number | null;
  canEdit?: boolean;
  transcriptItems: Array<{ speaker?: string | null }>;
  actualChannelCount?: number;
  multichannelShadowEnabled?: boolean;
}

function _draftKey(kind: string, key: string): string {
  return `${kind}::${key}`;
}

export function SpeakerIdentityReviewPanel({
  meetingId, canEdit = false, transcriptItems, actualChannelCount = 0, multichannelShadowEnabled = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const [drafts, setDrafts] = useState<SpeakerIdentityHintDraft[]>([]);
  const [savedHints, setSavedHints] = useState<RawSpeakerIdentityHints>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const channelCount = Math.max(0, Math.min(8, Math.floor(actualChannelCount || 0)));

  const strictLabels = useMemo(
    () => extractStrictSpeakerLabelsFromTranscript(transcriptItems), [transcriptItems]);
  const strictKey = strictLabels.join('|');

  // Актуальные метки/каналы через ref: rebuild/load не зависят от идентичности массива (иначе
  // пересоздаются на каждое сообщение, и ленивый useEffect ловит stale-closure на rebuild).
  const strictLabelsRef = useRef(strictLabels);
  strictLabelsRef.current = strictLabels;
  const channelCountRef = useRef(channelCount);
  channelCountRef.current = channelCount;

  // Полная пересборка списка из транскрипта + каналов + серверных hints (стабильная ссылка).
  const rebuild = useCallback((hints: RawSpeakerIdentityHints) => {
    const base = [
      ...buildSpeakerLabelHintDrafts(strictLabelsRef.current),
      ...buildChannelHintDrafts(channelCountRef.current),
    ];
    setDrafts(mergeHintsIntoDrafts(base, hints));
  }, []);

  const load = useCallback(async () => {
    if (meetingId == null) return;
    setBusy(true); setError(null);
    try {
      const data = await getMeetingAISettings(meetingId);
      const hints = (data.resolved?.speaker_identity_hints ?? null) as RawSpeakerIdentityHints;
      setSavedHints(hints);
      rebuild(hints);
    } catch (e) {
      // Панель не блокирует встречу — ошибка не критична.
      setError(apiErrorMessage(e, 'Не удалось загрузить назначения ролей'));
    } finally {
      setBusy(false);
    }
  }, [meetingId, rebuild]);

  // Загрузка при открытии панели (ленивая — не грузим на каждой встрече без надобности).
  useEffect(() => {
    // savedHints/drafts.length — guard от повторной загрузки, а не триггер (намеренно не в deps).
    if (open && meetingId != null && savedHints === null && drafts.length === 0) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, meetingId, load]);

  // Новые строгие метки/каналы добавляем, не затирая уже отредактированные строки.
  useEffect(() => {
    setDrafts((prev) => {
      const have = new Set(prev.map((d) => _draftKey(d.kind, d.key)));
      const additions: SpeakerIdentityHintDraft[] = [];
      for (const d of buildSpeakerLabelHintDrafts(strictLabels)) {
        if (!have.has(_draftKey(d.kind, d.key))) additions.push(d);
      }
      for (const d of buildChannelHintDrafts(channelCount)) {
        if (!have.has(_draftKey(d.kind, d.key))) additions.push(d);
      }
      return additions.length ? [...prev, ...additions] : prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strictKey, channelCount]);

  function setField(kind: string, key: string, patch: Partial<SpeakerIdentityHintDraft>) {
    setInfo(null);
    setDrafts((prev) => prev.map((d) => (d.kind === kind && d.key === key ? { ...d, ...patch } : d)));
  }

  async function onSave() {
    if (meetingId == null) { setError('Встреча ещё не загружена'); return; }
    if (!canEdit) { setError('Нет прав на изменение встречи'); return; }
    setBusy(true); setError(null); setInfo(null);
    try {
      const patch = buildSpeakerIdentityHintsPatch(drafts, savedHints);
      const data = await patchMeetingSpeakerIdentityHints(meetingId, patch as Record<string, unknown> | null);
      const hints = (data.resolved?.speaker_identity_hints ?? null) as RawSpeakerIdentityHints;
      setSavedHints(hints);
      rebuild(hints);
      setInfo('Роли сохранены');
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось сохранить роли'));
    } finally {
      setBusy(false);
    }
  }

  async function onReset() {
    if (meetingId == null) { setError('Встреча ещё не загружена'); return; }
    if (!canEdit) { setError('Нет прав на изменение встречи'); return; }
    setBusy(true); setError(null); setInfo(null);
    try {
      await patchMeetingSpeakerIdentityHints(meetingId, null);
      setSavedHints(null);
      rebuild(null);
      setInfo('Назначения сброшены');
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось сбросить назначения'));
    } finally {
      setBusy(false);
    }
  }

  const voiceDrafts = drafts.filter((d) => d.kind === 'speaker_label');
  const channelDrafts = drafts.filter((d) => d.kind === 'audio_source' || d.kind === 'channel_label');
  const showChannels = channelCount >= 2 || multichannelShadowEnabled || channelDrafts.length > 0;
  const savedRows = existingHintsToDrafts(savedHints).filter((d) => d.side !== 'unknown');
  const assignedCount = drafts.filter((d) => d.enabled && d.side !== 'unknown').length;

  const renderRow = (d: SpeakerIdentityHintDraft) => (
    <div style={styles.row} key={_draftKey(d.kind, d.key)}>
      <div style={styles.rowLabel} title={d.displayLabel}>
        <span style={styles.rowKind}>{d.kind === 'speaker_label' ? 'голос' : 'канал'}</span>
        <span style={styles.rowName}>{d.displayLabel}</span>
      </div>
      <Select
        value={d.side}
        onChange={(v) => setField(d.kind, d.key, { side: v as SpeakerSide })}
        options={SIDE_OPTIONS}
        disabled={!canEdit}
        ariaLabel={`Сторона: ${d.displayLabel}`}
        style={styles.select}
        wrapperStyle={styles.selectWrap}
      />
      <Select
        value={d.functionalRole}
        onChange={(v) => setField(d.kind, d.key, { functionalRole: v as FunctionalRole })}
        options={ROLE_OPTIONS}
        disabled={!canEdit || d.side === 'unknown'}
        ariaLabel={`Роль: ${d.displayLabel}`}
        style={styles.select}
        wrapperStyle={styles.selectWrap}
      />
      <span style={{ ...styles.status, color: d.side === 'unknown' ? theme.text.muted : theme.accent.green }}>
        {d.side === 'unknown' ? 'не задано' : sideLabel(d.side)}
      </span>
    </div>
  );

  return (
    <div style={styles.wrap}>
      <button style={styles.header} onClick={() => setOpen((o) => !o)} type="button">
        <span style={styles.headerTitle}>🧭 Роли и стороны</span>
        <span style={styles.headerMeta}>
          {assignedCount > 0 ? `${assignedCount} назнач.` : 'не заданы'} {open ? '▾' : '▸'}
        </span>
      </button>

      {open && (
        <div style={styles.body}>
          <div style={styles.subtitle}>
            Подтвердите, кто относится к нашей стороне, к контрагенту или к третьей стороне. Сторона
            появляется только после вашего подтверждения. Это не AI-профиль и не выбор режима ассистента.
          </div>
          {!canEdit && <div style={styles.readonly}>Только просмотр — нет прав на изменение встречи.</div>}
          {error && <div style={styles.errorBox}>{error}</div>}
          {info && <div style={styles.infoBox}>{info}</div>}

          <div style={styles.sectionTitle}>Голоса в транскрипте</div>
          {voiceDrafts.length === 0 ? (
            <div style={styles.empty}>Пока нет распознанных меток спикеров (SM_0 / Speaker 1 …).</div>
          ) : (
            voiceDrafts.map(renderRow)
          )}

          {showChannels && (
            <>
              <div style={styles.sectionTitle}>Каналы записи (техническая зона, не сторона)</div>
              {channelDrafts.length === 0 ? (
                <div style={styles.empty}>Мультиканальная запись не активна.</div>
              ) : (
                channelDrafts.map(renderRow)
              )}
            </>
          )}

          {savedRows.length > 0 && (
            <>
              <div style={styles.sectionTitle}>Сохранённые назначения</div>
              {savedRows.map((d) => (
                <div style={styles.savedRow} key={`saved-${_draftKey(d.kind, d.key)}`}>
                  <span style={styles.rowName}>{d.displayLabel}</span>
                  <span style={styles.savedMeta}>
                    {sideLabel(d.side)}
                    {d.functionalRole !== 'unknown' ? ` · ${roleLabel(d.functionalRole)}` : ''}
                  </span>
                </div>
              ))}
            </>
          )}

          <div style={styles.actions}>
            <button style={styles.saveBtn} onClick={() => void onSave()} type="button" disabled={!canEdit || busy}>
              {busy ? 'Сохранение…' : 'Сохранить роли'}
            </button>
            <button style={styles.ghostBtn} onClick={() => void onReset()} type="button" disabled={!canEdit || busy}>
              Сбросить назначения
            </button>
            <button style={styles.ghostBtn} onClick={() => void load()} type="button" disabled={busy || meetingId == null}>
              Обновить список
            </button>
          </div>
          <div style={styles.note}>
            Сохраняются только сторона и функциональная роль по технической метке. Имена, названия
            организаций и идентификаторы устройств не сохраняются.
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    background: theme.bg.secondary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
    margin: '8px 12px',
    overflow: 'hidden',
    flexShrink: 0,
  },
  header: {
    width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '10px 14px', background: 'transparent', border: 'none', cursor: 'pointer',
    color: theme.text.primary, fontFamily: theme.font.body, fontSize: 13,
  },
  headerTitle: { fontWeight: 600 },
  headerMeta: { color: theme.text.secondary, fontSize: 11, fontFamily: theme.font.mono },
  body: { padding: '4px 14px 14px', display: 'flex', flexDirection: 'column', gap: 6 },
  subtitle: { color: theme.text.secondary, fontSize: 11.5, lineHeight: 1.5, marginTop: 2 },
  readonly: { color: theme.text.muted, fontSize: 11, fontStyle: 'italic' },
  sectionTitle: {
    color: theme.text.secondary, fontSize: 11, fontWeight: 600, marginTop: 10,
    fontFamily: theme.font.mono, textTransform: 'uppercase', letterSpacing: 0.5,
  },
  empty: { color: theme.text.muted, fontSize: 11, fontFamily: theme.font.body },
  row: {
    display: 'grid', gridTemplateColumns: 'minmax(90px, 1.1fr) 1.2fr 1.2fr auto',
    gap: 6, alignItems: 'center',
  },
  rowLabel: { display: 'flex', flexDirection: 'column', minWidth: 0 },
  rowKind: { color: theme.text.muted, fontSize: 9.5, fontFamily: theme.font.mono, textTransform: 'uppercase' },
  rowName: {
    color: theme.text.primary, fontSize: 12, fontFamily: theme.font.mono,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  selectWrap: { minWidth: 0 },
  select: {
    background: theme.bg.input, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6, padding: '6px 8px',
    fontSize: 12, fontFamily: theme.font.body,
  },
  status: { fontSize: 10.5, fontFamily: theme.font.mono, textAlign: 'right', whiteSpace: 'nowrap' },
  savedRow: {
    display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline',
    padding: '3px 0', borderBottom: `1px solid ${theme.border.default}`,
  },
  savedMeta: { color: theme.text.secondary, fontSize: 11, fontFamily: theme.font.body, textAlign: 'right' },
  actions: { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 },
  saveBtn: {
    padding: '7px 14px', background: theme.accent.amber, color: '#080A0F', border: 'none',
    borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: theme.font.body,
  },
  ghostBtn: {
    padding: '7px 12px', background: theme.bg.elevated, color: theme.text.primary,
    border: `1px solid ${theme.border.default}`, borderRadius: 6, fontSize: 12, cursor: 'pointer',
    fontFamily: theme.font.body,
  },
  note: { marginTop: 8, color: theme.text.muted, fontSize: 10.5, fontFamily: theme.font.body, lineHeight: 1.5 },
  errorBox: {
    background: 'rgba(255,75,110,0.1)', color: theme.accent.red, borderRadius: 6,
    padding: '7px 10px', fontSize: 11.5,
  },
  infoBox: {
    background: 'rgba(46,229,157,0.1)', color: theme.accent.green, borderRadius: 6,
    padding: '7px 10px', fontSize: 11.5,
  },
};
