import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';

interface Props {
  // Отправить актуальный контекст из стора (debounce + WS) — см. MeetingPage.pushContext.
  pushContext: () => void;
}

// Краткие смысловые поля контекста: тип переговоров, ваша роль, ключевые условия.
// Тема выводится в карточке «Встреча», слабые стороны — в «Расширенных» (MeetingPage).
export function MeetingContext({ pushContext }: Props) {
  const negotiationType = useMeetingStore((s) => s.negotiationType);
  const meetingRole = useMeetingStore((s) => s.meetingRole);
  const notes = useMeetingStore((s) => s.meetingNotes);
  const setNegotiationType = useMeetingStore((s) => s.setNegotiationType);
  const setMeetingRole = useMeetingStore((s) => s.setMeetingRole);
  const setNotes = useMeetingStore((s) => s.setMeetingNotes);

  const handleNegotiationTypeChange = (value: string) => { setNegotiationType(value); pushContext(); };
  const handleMeetingRoleChange = (value: string) => { setMeetingRole(value); pushContext(); };
  const handleNotesChange = (value: string) => { setNotes(value); pushContext(); };

  return (
    <div className="context-columns" style={styles.columns}>
      <div style={styles.col}>
        <label style={styles.label}>Тип переговоров</label>
        <select
          style={styles.select}
          value={['sale', 'claim', 'negotiation'].includes(negotiationType) ? negotiationType : 'custom'}
          onChange={(e) => {
            if (e.target.value === 'custom') handleNegotiationTypeChange('');
            else handleNegotiationTypeChange(e.target.value);
          }}
        >
          <option value="sale">Продажа / заключение сделки</option>
          <option value="claim">Претензионная работа</option>
          <option value="negotiation">Согласование условий</option>
          <option value="custom">Своё...</option>
        </select>
        {!['sale', 'claim', 'negotiation'].includes(negotiationType) && (
          <input
            type="text"
            placeholder="Введите тип переговоров"
            value={negotiationType}
            onChange={(e) => handleNegotiationTypeChange(e.target.value)}
            style={styles.input}
          />
        )}

        <label style={styles.label}>Ваша роль</label>
        <input
          type="text"
          placeholder="Коммерческий директор"
          style={styles.input}
          value={meetingRole}
          onChange={(e) => handleMeetingRoleChange(e.target.value)}
        />
      </div>

      <div style={styles.col}>
        <label style={styles.label}>Ключевые условия / цели</label>
        <textarea
          placeholder={"Целевая сумма, дедлайн, ключевые требования, ограничения..."}
          value={notes}
          onChange={(e) => handleNotesChange(e.target.value)}
          rows={6}
          style={styles.textarea}
        />
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  columns: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 },
  col: { display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 },
  label: {
    fontSize: 10, fontFamily: theme.font.mono, color: theme.accent.amber,
    letterSpacing: '0.08em', textTransform: 'uppercase' as const, marginTop: 8,
  },
  input: {
    padding: '10px 14px', background: theme.bg.input, border: `1px solid ${theme.border.default}`,
    borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  select: {
    padding: '10px 14px', background: theme.bg.input, border: `1px solid ${theme.border.default}`,
    borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body, outline: 'none',
  },
  textarea: {
    padding: '10px 14px', background: theme.bg.input, border: `1px solid ${theme.border.default}`,
    borderRadius: 7, color: theme.text.primary, fontSize: 13, fontFamily: theme.font.body,
    outline: 'none', resize: 'vertical' as const,
  },
};
