import { useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { updateConversationTopic, refineConversationTree, rebuildConversationTree, getConversationTree } from '../../api/conversationTree';
import { putSpeakerRole } from '../../api/speakerRoles';
import { theme } from '../../styles/theme';
import type { ConversationTopic, ConversationTopicStatus, ConversationTopicUpdateInput, PublicSpeakerSide } from '../../types';
import { toPublicSpeakerSide } from '../../lib/speakerSides';

const SIDE_CHOICES: { side: PublicSpeakerSide; label: string }[] = [
  { side: 'self', label: 'Мы' },
  { side: 'opponent', label: 'Не мы' },
];

const STATUS_META: Record<ConversationTopicStatus, { label: string; color: string }> = {
  new: { label: 'НОВАЯ', color: theme.accent.green },
  updated: { label: 'ОБНОВЛЕНО', color: theme.accent.amber },
  resolved: { label: 'РЕШЕНО', color: theme.accent.blue },
  disputed: { label: 'СПОРНО', color: theme.accent.red },
  needs_follow_up: { label: 'НУЖЕН КОНТРОЛЬ', color: theme.accent.amberDim },
};

const STATUS_OPTIONS: ConversationTopicStatus[] = ['new', 'updated', 'resolved', 'disputed', 'needs_follow_up'];

function isRecent(iso: string): boolean {
  const t = new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime();
  return !Number.isNaN(t) && Date.now() - t < 15000;
}

function TopicCard({ topic, meetingId, canEdit }: { topic: ConversationTopic; meetingId: number; canEdit: boolean }) {
  const collapsed = useMeetingStore((s) => s.treeCollapsed[topic.id]);
  const toggle = useMeetingStore((s) => s.toggleTopicExpanded);
  const upsert = useMeetingStore((s) => s.upsertConversationTopic);
  const treeVersion = useMeetingStore((s) => s.treeVersion);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<ConversationTopicUpdateInput>({});
  const [saving, setSaving] = useState(false);

  const meta = STATUS_META[topic.status] ?? STATUS_META.new;
  const recent = isRecent(topic.last_updated_at);
  const refs = [...topic.our_refs, ...topic.opponent_refs];

  const startEdit = () => {
    setDraft({
      title: topic.title, status: topic.status,
      our_summary: topic.our_summary ?? '', opponent_summary: topic.opponent_summary ?? '',
    });
    setEditing(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const updated = await updateConversationTopic(meetingId, topic.id, draft);
      upsert(updated, treeVersion + 1);
      setEditing(false);
    } catch { /* нет прав / ошибка — оставляем форму */ }
    finally { setSaving(false); }
  };

  return (
    <div style={{
      ...styles.card,
      borderColor: recent ? theme.border.amber : theme.border.default,
      boxShadow: recent ? `0 0 0 1px ${theme.accent.amberGlow}` : 'none',
    }}>
      <div style={styles.cardHead}>
        {editing ? (
          <input style={styles.titleInput} value={draft.title ?? ''}
                 onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} />
        ) : (
          <span style={styles.title}>{topic.title}</span>
        )}
        <span style={{ ...styles.badge, color: meta.color, borderColor: meta.color }}>{meta.label}</span>
      </div>

      <div style={styles.cols}>
        <div style={styles.col}>
          <div style={{ ...styles.colLabel, color: theme.accent.amber }}>МЫ</div>
          {editing ? (
            <textarea style={styles.textarea} value={draft.our_summary ?? ''}
                      onChange={(e) => setDraft((d) => ({ ...d, our_summary: e.target.value }))} />
          ) : topic.our_summary ? (
            <div style={styles.summary}>{topic.our_summary}</div>
          ) : (
            <div style={styles.placeholder}>Наша позиция пока не зафиксирована</div>
          )}
        </div>
        <div style={styles.col}>
          <div style={{ ...styles.colLabel, color: theme.accent.blue }}>НЕ МЫ</div>
          {editing ? (
            <textarea style={styles.textarea} value={draft.opponent_summary ?? ''}
                      onChange={(e) => setDraft((d) => ({ ...d, opponent_summary: e.target.value }))} />
          ) : topic.opponent_summary ? (
            <div style={styles.summary}>{topic.opponent_summary}</div>
          ) : (
            <div style={styles.placeholder}>Позиция другой стороны пока не зафиксирована</div>
          )}
        </div>
      </div>

      {editing && (
        <div style={styles.editRow}>
          <select style={styles.select} value={draft.status}
                  onChange={(e) => setDraft((d) => ({ ...d, status: e.target.value as ConversationTopicStatus }))}>
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{STATUS_META[s].label}</option>)}
          </select>
          <div style={{ flex: 1 }} />
          <button style={styles.btnGhost} disabled={saving} onClick={() => setEditing(false)}>Отмена</button>
          <button style={styles.btnPrimary} disabled={saving} onClick={save}>Сохранить</button>
        </div>
      )}

      {!editing && (
        <div style={styles.cardFoot}>
          {refs.length > 0 && (
            <button style={styles.linkBtn} onClick={() => toggle(topic.id)}>
              {collapsed === false || collapsed === undefined ? 'Скрыть цитаты' : `Цитаты (${refs.length})`}
            </button>
          )}
          {canEdit && <button style={styles.linkBtn} onClick={startEdit}>Редактировать</button>}
        </div>
      )}

      {!editing && refs.length > 0 && collapsed !== true && (
        <div style={styles.refs}>
          {refs.map((r, i) => (
            <div key={`${r.segment_id}-${i}`} style={styles.refLine}>
              <span style={styles.refTc}>{r.timecode}</span>
              <span style={styles.refSpeaker}>{r.speaker}:</span>
              <span style={styles.refText}>{r.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function UnassignedBlock({ meetingId, canEdit }: { meetingId: number; canEdit: boolean }) {
  const treeUnassigned = useMeetingStore((s) => s.treeUnassigned);
  const turns = useMeetingStore((s) => s.turns);
  const speakerRoles = useMeetingStore((s) => s.speakerRoles);
  const setSpeakerRoles = useMeetingStore((s) => s.setSpeakerRoles);
  const setTree = useMeetingStore((s) => s.setConversationTree);
  const treeVersion = useMeetingStore((s) => s.treeVersion);
  const [busy, setBusy] = useState<string | null>(null);
  const [canRebuild, setCanRebuild] = useState(false);

  // объединяем persisted-неназначенных и live-спикеров из turns без стороны
  const liveSpeakers = Array.from(new Set(turns.map((t) => t.speaker).filter(Boolean)));
  const names = Array.from(new Set([...treeUnassigned, ...liveSpeakers]))
    .filter((n) => toPublicSpeakerSide(speakerRoles[n]) === '');  // legacy ally/third_party = назначено

  if (!canEdit || names.length === 0) {
    return canRebuild && canEdit ? (
      <RebuildButton meetingId={meetingId} onDone={() => setCanRebuild(false)} />
    ) : null;
  }

  const assign = async (name: string, side: PublicSpeakerSide) => {
    setBusy(name);
    try {
      await putSpeakerRole(meetingId, name, { side });
      setSpeakerRoles({ ...speakerRoles, [name]: side });
      setCanRebuild(true);
      // обновим список неназначенных
      const tree = await getConversationTree(meetingId);
      setTree(tree.topics, Math.max(treeVersion, tree.tree_version), tree.unassigned_speakers);
    } catch { /* нет прав / ошибка — игнор */ }
    finally { setBusy(null); }
  };

  return (
    <div style={styles.unassigned}>
      <div style={styles.unassignedTitle}>Не назначены стороны для спикеров</div>
      <div style={styles.unassignedHint}>Выберите, кто относится к нам, а кто к другой стороне.</div>
      {names.map((name) => (
        <div key={name} style={styles.unassignedRow}>
          <span style={styles.unassignedName}>{name}</span>
          <div style={styles.sideBtns}>
            {SIDE_CHOICES.map((c) => (
              <button key={c.side} style={styles.sideBtn} disabled={busy === name}
                      onClick={() => assign(name, c.side)}>{c.label}</button>
            ))}
          </div>
        </div>
      ))}
      {canRebuild && <RebuildButton meetingId={meetingId} onDone={() => setCanRebuild(false)} />}
    </div>
  );
}

function RebuildButton({ meetingId, onDone }: { meetingId: number; onDone: () => void }) {
  const setTree = useMeetingStore((s) => s.setConversationTree);
  const treeVersion = useMeetingStore((s) => s.treeVersion);
  const [busy, setBusy] = useState(false);
  const rebuild = async () => {
    setBusy(true);
    try {
      const tree = await rebuildConversationTree(meetingId);
      setTree(tree.topics, Math.max(treeVersion + 1, tree.tree_version), tree.unassigned_speakers);
      onDone();
    } catch { /* игнор */ }
    finally { setBusy(false); }
  };
  return (
    <button style={styles.rebuildBtn} disabled={busy} onClick={rebuild}>
      {busy ? 'Пересборка…' : '↻ Пересобрать дерево'}
    </button>
  );
}

export function ConversationTreePanel({ meetingId }: { meetingId: number | null }) {
  const topics = useMeetingStore((s) => s.conversationTree);
  const open = useMeetingStore((s) => s.treePanelOpen);
  const setOpen = useMeetingStore((s) => s.setTreePanelOpen);
  const canEdit = useMeetingStore((s) => s.canSendAudio);
  const setTree = useMeetingStore((s) => s.setConversationTree);
  const treeVersion = useMeetingStore((s) => s.treeVersion);
  const [refining, setRefining] = useState(false);

  const ordered = [...topics].sort(
    (a, b) => new Date(b.last_updated_at).getTime() - new Date(a.last_updated_at).getTime(),
  );

  const refine = async () => {
    if (meetingId == null) return;
    setRefining(true);
    try {
      const tree = await refineConversationTree(meetingId);
      setTree(tree.topics, Math.max(treeVersion, tree.tree_version), tree.unassigned_speakers);
    } catch { /* троттлинг/нет ключа — игнор */ }
    finally { setRefining(false); }
  };

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <button style={styles.toggleBtn} onClick={() => setOpen(!open)}>
          <span style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s', display: 'inline-block' }}>▸</span>
          <span style={styles.headerTitle}>Дерево общения</span>
        </button>
        <span style={styles.count}>{topics.length}</span>
        {open && canEdit && meetingId != null && (
          <button style={styles.refineBtn} disabled={refining} onClick={refine} title="Уточнить темы через AI">
            {refining ? '…' : '✨ AI'}
          </button>
        )}
      </div>

      {open && (
        <div style={styles.body}>
          {meetingId != null && <UnassignedBlock meetingId={meetingId} canEdit={canEdit} />}
          {ordered.length === 0 ? (
            <div style={styles.empty}>
              Дерево общения появится после назначения сторон спикерам: кто относится к нашей
              стороне, а кто к другой. Назначить можно выше или кликом по имени спикера в транскрипции.
            </div>
          ) : (
            ordered.map((t) => (
              <TopicCard key={t.id} topic={t} meetingId={meetingId ?? t.meeting_id} canEdit={canEdit} />
            ))
          )}
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  panel: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, background: theme.bg.tertiary, borderRadius: 10, border: `1px solid ${theme.border.default}`, overflow: 'hidden' },
  header: { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', borderBottom: `1px solid ${theme.border.default}`, background: theme.bg.secondary },
  toggleBtn: { background: 'none', border: 'none', color: theme.text.primary, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, padding: 0 },
  headerTitle: { fontFamily: theme.font.heading, fontWeight: 800, fontSize: 13, letterSpacing: 0.3 },
  count: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, background: theme.bg.elevated, borderRadius: 6, padding: '1px 7px' },
  refineBtn: { marginLeft: 'auto', background: theme.accent.amberGlow, color: theme.accent.amber, border: `1px solid ${theme.border.amber}`, borderRadius: 6, fontSize: 11, padding: '3px 8px', cursor: 'pointer', fontFamily: theme.font.mono },
  body: { flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0 },
  empty: { color: theme.text.muted, fontSize: 12, lineHeight: 1.5, padding: '12px 8px', fontFamily: theme.font.body },
  unassigned: { background: theme.bg.elevated, border: `1px solid ${theme.border.amber}`, borderRadius: 9, padding: 10, display: 'flex', flexDirection: 'column', gap: 8 },
  unassignedTitle: { fontFamily: theme.font.mono, fontSize: 10, fontWeight: 700, letterSpacing: 0.4, color: theme.accent.amber },
  unassignedHint: { fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted, lineHeight: 1.4 },
  unassignedRow: { display: 'flex', flexDirection: 'column', gap: 5 },
  unassignedName: { fontSize: 12, color: theme.text.primary, fontWeight: 600, wordBreak: 'break-word' },
  sideBtns: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  sideBtn: { background: theme.bg.input, color: theme.text.secondary, border: `1px solid ${theme.border.default}`, borderRadius: 6, padding: '3px 9px', fontSize: 11, cursor: 'pointer', fontFamily: theme.font.body },
  rebuildBtn: { background: theme.accent.amberGlow, color: theme.accent.amber, border: `1px solid ${theme.border.amber}`, borderRadius: 6, padding: '5px 10px', fontSize: 11, cursor: 'pointer', fontFamily: theme.font.mono, marginTop: 4 },
  card: { background: theme.bg.card, border: '1px solid', borderRadius: 9, padding: 10, transition: 'border-color .3s, box-shadow .3s' },
  cardHead: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 8 },
  title: { fontFamily: theme.font.body, fontWeight: 600, fontSize: 13, color: theme.text.primary, lineHeight: 1.3 },
  titleInput: { flex: 1, background: theme.bg.input, color: theme.text.primary, border: `1px solid ${theme.border.default}`, borderRadius: 6, padding: '4px 7px', fontSize: 13, fontFamily: theme.font.body },
  badge: { fontFamily: theme.font.mono, fontSize: 9, fontWeight: 700, letterSpacing: 0.5, border: '1px solid', borderRadius: 5, padding: '2px 6px', whiteSpace: 'nowrap', flexShrink: 0 },
  cols: { display: 'flex', gap: 8 },
  col: { flex: 1, minWidth: 0 },
  colLabel: { fontFamily: theme.font.mono, fontSize: 9, fontWeight: 700, letterSpacing: 0.6, marginBottom: 4 },
  summary: { fontSize: 12, color: theme.text.primary, lineHeight: 1.4, fontFamily: theme.font.body, wordBreak: 'break-word' },
  placeholder: { fontSize: 11, color: theme.text.muted, fontStyle: 'italic', lineHeight: 1.4 },
  textarea: { width: '100%', minHeight: 48, background: theme.bg.input, color: theme.text.primary, border: `1px solid ${theme.border.default}`, borderRadius: 6, padding: 6, fontSize: 12, fontFamily: theme.font.body, resize: 'vertical', boxSizing: 'border-box' },
  editRow: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 },
  select: { background: theme.bg.input, color: theme.text.primary, border: `1px solid ${theme.border.default}`, borderRadius: 6, padding: '4px 6px', fontSize: 11, fontFamily: theme.font.mono },
  cardFoot: { display: 'flex', gap: 14, marginTop: 8 },
  linkBtn: { background: 'none', border: 'none', color: theme.text.secondary, cursor: 'pointer', fontSize: 11, fontFamily: theme.font.mono, padding: 0 },
  btnGhost: { background: 'none', border: `1px solid ${theme.border.default}`, color: theme.text.secondary, borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer' },
  btnPrimary: { background: theme.accent.amber, border: 'none', color: '#080A0F', borderRadius: 6, padding: '4px 12px', fontSize: 11, fontWeight: 700, cursor: 'pointer' },
  refs: { marginTop: 8, paddingTop: 8, borderTop: `1px solid ${theme.border.default}`, display: 'flex', flexDirection: 'column', gap: 4 },
  refLine: { fontSize: 11, lineHeight: 1.4, fontFamily: theme.font.body, color: theme.text.secondary, display: 'flex', gap: 6, flexWrap: 'wrap' },
  refTc: { fontFamily: theme.font.mono, color: theme.text.muted, flexShrink: 0 },
  refSpeaker: { color: theme.text.secondary, fontWeight: 600, flexShrink: 0 },
  refText: { color: theme.text.primary, wordBreak: 'break-word' },
};
