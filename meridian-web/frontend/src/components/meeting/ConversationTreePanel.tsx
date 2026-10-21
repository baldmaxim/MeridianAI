import { useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { refineConversationTree } from '../../api/conversationTree';
import { ConversationTopicCard } from './ConversationTopicCard';
import { UnassignedSpeakersBlock } from './UnassignedSpeakersBlock';
import styles from './ConversationTreePanel.module.css';

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
    <div className={styles.panel}>
      <div className={styles.header}>
        <button className={styles.toggleBtn} onClick={() => setOpen(!open)}>
          <span className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}>▸</span>
          <span className={styles.headerTitle}>Дерево общения</span>
        </button>
        <span className={styles.count}>{topics.length}</span>
        {open && canEdit && meetingId != null && (
          <button className={styles.refineBtn} disabled={refining} onClick={refine} title="Уточнить темы через AI">
            {refining ? '…' : '✨ AI'}
          </button>
        )}
      </div>

      {open && (
        <div className={styles.body}>
          {meetingId != null && <UnassignedSpeakersBlock meetingId={meetingId} canEdit={canEdit} />}
          {ordered.length === 0 ? (
            <div className={styles.empty}>
              Дерево общения появится после назначения сторон спикерам: кто относится к нашей
              стороне, а кто к другой. Назначить можно выше или кликом по имени спикера в транскрипции.
            </div>
          ) : (
            ordered.map((t) => (
              <ConversationTopicCard key={t.id} topic={t} meetingId={meetingId ?? t.meeting_id} canEdit={canEdit} />
            ))
          )}
        </div>
      )}
    </div>
  );
}
