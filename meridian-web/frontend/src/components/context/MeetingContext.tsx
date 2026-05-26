import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';

interface Props {
  onContextChange: (topic: string, notes: string, negotiationType: string, meetingRole: string, opponentWeaknesses: string) => void;
}

export function MeetingContext({ onContextChange }: Props) {
  const topic = useMeetingStore((s) => s.meetingTopic);
  const notes = useMeetingStore((s) => s.meetingNotes);
  const negotiationType = useMeetingStore((s) => s.negotiationType);
  const meetingRole = useMeetingStore((s) => s.meetingRole);
  const opponentWeaknesses = useMeetingStore((s) => s.opponentWeaknesses);
  const setTopic = useMeetingStore((s) => s.setMeetingTopic);
  const setNotes = useMeetingStore((s) => s.setMeetingNotes);
  const setNegotiationType = useMeetingStore((s) => s.setNegotiationType);
  const setMeetingRole = useMeetingStore((s) => s.setMeetingRole);
  const setOpponentWeaknesses = useMeetingStore((s) => s.setOpponentWeaknesses);

  const send = (t: string, n: string, nt: string, mr: string, ow: string) => {
    onContextChange(t, n, nt, mr, ow);
  };

  const handleTopicChange = (value: string) => {
    setTopic(value);
    send(value, notes, negotiationType, meetingRole, opponentWeaknesses);
  };

  const handleNotesChange = (value: string) => {
    setNotes(value);
    send(topic, value, negotiationType, meetingRole, opponentWeaknesses);
  };

  const handleNegotiationTypeChange = (value: string) => {
    setNegotiationType(value);
    send(topic, notes, value, meetingRole, opponentWeaknesses);
  };

  const handleMeetingRoleChange = (value: string) => {
    setMeetingRole(value);
    send(topic, notes, negotiationType, value, opponentWeaknesses);
  };

  const handleOpponentWeaknessesChange = (value: string) => {
    setOpponentWeaknesses(value);
    send(topic, notes, negotiationType, meetingRole, value);
  };

  return (
    <div className="context-columns" style={styles.columns}>
      {/* Left: meeting context */}
      <div style={styles.card}>
        <div style={styles.cardHeader}>
          <span style={styles.dot} />
          <span style={styles.cardTitle}>Контекст встречи</span>
        </div>

        <label style={styles.label}>Тема встречи</label>
        <input
          type="text"
          placeholder="Например: Финальные условия контракта — ЖК Рассвет"
          value={topic}
          onChange={(e) => handleTopicChange(e.target.value)}
          style={styles.input}
        />

        <label style={styles.label}>Тип переговоров</label>
        <select style={styles.select} value={['sale','claim','negotiation'].includes(negotiationType) ? negotiationType : 'custom'} onChange={(e) => {
          if (e.target.value === 'custom') handleNegotiationTypeChange('');
          else handleNegotiationTypeChange(e.target.value);
        }}>
          <option value="sale">Продажа / заключение сделки</option>
          <option value="claim">Претензионная работа</option>
          <option value="negotiation">Согласование условий</option>
          <option value="custom">Своё...</option>
        </select>
        {!['sale','claim','negotiation'].includes(negotiationType) && (
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

      {/* Right: notes & conditions */}
      <div style={styles.card}>
        <div style={styles.cardHeader}>
          <span style={styles.dot} />
          <span style={styles.cardTitle}>Заметки и условия</span>
        </div>

        <label style={styles.label}>Ключевые условия / цели</label>
        <textarea
          placeholder={"Целевая сумма, дедлайн, ключевые требования, ограничения..."}
          value={notes}
          onChange={(e) => handleNotesChange(e.target.value)}
          rows={5}
          style={styles.textarea}
        />

        <label style={styles.label}>Слабые стороны оппонента</label>
        <textarea
          placeholder={"Известные проблемы, сорванные сроки, рыночная позиция..."}
          value={opponentWeaknesses}
          onChange={(e) => handleOpponentWeaknessesChange(e.target.value)}
          rows={3}
          style={styles.textarea}
        />
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  columns: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 20,
  },
  card: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 20,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent.amber,
    flexShrink: 0,
  },
  cardTitle: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.14em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
  },
  label: {
    fontSize: 10,
    fontFamily: theme.font.mono,
    color: theme.accent.amber,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    marginTop: 8,
  },
  input: {
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 13,
    fontFamily: theme.font.body,
    outline: 'none',
  },
  select: {
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 13,
    fontFamily: theme.font.body,
    outline: 'none',
  },
  textarea: {
    padding: '10px 14px',
    background: theme.bg.input,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.primary,
    fontSize: 13,
    fontFamily: theme.font.body,
    outline: 'none',
    resize: 'vertical' as const,
  },
};
