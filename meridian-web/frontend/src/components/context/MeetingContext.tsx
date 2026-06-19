import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';

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
    <div style={styles.col}>
      <label style={styles.label}>Тип переговоров</label>
      <input
        type="text"
        list="negotiation-type-suggestions"
        placeholder="Например: согласование условий"
        value={negotiationType}
        onChange={(e) => handleNegotiationTypeChange(e.target.value)}
        style={styles.input}
      />
      <datalist id="negotiation-type-suggestions">
        {TYPE_SUGGESTIONS.map((t) => <option key={t} value={t} />)}
      </datalist>

      <label style={styles.label}>Ключевые условия / цели</label>
      <textarea
        placeholder={"Целевая сумма, дедлайн, ключевые требования, ограничения..."}
        value={notes}
        onChange={(e) => handleNotesChange(e.target.value)}
        rows={6}
        style={styles.textarea}
      />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  col: { display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 },
  label: {
    fontSize: 10, fontFamily: theme.font.mono, color: theme.accent.amber,
    letterSpacing: '0.08em', textTransform: 'uppercase' as const, marginTop: 8,
  },
  input: {
    padding: '10px 14px', background: theme.bg.input, border: `1px solid ${theme.border.default}`,
    borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  textarea: {
    padding: '10px 14px', background: theme.bg.input, border: `1px solid ${theme.border.default}`,
    borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body,
    outline: 'none', resize: 'vertical' as const,
  },
};
