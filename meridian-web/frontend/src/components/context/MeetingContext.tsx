import { useMeetingStore } from '../../store/meetingStore';
import { Combobox } from '../common';
import styles from './MeetingContext.module.css';

interface Props {
  // Отправить актуальный контекст из стора (debounce + WS) — см. MeetingPage.pushContext.
  pushContext: () => void;
}

// Краткие смысловые поля контекста: тип переговоров (свободный ввод) и ключевые условия.
// «Ваша роль» убрана — задаётся в «Роли переговоров». Тема — read-only в карточке «Встреча».
const TYPE_SUGGESTIONS = ['Продажа / заключение сделки', 'Претензионная работа', 'Согласование условий'];

export function MeetingContext({ pushContext }: Props) {
  const negotiationType = useMeetingStore((s) => s.negotiationType);
  const notes = useMeetingStore((s) => s.meetingNotes);
  const setNegotiationType = useMeetingStore((s) => s.setNegotiationType);
  const setNotes = useMeetingStore((s) => s.setMeetingNotes);

  const handleNegotiationTypeChange = (value: string) => { setNegotiationType(value); pushContext(); };
  const handleNotesChange = (value: string) => { setNotes(value); pushContext(); };

  return (
    <div className={styles.col}>
      <label className={styles.label}>Тип переговоров</label>
      <Combobox
        placeholder="Например: согласование условий"
        value={negotiationType}
        onChange={handleNegotiationTypeChange}
        options={TYPE_SUGGESTIONS}
        inputClassName={styles.input}
      />

      <label className={styles.label}>Ключевые условия / цели</label>
      <textarea
        placeholder={"Целевая сумма, дедлайн, ключевые требования, ограничения..."}
        value={notes}
        onChange={(e) => handleNotesChange(e.target.value)}
        rows={6}
        className={styles.textarea}
      />
    </div>
  );
}
