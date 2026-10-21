import { useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { getConversationTree } from '../../api/conversationTree';
import { putSpeakerRole } from '../../api/speakerRoles';
import type { PublicSpeakerSide } from '../../types';
import { toPublicSpeakerSide } from '../../lib/speakerSides';
import { RebuildTreeButton } from './RebuildTreeButton';
import styles from './ConversationTreePanel.module.css';

interface IUnassignedSpeakersBlockProps {
  meetingId: number;
  canEdit: boolean;
}

const SIDE_CHOICES: { side: PublicSpeakerSide; label: string }[] = [
  { side: 'self', label: 'Мы' },
  { side: 'opponent', label: 'Не мы' },
];

export const UnassignedSpeakersBlock: FC<IUnassignedSpeakersBlockProps> = ({ meetingId, canEdit }) => {
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
      <RebuildTreeButton meetingId={meetingId} onDone={() => setCanRebuild(false)} />
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
    <div className={styles.unassigned}>
      <div className={styles.unassignedTitle}>Не назначены стороны для спикеров</div>
      <div className={styles.unassignedHint}>Выберите, кто относится к нам, а кто к другой стороне.</div>
      {names.map((name) => (
        <div key={name} className={styles.unassignedRow}>
          <span className={styles.unassignedName}>{name}</span>
          <div className={styles.sideBtns}>
            {SIDE_CHOICES.map((c) => (
              <button key={c.side} className={styles.sideBtn} disabled={busy === name}
                      onClick={() => assign(name, c.side)}>{c.label}</button>
            ))}
          </div>
        </div>
      ))}
      {canRebuild && <RebuildTreeButton meetingId={meetingId} onDone={() => setCanRebuild(false)} />}
    </div>
  );
};
