import { useState } from 'react';
import type { FC } from 'react';
import { TextInput } from '../components/common';
import { ProtocolSection } from '../components/protocol/ProtocolSection';
import { LearningCandidates } from '../components/learning/LearningCandidates';
import { PreviousMeetingsContext } from '../components/context/PreviousMeetingsContext';
import {
  useMeetingDetail, useUpdateMeetingTitle, useDeleteMeeting, useContinueMeeting,
} from '../hooks/queries/meetings';
import { meetingDisplayName } from '../lib/meetingName';
import { ContextBlock } from './meetingDetail/ContextBlock';
import { formatDateTime, formatRecorded, formatTime } from './meetingDetail/meetingDetailFormat';
import { PanelHeader } from './meetingDetail/PanelHeader';
import { StrengthenCard } from './meetingDetail/StrengthenCard';
import { SuggestionCard } from './meetingDetail/SuggestionCard';
import { TranscriptRow } from './meetingDetail/TranscriptRow';
import styles from './MeetingDetailPage.module.css';

interface IMeetingDetailPageProps {
  meetingId: number;
  onBack: () => void;
  onContinue: () => void;
  backLabel?: string;
}

type TMobileTab = 'transcript' | 'suggestions' | 'context';

const MOBILE_TABS: ReadonlyArray<{ key: TMobileTab; label: string }> = [
  { key: 'transcript', label: 'Транскрипция' },
  { key: 'suggestions', label: 'Подсказки' },
  { key: 'context', label: 'Контекст' },
];

export const MeetingDetailPage: FC<IMeetingDetailPageProps> = ({
  meetingId, onBack, onContinue, backLabel = 'К истории',
}) => {
  const { data: meeting, isPending, isError } = useMeetingDetail(meetingId);
  const updateTitleMut = useUpdateMeetingTitle();
  const deleteMut = useDeleteMeeting();
  const continueMut = useContinueMeeting();

  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [mobileTab, setMobileTab] = useState<TMobileTab>('transcript');
  const [confirmDelete, setConfirmDelete] = useState(false);

  function startEditTitle() {
    setTitleDraft(meeting?.title || '');
    setEditingTitle(true);
  }

  async function saveTitle() {
    if (!meeting || !titleDraft.trim()) return;
    try {
      await updateTitleMut.mutateAsync({ id: meetingId, title: titleDraft.trim() });
      setEditingTitle(false);
    } catch { /* ignore */ }
  }

  async function handleDelete() {
    try {
      await deleteMut.mutateAsync(meetingId);
      onBack();
    } catch { /* ignore */ }
  }

  async function handleContinue() {
    try {
      await continueMut.mutateAsync(meetingId);
      onContinue();
    } catch { /* ignore */ }
  }

  if (isPending) return <div className={styles.loading}>Загрузка...</div>;
  if (isError || !meeting) {
    return <div className={`${styles.loading} ${styles.loadingError}`}>{isError ? 'Ошибка загрузки встречи' : 'Не найдено'}</div>;
  }

  const suggestions = meeting.suggestions.filter(s => s.source === 'suggestion');
  const strengthens = meeting.suggestions.filter(s => s.source === 'strengthen');
  const recorded = formatRecorded(meeting.recorded_seconds);

  return (
    <div className={`detail-container ${styles.container}`}>
      {/* Top bar */}
      <div className={styles.topBar}>
        <button onClick={onBack} className={`t-btn ${styles.backBtn}`}>&larr; {backLabel}</button>
        <span className={styles.topTitle}>ДЕТАЛИ ВСТРЕЧИ</span>
        <button onClick={handleContinue} className={`t-btn t-btn-amber ${styles.continueBtn}`}>
          Продолжить
        </button>
        <button
          onClick={() => setConfirmDelete(true)}
          className={`t-btn t-btn-red ${styles.deleteBtn}`}
        >
          Удалить
        </button>
      </div>

      {/* Delete confirm */}
      {confirmDelete && (
        <div className={styles.confirmBar}>
          <span className={styles.confirmText}>Удалить встречу и все данные?</span>
          <button onClick={handleDelete} className={`t-btn t-btn-red ${styles.confirmYes}`}>Да, удалить</button>
          <button onClick={() => setConfirmDelete(false)} className={`t-btn ${styles.confirmNo}`}>Отмена</button>
        </div>
      )}

      {/* Title */}
      <div className={styles.titleRow}>
        {editingTitle ? (
          <TextInput
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onClear={() => setTitleDraft('')}
            clearLabel="название встречи"
            onBlur={saveTitle}
            onKeyDown={(e) => e.key === 'Enter' && saveTitle()}
            autoFocus
            className={styles.titleField}
          />
        ) : (
          <h2 className={styles.title} onClick={startEditTitle}>
            {meetingDisplayName(meeting)}
          </h2>
        )}
        <div className={styles.titleMeta}>
          {formatDateTime(meeting.started_at)}
          {meeting.ended_at && ` — ${formatTime(meeting.ended_at)}`}
          {recorded && ` · ${recorded}`}
        </div>
      </div>

      {/* Этап 5: протокол встречи */}
      <ProtocolSection meetingId={meetingId} />

      {/* Этап 8: использованные как контекст прошлые встречи */}
      <PreviousMeetingsContext
        meetingId={meetingId}
        currentCustomerId={meeting.customer_id}
        currentObjectId={meeting.object_id}
      />

      {/* Этап 7: кандидаты в базу знаний по этой встрече */}
      <div className={`${styles.section} ${styles.knowledgeSection}`}>
        <PanelHeader title="База знаний по встрече" plain />
        <LearningCandidates meetingId={meetingId} compact />
      </div>

      {/* Mobile tabs */}
      <div className={`detail-mobile-tabs ${styles.mobileTabs}`}>
        {MOBILE_TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setMobileTab(key)}
            className={`t-btn ${styles.mobileTab}${mobileTab === key ? ` ${styles.mobileTabActive}` : ''}`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Two-panel layout */}
      <div className={`detail-panels ${styles.panels}`}>
        {/* Left: Transcript */}
        <div className={`detail-left ${mobileTab !== 'transcript' ? 'detail-hide-mobile' : ''} ${styles.leftPanel}`}>
          <PanelHeader title="Транскрипция" meta={`${meeting.segments.length} сегментов`} />
          <div className={styles.transcriptList}>
            {meeting.segments.length === 0 && (
              <div className={styles.emptyPanel}>Нет данных транскрипции</div>
            )}
            {meeting.segments.map((seg, i) => (
              <TranscriptRow key={seg.segment_id || i} segment={seg} />
            ))}
          </div>
        </div>

        {/* Right: Suggestions + Context */}
        <div className={`detail-right ${mobileTab === 'transcript' ? 'detail-hide-mobile' : ''} ${styles.rightPanel}`}>
          {/* Context section */}
          <div className={`${mobileTab === 'suggestions' ? 'detail-hide-mobile ' : ''}${styles.section}`}>
            <PanelHeader title="Контекст" />
            <ContextBlock meeting={meeting} />
          </div>

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <div className={`${mobileTab === 'context' ? 'detail-hide-mobile ' : ''}${styles.section}`}>
              <PanelHeader title="Подсказки" meta={suggestions.length} />
              <div className={styles.suggestionList}>
                {suggestions.map((s) => (
                  <SuggestionCard key={s.id} suggestion={s} />
                ))}
              </div>
            </div>
          )}

          {/* Strengthen */}
          {strengthens.length > 0 && (
            <div className={`${mobileTab === 'context' ? 'detail-hide-mobile ' : ''}${styles.section}`}>
              <PanelHeader title="Усиления позиции" meta={strengthens.length} accent="green" />
              <div className={styles.suggestionList}>
                {strengthens.map((s) => (
                  <StrengthenCard key={s.id} suggestion={s} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
