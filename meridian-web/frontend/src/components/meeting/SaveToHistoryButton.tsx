import { useEffect, useState } from 'react';
import type { FC } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { SuccessCheck } from '../common/SuccessCheck';
import styles from './ControlButtons.module.css';

const SAVED_MSG_MS = 3000;

interface ISaveToHistoryButtonProps {
  onSave: () => void;
}

/** «В историю»: отправляет save_to_history и ждёт подтверждения (meetingSavedId) из стора. */
export const SaveToHistoryButton: FC<ISaveToHistoryButtonProps> = ({ onSave }) => {
  const messagesCount = useMeetingStore((s) => s.messages.length);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Подтверждение сохранения приходит из стора (WS): подписка на внешнее хранилище
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = useMeetingStore.subscribe((state, prev) => {
      if (state.meetingSavedId === null || state.meetingSavedId === prev.meetingSavedId) return;
      setSaving(false);
      setSaved(true);
      clearTimeout(timer);
      timer = setTimeout(() => setSaved(false), SAVED_MSG_MS);
      useMeetingStore.getState().setMeetingSavedId(null);
    });
    return () => {
      unsubscribe();
      clearTimeout(timer);
    };
  }, []);

  const handleClick = () => {
    if (messagesCount === 0 || saving) return;
    setSaving(true);
    onSave();
  };

  return (
    <button
      type="button"
      className={`t-btn ${styles.btnSave}`}
      onClick={handleClick}
      disabled={messagesCount === 0 || saving}
      title="Сохранить встречу в историю"
    >
      {saved && !saving && <SuccessCheck show={saved} size={13} />}
      <span>{saving ? 'Сохранение...' : saved ? 'Сохранено' : 'В историю'}</span>
    </button>
  );
};
