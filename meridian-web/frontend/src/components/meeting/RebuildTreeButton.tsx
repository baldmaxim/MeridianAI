import { useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { rebuildConversationTree } from '../../api/conversationTree';
import styles from './ConversationTreePanel.module.css';

interface IRebuildTreeButtonProps {
  meetingId: number;
  onDone: () => void;
}

export const RebuildTreeButton: FC<IRebuildTreeButtonProps> = ({ meetingId, onDone }) => {
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
    <button className={styles.rebuildBtn} disabled={busy} onClick={rebuild}>
      {busy ? 'Пересборка…' : '↻ Пересобрать дерево'}
    </button>
  );
};
