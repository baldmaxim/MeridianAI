import { useState } from 'react';
import type { FC } from 'react';
import { TextInput } from '../common';
import styles from './SpeakerSideAssignmentPanel.module.css';

interface ISpeakerNameInputProps {
  value: string;
  placeholder: string;
  onCommit: (v: string) => void;
}

// Поле имени спикера: локальный draft, коммит по blur/Enter, синк при внешнем изменении.
export const SpeakerNameInput: FC<ISpeakerNameInputProps> = ({ value, placeholder, onCommit }) => {
  const [draft, setDraft] = useState(value);
  const [prevValue, setPrevValue] = useState(value);
  // Внешнее значение изменилось — подтягиваем в draft (без эффекта)
  if (value !== prevValue) {
    setPrevValue(value);
    setDraft(value);
  }
  const commit = () => { if (draft.trim() !== value.trim()) onCommit(draft); };
  return (
    <TextInput
      inputClassName={styles.nameInput}
      value={draft}
      placeholder={placeholder}
      clearLabel="имя спикера"
      onClear={() => setDraft('')}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
    />
  );
};
