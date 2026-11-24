import { useMemo, useState } from 'react';
import type { FC } from 'react';
import { TextInput } from '../components/common';
import { PreviousMeetingsContext } from '../components/context/PreviousMeetingsContext';
import { LearningCandidates } from '../components/learning/LearningCandidates';
import {
  useMeetingDetail, useUpdateMeetingTitle, useDeleteMeeting, useContinueMeeting,
} from '../hooks/queries/meetings';
import { useMediaQuery } from '../hooks/useMediaQuery';
import type { SpeakerRoleOut } from '../types';
import { cx } from '../utils/cx';
import { meetingDisplayName } from '../lib/meetingName';
import { MeetingContextHeader } from './meetingDetail/MeetingContextHeader';
import { MeetingMainWindow } from './meetingDetail/MeetingMainWindow';
import type { TMainTab } from './meetingDetail/MeetingMainWindow';
import { formatDateTime, formatRecorded, formatTime } from './meetingDetail/meetingDetailFormat';
import { PanelHeader } from './meetingDetail/PanelHeader';
import { StrengthenCard } from './meetingDetail/StrengthenCard';
import { SuggestionCard } from './meetingDetail/SuggestionCard';
import styles from './MeetingDetailPage.module.css';

interface IMeetingDetailPageProps {
  meetingId: number;
  onBack: () => void;
  onContinue: () => void;
  backLabel?: string;
}

const DESKTOP_QUERY = '(min-width: 769px)';
const WIDE_QUERY = '(min-width: 1024px)';

type TPageTab = 'transcript' | 'protocol' | 'suggestions' | 'strengthen' | 'knowledge';

const PAGE_TABS: ReadonlyArray<{ key: TPageTab; label: string }> = [
  { key: 'transcript', label: 'Транскрипт' },
  { key: 'protocol', label: 'Протокол' },
  { key: 'suggestions', label: 'Подсказки' },
  { key: 'strengthen', label: 'Усиления' },
  { key: 'knowledge', label: 'Знания' },
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
  const [tab, setTab] = useState<TPageTab>('transcript');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const isWide = useMediaQuery(WIDE_QUERY);
  const [roles, setRoles] = useState<SpeakerRoleOut[]>([]);
  const [protocolRefresh, setProtocolRefresh] = useState(0);
  const rolesByLabel = useMemo(() => new Map(roles.map((r) => [r.speaker_label, r])), [roles]);

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
  const mainTab: TMainTab = tab === 'protocol' ? 'protocol' : 'transcript';
  const mainVisible = tab === 'transcript' || tab === 'protocol';

  // «Продолжить» и «Удалить»: на десктопе — в строке названия, на телефоне — в верхней панели
  const actions = (
    <>
      <button onClick={handleContinue} className={`t-btn t-btn-amber ${styles.continueBtn}`}>
        Продолжить
      </button>
      <button
        onClick={() => setConfirmDelete(true)}
        className={`t-btn t-btn-red ${styles.deleteBtn}`}
      >
        Удалить
      </button>
    </>
  );

  return (
    <div className={`detail-container ${styles.container}`}>
      {/* Top bar */}
      <div className={styles.topBar}>
        <button onClick={onBack} className={`t-btn ${styles.backBtn}`}>&larr; {backLabel}</button>
        <span className={styles.topTitle}>ДЕТАЛИ ВСТРЕЧИ</span>
        {!isDesktop && actions}
      </div>

      {/* Title */}
      <div className={styles.titleRow}>
        <div className={styles.titleBlock}>
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
        {isDesktop && <div className={styles.titleActions}>{actions}</div>}
      </div>

      {/* Тема встречи — целиком, отдельной строкой под названием */}
      {meeting.meeting_topic && <p className={styles.topic}>{meeting.meeting_topic}</p>}

      {/* Delete confirm — под строкой названия */}
      {confirmDelete && (
        <div className={styles.confirmBar}>
          <span className={styles.confirmText}>Удалить встречу и все данные?</span>
          <button onClick={handleDelete} className={`t-btn t-btn-red ${styles.confirmYes}`}>Да, удалить</button>
          <button onClick={() => setConfirmDelete(false)} className={`t-btn ${styles.confirmNo}`}>Отмена</button>
        </div>
      )}

      {/* Контекст встречи: чипы, заметки, «Подробнее» */}
      <MeetingContextHeader meeting={meeting} />

      {/* Телефон/планшет: вкладки страницы */}
      {!isWide && (
        <div className={styles.tabs} role="tablist" aria-label="Разделы встречи">
          {PAGE_TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cx('t-btn', styles.tab, tab === key && styles.tabActive)}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      <div className={styles.content}>
        {/* Главное окно: транскрипт / протокол (остаётся смонтированным при смене вкладки страницы) */}
        <div className={cx(styles.mainSlot, !isWide && !mainVisible && styles.mainSlotHidden)}>
          <MeetingMainWindow
            meetingId={meetingId}
            segments={meeting.segments}
            rolesByLabel={rolesByLabel}
            tab={mainTab}
            onTabChange={setTab}
            showSwitch={isWide}
            protocolRefresh={protocolRefresh}
            onRolesChange={setRoles}
            onProtocolRebuild={() => setProtocolRefresh((k) => k + 1)}
          />
        </div>

        {/* Подсказки, усиления, база знаний: на десктопе стопкой слева, на узких — по вкладке */}
        {(isWide || !mainVisible) && (
          <div className={styles.side}>
            {/* Прошлые встречи как контекст — вверху левой колонки, окно справа не сдвигается */}
            {(isWide || tab === 'suggestions') && (
              <PreviousMeetingsContext
                variant="row"
                meetingId={meeting.id}
                currentCustomerId={meeting.customer_id}
                currentObjectId={meeting.object_id}
              />
            )}

            {(isWide || tab === 'suggestions') && (
              <div className={styles.section}>
                <PanelHeader title="Подсказки" meta={suggestions.length} />
                {suggestions.length === 0 ? (
                  <div className={styles.emptyPanel}>Подсказок нет</div>
                ) : (
                  <div className={styles.suggestionList}>
                    {suggestions.map((s) => <SuggestionCard key={s.id} suggestion={s} />)}
                  </div>
                )}
              </div>
            )}

            {(isWide || tab === 'strengthen') && (
              <div className={styles.section}>
                <PanelHeader title="Усиления позиции" meta={strengthens.length} accent="green" />
                {strengthens.length === 0 ? (
                  <div className={styles.emptyPanel}>Усилений нет</div>
                ) : (
                  <div className={styles.suggestionList}>
                    {strengthens.map((s) => <StrengthenCard key={s.id} suggestion={s} />)}
                  </div>
                )}
              </div>
            )}

            {/* Этап 7: кандидаты в базу знаний по этой встрече */}
            {(isWide || tab === 'knowledge') && (
              <div className={styles.section}>
                <PanelHeader title="База знаний по встрече" />
                <div className={styles.knowledgeList}>
                  <LearningCandidates meetingId={meetingId} compact />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
