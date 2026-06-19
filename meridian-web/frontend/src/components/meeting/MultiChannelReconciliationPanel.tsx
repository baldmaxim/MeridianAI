import { useMemo, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import type {
  WSMessageToServer, MultiChannelReconciliationEntry, SpeakerSegmentCorrection,
} from '../../types';
import { putSpeakerCorrection, bulkPutSpeakerCorrections, listSpeakerCorrections } from '../../api/speakerCorrections';
import {
  buildCorrectionFromReconciliation, buildBulkReconciliationCorrections,
} from '../../lib/applyReconciliationCorrection';

interface Props {
  meetingId: number | null;
  canEdit?: boolean;
  sendJSON: (message: WSMessageToServer) => void;
}

type Filter = 'all' | 'applicable' | 'conflict' | 'ambiguous' | 'channel_only' | 'primary_only';

const SIDE_RU = (s: string | null) => s === 'self' ? 'Мы' : s === 'opponent' ? 'Не мы' : '—';

function corrMap(list: SpeakerSegmentCorrection[]): Record<string, SpeakerSegmentCorrection> {
  const m: Record<string, SpeakerSegmentCorrection> = {};
  for (const c of list) m[c.segment_key] = c;
  return m;
}

export function MultiChannelReconciliationPanel({ meetingId, canEdit = true, sendJSON }: Props) {
  const recon = useMeetingStore((s) => s.multiChannelReconciliation);
  const dismissed = useMeetingStore((s) => s.dismissedReconciliationEntries);
  const selected = useMeetingStore((s) => s.selectedReconciliationEntries);
  const speakerCorrections = useMeetingStore((s) => s.speakerCorrections);
  const dismissEntry = useMeetingStore((s) => s.dismissReconciliationEntry);
  const selectEntry = useMeetingStore((s) => s.selectReconciliationEntry);
  const clearSel = useMeetingStore((s) => s.clearReconciliationSelection);
  const setSpeakerCorrections = useMeetingStore((s) => s.setSpeakerCorrections);

  const [filter, setFilter] = useState<Filter>('all');
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [includeConflicts, setIncludeConflicts] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const entries = useMemo(() => (recon?.entries ?? []).filter((e) => !dismissed[e.entry_id]), [recon, dismissed]);
  const visible = useMemo(() => entries.filter((e) => {
    switch (filter) {
      case 'applicable': return e.can_apply_side;
      case 'conflict': return e.side_agreement === 'conflict';
      case 'ambiguous': return e.kind === 'ambiguous';
      case 'channel_only': return e.kind === 'channel_only';
      case 'primary_only': return e.kind === 'primary_only';
      default: return true;
    }
  }), [entries, filter]);

  const base = useMemo(() => {
    let m = Infinity;
    for (const e of entries) {
      const t = e.primary_start_server_ms ?? e.channel_start_server_ms;
      if (t != null) m = Math.min(m, t);
    }
    return Number.isFinite(m) ? m : 0;
  }, [entries]);
  const fmt = (ms: number | null) => ms == null ? '—'
    : `${Math.floor((ms - base) / 60000).toString().padStart(2, '0')}:${(((ms - base) % 60000) / 1000).toFixed(1).padStart(4, '0')}`;

  if (!recon) {
    return <div style={styles.note}>Сопоставление появится, когда live multi-channel candidate
      получит финальные реплики и в основном transcript будут committed-реплики.</div>;
  }
  const sum = recon.summary;
  const selectedIds = Object.keys(selected);
  // сколько реально применится (исключая конфликты без галки и неприменимое)
  const applicableCount = buildBulkReconciliationCorrections({
    entries, selected, dismissed, existingByKey: speakerCorrections, includeConflicts,
  }).length;

  async function applyEntry(e: MultiChannelReconciliationEntry, replaceConflict = false) {
    if (meetingId == null || !canEdit || !e.primary_segment_key || !e.can_apply_side) return;
    if (e.requires_conflict_confirmation && !replaceConflict) { setConfirmId(e.entry_id); return; }
    setBusy(true); setError(null);
    try {
      // свежие коррекции с сервера → сохранить актуальные label/note (только side меняем)
      const fresh = corrMap(await listSpeakerCorrections(meetingId));
      setSpeakerCorrections(fresh);
      const item = buildCorrectionFromReconciliation({ entry: e, existing: fresh[e.primary_segment_key] });
      const list = await putSpeakerCorrection(meetingId, e.primary_segment_key, {
        side: item.side, corrected_speaker_label: item.corrected_speaker_label,
        note: item.note, original_speaker_label: item.original_speaker_label,
      });
      setSpeakerCorrections(corrMap(list));
      setConfirmId(null);
      sendJSON({ type: 'multi_channel_reconciliation_refresh' });
    } catch {
      setError('Не удалось применить сторону. Попробуйте ещё раз.');
    } finally { setBusy(false); }
  }

  async function applyBulk() {
    if (meetingId == null || !canEdit || !selectedIds.length) return;
    setBusy(true); setError(null);
    try {
      // свежие коррекции с сервера перед сборкой items (сохранить label/note)
      const fresh = corrMap(await listSpeakerCorrections(meetingId));
      setSpeakerCorrections(fresh);
      const items = buildBulkReconciliationCorrections({
        entries, selected, dismissed, existingByKey: fresh, includeConflicts,
      });
      if (!items.length) { setError('Нет применимых выбранных реплик.'); setBusy(false); return; }
      const list = await bulkPutSpeakerCorrections(meetingId, items);
      setSpeakerCorrections(corrMap(list));
      clearSel();
      sendJSON({ type: 'multi_channel_reconciliation_refresh' });
    } catch {
      setError('Массовое применение не удалось. Выбор сохранён.');
    } finally { setBusy(false); }
  }

  return (
    <div style={styles.panel}>
      <div style={styles.note}>
        Multi-channel candidate сравнивается с committed-репликами основного transcript по времени и тексту.
      </div>
      <div style={styles.important}>
        Применение меняет только сторону выбранной реплики через ручную correction. Текст исходного
        transcript не изменяется.
      </div>

      <div style={styles.chips}>
        <Chip label="Совпало" value={sum.matched} />
        <Chip label="Предложений" value={sum.suggested} color={theme.accent.green} />
        <Chip label="Подтверждено" value={sum.confirmed} />
        <Chip label="Конфликтов" value={sum.conflicts} color={theme.accent.red} />
        <Chip label="Неоднозначно" value={sum.ambiguous} color={theme.accent.amber} />
        <Chip label="Только канал" value={sum.channel_only} />
        <Chip label="Только основной" value={sum.primary_only} />
      </div>

      <div style={styles.filters}>
        {(['all', 'applicable', 'conflict', 'ambiguous', 'channel_only', 'primary_only'] as Filter[]).map((f) => (
          <button key={f} type="button" style={filter === f ? styles.fOn : styles.fOff} onClick={() => setFilter(f)}>
            {f === 'all' ? 'Все' : f === 'applicable' ? 'Можно применить' : f === 'conflict' ? 'Конфликты'
              : f === 'ambiguous' ? 'Неоднозначные' : f === 'channel_only' ? 'Только канал' : 'Только основной'}
          </button>
        ))}
      </div>

      {recon.truncated && <div style={styles.warn}>Показаны не все записи (превышен лимит).</div>}

      <div style={styles.list}>
        {visible.length === 0 && <div style={styles.dim}>Нет записей для этого фильтра.</div>}
        {visible.map((e) => (
          <EntryCard key={e.entry_id} e={e} fmt={fmt} canEdit={canEdit} busy={busy}
            confirming={confirmId === e.entry_id} selected={!!selected[e.entry_id]}
            onSelect={(v) => selectEntry(e.entry_id, v)}
            onApply={() => applyEntry(e)} onConfirmApply={() => applyEntry(e, true)}
            onCancelConfirm={() => setConfirmId(null)}
            onDismiss={() => dismissEntry(e.entry_id)} />
        ))}
      </div>

      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.actions}>
        <button type="button" style={styles.ghost} disabled={busy}
          onClick={() => sendJSON({ type: 'multi_channel_reconciliation_refresh' })}>Обновить</button>
        <span style={styles.spacer} />
        {selectedIds.length > 0 && (
          <label style={styles.cbRow}>
            <input type="checkbox" checked={includeConflicts}
              onChange={(ev) => setIncludeConflicts(ev.target.checked)} />
            Заменять конфликтующие
          </label>
        )}
        <button type="button" style={styles.primary} disabled={busy || !canEdit || !applicableCount}
          onClick={applyBulk}>
          Применить выбранные ({applicableCount}{applicableCount !== selectedIds.length ? ` из ${selectedIds.length}` : ''})
        </button>
      </div>
    </div>
  );
}

function Chip({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <span style={styles.chip}>
      <span style={styles.chipLabel}>{label}</span>
      <span style={{ ...styles.chipVal, color: color ?? theme.text.primary }}>{value}</span>
    </span>
  );
}

function EntryCard(props: {
  e: MultiChannelReconciliationEntry; fmt: (ms: number | null) => string; canEdit: boolean;
  busy: boolean; confirming: boolean; selected: boolean;
  onSelect: (v: boolean) => void; onApply: () => void; onConfirmApply: () => void;
  onCancelConfirm: () => void; onDismiss: () => void;
}) {
  const { e, fmt, canEdit, busy, confirming, selected } = props;
  const statusText = e.kind === 'ambiguous' ? 'Неоднозначное соответствие'
    : e.kind === 'channel_only' ? 'Только в multi-channel'
    : e.kind === 'primary_only' ? 'Только в основном transcript'
    : e.side_agreement === 'suggested' ? `Предлагается: ${SIDE_RU(e.channel_side)}`
    : e.side_agreement === 'confirmed' ? 'Подтверждено каналом'
    : e.side_agreement === 'conflict' ? 'Конфликт сторон' : 'Сторона канала не указана';
  const statusColor = e.side_agreement === 'conflict' ? theme.accent.red
    : e.side_agreement === 'confirmed' ? theme.accent.green
    : e.side_agreement === 'suggested' ? theme.accent.amber : theme.text.muted;

  return (
    <div style={styles.card}>
      <div style={styles.cardHead}>
        {e.can_apply_side && (
          <input type="checkbox" checked={selected} onChange={(ev) => props.onSelect(ev.target.checked)} />
        )}
        <span style={{ ...styles.status, color: statusColor }}>{statusText}</span>
        <span style={styles.spacer} />
        {e.match_score > 0 && <span style={styles.rowMeta}>score {(e.match_score * 100).toFixed(0)}%</span>}
      </div>

      {e.primary_text != null && (
        <div style={styles.side}>
          <div style={styles.sideHead}>основной · {fmt(e.primary_start_server_ms)}
            {e.current_side ? ` · сейчас: ${SIDE_RU(e.current_side)}` : ''}
            {e.has_segment_correction ? ' ✎' : ''}</div>
          <div style={styles.text}>{e.primary_text}</div>
        </div>
      )}
      {e.channel_text != null && (
        <div style={styles.side}>
          <div style={styles.sideHead}>
            канал {(e.channel_index ?? 0) + 1} · {e.channel_label} · {SIDE_RU(e.channel_side)} · {fmt(e.channel_start_server_ms)}
            {e.provider_confidence != null ? ` · ${(e.provider_confidence * 100).toFixed(0)}%` : ''}
          </div>
          <div style={styles.text}>{e.channel_text}</div>
        </div>
      )}
      {e.kind === 'ambiguous' && e.alternatives.length > 0 && (
        <div style={styles.alts}>
          {e.alternatives.map((a) => (
            <div key={a.channel_segment_id} style={styles.rowMeta}>
              канал {a.channel_index + 1}: score {(a.match_score * 100).toFixed(0)}%
            </div>
          ))}
        </div>
      )}
      {e.warnings.map((w, i) => <div key={i} style={styles.warn}>⚠ {w}</div>)}

      <div style={styles.cardActions}>
        {confirming ? (
          <>
            <span style={styles.confirmText}>
              {e.side_agreement === 'conflict'
                ? `У реплики уже задана другая сторона. Заменить на «${SIDE_RU(e.channel_side)}»?`
                : `У реплики уже есть ручная коррекция (метка/заметка сохранятся). Задать сторону «${SIDE_RU(e.channel_side)}»?`}
            </span>
            <button type="button" style={styles.primary} disabled={busy} onClick={props.onConfirmApply}>Заменить</button>
            <button type="button" style={styles.ghost} onClick={props.onCancelConfirm}>Отмена</button>
          </>
        ) : (
          <>
            {e.can_apply_side && canEdit && (
              <button type="button" style={styles.primary} disabled={busy} onClick={props.onApply}>
                Применить сторону канала
              </button>
            )}
            <button type="button" style={styles.ghost} onClick={props.onDismiss}>Скрыть</button>
          </>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  panel: { display: 'flex', flexDirection: 'column', gap: 10 },
  note: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, lineHeight: 1.5 },
  important: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.green, lineHeight: 1.5 },
  chips: { display: 'flex', gap: 6, flexWrap: 'wrap' as const },
  chip: { display: 'inline-flex', gap: 5, alignItems: 'baseline', padding: '3px 8px', background: theme.bg.input, borderRadius: 8 },
  chipLabel: { fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted },
  chipVal: { fontFamily: theme.font.mono, fontSize: 12, fontWeight: 600 },
  filters: { display: 'flex', gap: 6, flexWrap: 'wrap' as const },
  fOff: { padding: '4px 10px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 8, color: theme.text.secondary, cursor: 'pointer', fontSize: 11 },
  fOn: { padding: '4px 10px', background: 'rgba(245,166,35,0.14)', border: `1px solid ${theme.accent.amber}`, borderRadius: 8, color: theme.accent.amber, cursor: 'pointer', fontSize: 11, fontWeight: 600 },
  list: { display: 'flex', flexDirection: 'column', gap: 8 },
  dim: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted },
  warn: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.amber },
  error: { fontFamily: theme.font.mono, fontSize: 12, color: theme.accent.red },
  card: { display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 10px', background: theme.bg.card, borderRadius: 10 },
  cardHead: { display: 'flex', alignItems: 'center', gap: 8 },
  status: { fontFamily: theme.font.mono, fontSize: 11, fontWeight: 600 },
  side: { display: 'flex', flexDirection: 'column', gap: 2, padding: '4px 6px', background: theme.bg.input, borderRadius: 6 },
  sideHead: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  text: { fontFamily: theme.font.body, fontSize: 12, color: theme.text.primary, lineHeight: 1.4 },
  alts: { display: 'flex', flexDirection: 'column', gap: 2 },
  rowMeta: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted },
  cardActions: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const },
  confirmText: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.red },
  actions: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const, marginTop: 4 },
  cbRow: { display: 'flex', alignItems: 'center', gap: 6, fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary },
  spacer: { flex: 1 },
  ghost: { padding: '6px 12px', background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 8, color: theme.text.secondary, cursor: 'pointer', fontSize: 12 },
  primary: { padding: '6px 14px', background: theme.accent.amber, border: 'none', borderRadius: 8, color: '#080A0F', cursor: 'pointer', fontSize: 12, fontWeight: 600 },
};
