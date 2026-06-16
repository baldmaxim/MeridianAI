import { useState, useEffect } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import type { Customer, ProjectObject } from '../../types';
import { listCustomers } from '../../api/customers';
import { listObjects } from '../../api/objects';
import { createMeeting, updateMeeting } from '../../api/meetings';
import { apiErrorMessage } from '../../lib/apiError';
import { PreviousMeetingsContext } from './PreviousMeetingsContext';
import { MeetingAISettingsBlock } from './MeetingAISettings';

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

  // Этап 1 MVP: выбор заказчика/объекта из справочника
  const selectedCustomerId = useMeetingStore((s) => s.selectedCustomerId);
  const selectedObjectId = useMeetingStore((s) => s.selectedObjectId);
  const draftMeetingId = useMeetingStore((s) => s.draftMeetingId);
  const setSelectedCustomerId = useMeetingStore((s) => s.setSelectedCustomerId);
  const setSelectedObjectId = useMeetingStore((s) => s.setSelectedObjectId);
  const setDraftMeetingId = useMeetingStore((s) => s.setDraftMeetingId);

  const [customers, setCustomers] = useState<Customer[]>([]);
  const [objects, setObjects] = useState<ProjectObject[]>([]);
  const [customerName, setCustomerName] = useState('');
  const [dirError, setDirError] = useState('');
  const [dirInfo, setDirInfo] = useState('');

  useEffect(() => {
    listCustomers().then(setCustomers).catch(() => { /* справочник может быть пуст */ });
  }, []);

  // объекты, отфильтрованные по выбранному заказчику
  useEffect(() => {
    if (selectedCustomerId == null) { setObjects([]); return; }
    listObjects(selectedCustomerId).then(setObjects).catch(() => setObjects([]));
  }, [selectedCustomerId]);

  // при возврате к контексту/выборе объекта — подставить имя выбранного заказчика в combobox
  useEffect(() => {
    if (selectedCustomerId == null || !customers.length) return;
    const c = customers.find((c) => c.id === selectedCustomerId);
    if (c) setCustomerName((prev) => (prev.trim() ? prev : c.name));
  }, [selectedCustomerId, customers]);

  /** Сохранить выбор в draft-встрече (POST либо PATCH). Заказчик — по имени (найти-или-создать).
   *  WS подхватит активную. Возвращённый customer_id синхронизируем со store. */
  async function persistDraft(custName: string | null, objectId: number | null) {
    setDirError(''); setDirInfo('');
    try {
      let m;
      if (draftMeetingId) {
        m = await updateMeeting(draftMeetingId, { customer_name: custName, object_id: objectId });
      } else {
        m = await createMeeting({
          customer_name: custName, object_id: objectId,
          meeting_topic: topic || null, meeting_notes: notes || null,
          negotiation_type: negotiationType || null, meeting_role: meetingRole || null,
          opponent_weaknesses: opponentWeaknesses || null,
        });
        setDraftMeetingId(m.id);
      }
      if (m) setSelectedCustomerId(m.customer_id);
      setDirInfo('Встреча подготовлена — заказчик и объект привязаны');
    } catch (e) {
      setDirError(apiErrorMessage(e, 'Не удалось привязать объект к встрече'));
    }
  }

  // ввод/выбор заказчика: имя — для combobox, id (если совпало с существующим) — для фильтра объектов
  const handleCustomerNameChange = (value: string) => {
    setCustomerName(value);
    setDirError(''); setDirInfo('');
    const match = customers.find((c) => c.name.trim().toLowerCase() === value.trim().toLowerCase());
    setSelectedCustomerId(match ? match.id : null);
    setSelectedObjectId(null); // сменился заказчик — сбрасываем объект
  };

  // фиксируем заказчика в draft по завершении ввода. Если объект выбран — заказчик уже
  // привязан через него (handleObjectChange), не трогаем, чтобы не отвязать объект.
  const handleCustomerBlur = () => {
    const name = customerName.trim();
    if (name && selectedObjectId == null) persistDraft(name, null);
  };

  const handleObjectChange = (value: string) => {
    const id = value === '' ? null : Number(value);
    setSelectedObjectId(id);
    // объект автозадаёт заказчика
    const obj = objects.find((o) => o.id === id);
    if (obj) { setSelectedCustomerId(obj.customer_id); setCustomerName(obj.customer_name || ''); }
    if (id != null) persistDraft(obj?.customer_name ?? (customerName.trim() || null), id);
  };

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
   <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
    {/* Этап 1 MVP: заказчик/объект из справочника */}
    <div style={styles.dirCard}>
      <div style={styles.cardHeader}>
        <span style={styles.dot} />
        <span style={styles.cardTitle}>Заказчик и объект</span>
      </div>
      <div className="context-columns" style={styles.columns}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={styles.label}>Заказчик</label>
          <input
            style={styles.select}
            list="meeting-customers-dl"
            value={customerName}
            onChange={(e) => handleCustomerNameChange(e.target.value)}
            onBlur={handleCustomerBlur}
            placeholder="выберите или впишите нового"
          />
          <datalist id="meeting-customers-dl">
            {customers.map((c) => <option key={c.id} value={c.name} />)}
          </datalist>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={styles.label}>Объект</label>
          <select
            style={styles.select}
            value={selectedObjectId ?? ''}
            onChange={(e) => handleObjectChange(e.target.value)}
            disabled={!customerName.trim()}
          >
            <option value="">{!customerName.trim() ? 'сначала выберите заказчика' : '— не выбран —'}</option>
            {objects.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </div>
      </div>
      {dirInfo && <div style={{ ...styles.dirHint, color: theme.accent.green }}>{dirInfo}</div>}
      {dirError && <div style={{ ...styles.dirHint, color: theme.accent.red }}>{dirError}</div>}
    </div>

    {/* Этап 9: AI-настройки встречи */}
    {draftMeetingId && <MeetingAISettingsBlock meetingId={draftMeetingId} />}

    {/* Этап 8: предыдущие встречи как контекст (нужна подготовленная draft-встреча) */}
    {draftMeetingId ? (
      <PreviousMeetingsContext
        meetingId={draftMeetingId}
        currentCustomerId={selectedCustomerId}
        currentObjectId={selectedObjectId}
      />
    ) : (
      <div style={styles.dirCard}>
        <div style={styles.cardHeader}>
          <span style={styles.dot} />
          <span style={styles.cardTitle}>Предыдущие встречи как контекст</span>
        </div>
        <div style={styles.dirHint}>
          Выберите заказчика или объект — встреча подготовится, и можно будет добавить прошлые встречи.
        </div>
      </div>
    )}

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
  dirCard: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 12,
    padding: 20,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  dirHint: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.text.muted,
    letterSpacing: '0.04em',
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
