import { useState } from 'react';
import type { FC } from 'react';
import { Collapse } from '../../components/common';
import { PreviousMeetingsContext } from '../../components/context/PreviousMeetingsContext';
import type { MeetingDetail } from '../../types';
import { ClampedText } from './ClampedText';
import { ContextBlock } from './ContextBlock';
import { NEGOTIATION_TYPE_LABELS } from './meetingDetailFormat';
import styles from './MeetingContextHeader.module.css';

interface IMeetingContextHeaderProps {
  meeting: MeetingDetail;
}

interface IChip {
  label: string;
  value: string;
}

/** Контекст встречи в шапке: чипы, длинные заметки в две строки, «Подробнее» (полный контекст с документами), прошлые встречи. */
export const MeetingContextHeader: FC<IMeetingContextHeaderProps> = ({ meeting }) => {
  const [detailsOpen, setDetailsOpen] = useState(false);

  const docsCount = meeting.documents?.length ?? 0;
  const chips: IChip[] = [
    { label: 'Заказчик', value: meeting.customer_name ?? '' },
    { label: 'Объект', value: meeting.object_name ?? '' },
    { label: 'Тема', value: meeting.meeting_topic ?? '' },
    {
      label: 'Тип',
      value: meeting.negotiation_type ? (NEGOTIATION_TYPE_LABELS[meeting.negotiation_type] || meeting.negotiation_type) : '',
    },
    { label: 'Роль', value: meeting.meeting_role ?? '' },
    { label: 'Документы', value: docsCount > 0 ? String(docsCount) : '' },
  ].filter((c) => c.value);

  const hasDetails = !!(
    meeting.meeting_topic || meeting.negotiation_type || meeting.meeting_role
    || meeting.meeting_notes || meeting.opponent_weaknesses || docsCount > 0
  );

  return (
    <div className={styles.wrap}>
      {(chips.length > 0 || hasDetails) && (
        <div className={styles.chips}>
          {chips.map((c) => (
            <span key={c.label} className={styles.chip} title={`${c.label}: ${c.value}`}>
              <span className={styles.chipLabel}>{c.label}</span>
              <span className={styles.chipValue}>{c.value}</span>
            </span>
          ))}
          {hasDetails && (
            <button
              type="button"
              className={styles.detailsBtn}
              aria-expanded={detailsOpen}
              onClick={() => setDetailsOpen((v) => !v)}
            >
              {detailsOpen ? 'Скрыть' : 'Подробнее'}
            </button>
          )}
        </div>
      )}
      {meeting.meeting_notes && <ClampedText label="Заметки" text={meeting.meeting_notes} />}
      {meeting.opponent_weaknesses && <ClampedText label="Слабости оппонента" text={meeting.opponent_weaknesses} />}
      <Collapse open={detailsOpen} className={styles.details}>
        <ContextBlock meeting={meeting} />
      </Collapse>
      <PreviousMeetingsContext
        variant="row"
        meetingId={meeting.id}
        currentCustomerId={meeting.customer_id}
        currentObjectId={meeting.object_id}
      />
    </div>
  );
};
