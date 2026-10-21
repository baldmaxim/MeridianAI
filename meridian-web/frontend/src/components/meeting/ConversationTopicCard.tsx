import { useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { updateConversationTopic } from '../../api/conversationTree';
import type { ConversationTopic, ConversationTopicStatus, ConversationTopicUpdateInput } from '../../types';
import { Select, TextInput } from '../common';
import styles from './ConversationTreePanel.module.css';

interface IConversationTopicCardProps {
  topic: ConversationTopic;
  meetingId: number;
  canEdit: boolean;
}

const STATUS_META: Record<ConversationTopicStatus, { label: string; cls: string }> = {
  new: { label: 'НОВАЯ', cls: styles.statusNew },
  updated: { label: 'ОБНОВЛЕНО', cls: styles.statusUpdated },
  resolved: { label: 'РЕШЕНО', cls: styles.statusResolved },
  disputed: { label: 'СПОРНО', cls: styles.statusDisputed },
  needs_follow_up: { label: 'НУЖЕН КОНТРОЛЬ', cls: styles.statusFollowUp },
};

const STATUS_OPTIONS: ConversationTopicStatus[] = ['new', 'updated', 'resolved', 'disputed', 'needs_follow_up'];

function isRecent(iso: string): boolean {
  const t = new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime();
  return !Number.isNaN(t) && Date.now() - t < 15000;
}

export const ConversationTopicCard: FC<IConversationTopicCardProps> = ({ topic, meetingId, canEdit }) => {
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
    <div className={`${styles.card} ${recent ? styles.cardRecent : ''}`}>
      <div className={styles.cardHead}>
        {editing ? (
          <TextInput className={styles.titleWrap} inputClassName={styles.titleInput} value={draft.title ?? ''}
                     clearLabel="название темы" onClear={() => setDraft((d) => ({ ...d, title: '' }))}
                     onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} />
        ) : (
          <span className={styles.title}>{topic.title}</span>
        )}
        <span className={`${styles.badge} ${meta.cls}`}>{meta.label}</span>
      </div>

      <div className={styles.cols}>
        <div className={styles.col}>
          <div className={`${styles.colLabel} ${styles.colLabelSelf}`}>МЫ</div>
          {editing ? (
            <textarea className={styles.textarea} value={draft.our_summary ?? ''}
                      onChange={(e) => setDraft((d) => ({ ...d, our_summary: e.target.value }))} />
          ) : topic.our_summary ? (
            <div className={styles.summary}>{topic.our_summary}</div>
          ) : (
            <div className={styles.placeholder}>Наша позиция пока не зафиксирована</div>
          )}
        </div>
        <div className={styles.col}>
          <div className={`${styles.colLabel} ${styles.colLabelOpp}`}>НЕ МЫ</div>
          {editing ? (
            <textarea className={styles.textarea} value={draft.opponent_summary ?? ''}
                      onChange={(e) => setDraft((d) => ({ ...d, opponent_summary: e.target.value }))} />
          ) : topic.opponent_summary ? (
            <div className={styles.summary}>{topic.opponent_summary}</div>
          ) : (
            <div className={styles.placeholder}>Позиция другой стороны пока не зафиксирована</div>
          )}
        </div>
      </div>

      {editing && (
        <div className={styles.editRow}>
          <Select triggerClassName={styles.select} value={draft.status ?? topic.status}
                  ariaLabel="Статус темы"
                  onChange={(v) => setDraft((d) => ({ ...d, status: v as ConversationTopicStatus }))}
                  options={STATUS_OPTIONS.map((s) => ({ value: s, label: STATUS_META[s].label }))} />
          <div className={styles.spacer} />
          <button className={styles.btnGhost} disabled={saving} onClick={() => setEditing(false)}>Отмена</button>
          <button className={styles.btnPrimary} disabled={saving} onClick={save}>Сохранить</button>
        </div>
      )}

      {!editing && (
        <div className={styles.cardFoot}>
          {refs.length > 0 && (
            <button className={styles.linkBtn} onClick={() => toggle(topic.id)}>
              {collapsed === false || collapsed === undefined ? 'Скрыть цитаты' : `Цитаты (${refs.length})`}
            </button>
          )}
          {canEdit && <button className={styles.linkBtn} onClick={startEdit}>Редактировать</button>}
        </div>
      )}

      {!editing && refs.length > 0 && collapsed !== true && (
        <div className={styles.refs}>
          {refs.map((r, i) => (
            <div key={`${r.segment_id}-${i}`} className={styles.refLine}>
              <span className={styles.refTc}>{r.timecode}</span>
              <span className={styles.refSpeaker}>{r.speaker}:</span>
              <span className={styles.refText}>{r.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
