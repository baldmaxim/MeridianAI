import { useMemo, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import type {
  WSMessageToServer, MultiChannelReconciliationEntry, SpeakerSegmentCorrection,
} from '../../types';
import { putSpeakerCorrection, bulkPutSpeakerCorrections, listSpeakerCorrections } from '../../api/speakerCorrections';
import styles from './MultiChannelReconciliationPanel.module.css';
import tone from './Tone.module.css';
import { ReconciliationChip } from './ReconciliationChip';
import { ReconciliationEntryCard } from './ReconciliationEntryCard';
import {
  buildCorrectionFromReconciliation, buildBulkReconciliationCorrections,
} from '../../lib/applyReconciliationCorrection';

interface Props {
  meetingId: number | null;
  canEdit?: boolean;
  sendJSON: (message: WSMessageToServer) => void;
}

type Filter = 'all' | 'applicable' | 'conflict' | 'ambiguous' | 'channel_only' | 'primary_only';


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
    return <div className={styles.note}>Сопоставление появится, когда live multi-channel candidate
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
    <div className={styles.panel}>
      <div className={styles.note}>
        Multi-channel candidate сравнивается с committed-репликами основного transcript по времени и тексту.
      </div>
      <div className={styles.important}>
        Применение меняет только сторону выбранной реплики через ручную correction. Текст исходного
        transcript не изменяется.
      </div>

      <div className={styles.chips}>
        <ReconciliationChip label="Совпало" value={sum.matched} />
        <ReconciliationChip label="Предложений" value={sum.suggested} toneClass={tone.green} />
        <ReconciliationChip label="Подтверждено" value={sum.confirmed} />
        <ReconciliationChip label="Конфликтов" value={sum.conflicts} toneClass={tone.red} />
        <ReconciliationChip label="Неоднозначно" value={sum.ambiguous} toneClass={tone.amber} />
        <ReconciliationChip label="Только канал" value={sum.channel_only} />
        <ReconciliationChip label="Только основной" value={sum.primary_only} />
      </div>

      <div className={styles.filters}>
        {(['all', 'applicable', 'conflict', 'ambiguous', 'channel_only', 'primary_only'] as Filter[]).map((f) => (
          <button key={f} type="button" className={filter === f ? styles.fOn : styles.fOff} onClick={() => setFilter(f)}>
            {f === 'all' ? 'Все' : f === 'applicable' ? 'Можно применить' : f === 'conflict' ? 'Конфликты'
              : f === 'ambiguous' ? 'Неоднозначные' : f === 'channel_only' ? 'Только канал' : 'Только основной'}
          </button>
        ))}
      </div>

      {recon.truncated && <div className={styles.warn}>Показаны не все записи (превышен лимит).</div>}

      <div className={styles.list}>
        {visible.length === 0 && <div className={styles.dim}>Нет записей для этого фильтра.</div>}
        {visible.map((e) => (
          <ReconciliationEntryCard key={e.entry_id} e={e} fmt={fmt} canEdit={canEdit} busy={busy}
            confirming={confirmId === e.entry_id} selected={!!selected[e.entry_id]}
            onSelect={(v) => selectEntry(e.entry_id, v)}
            onApply={() => applyEntry(e)} onConfirmApply={() => applyEntry(e, true)}
            onCancelConfirm={() => setConfirmId(null)}
            onDismiss={() => dismissEntry(e.entry_id)} />
        ))}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.actions}>
        <button type="button" className={styles.ghost} disabled={busy}
          onClick={() => sendJSON({ type: 'multi_channel_reconciliation_refresh' })}>Обновить</button>
        <span className={styles.spacer} />
        {selectedIds.length > 0 && (
          <label className={styles.cbRow}>
            <input type="checkbox" checked={includeConflicts}
              onChange={(ev) => setIncludeConflicts(ev.target.checked)} />
            Заменять конфликтующие
          </label>
        )}
        <button type="button" className={styles.primary} disabled={busy || !canEdit || !applicableCount}
          onClick={applyBulk}>
          Применить выбранные ({applicableCount}{applicableCount !== selectedIds.length ? ` из ${selectedIds.length}` : ''})
        </button>
      </div>
    </div>
  );
}
