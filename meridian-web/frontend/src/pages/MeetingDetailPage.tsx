import { useState, useEffect } from 'react';
import { theme } from '../styles/theme';
import { ProtocolSection } from '../components/protocol/ProtocolSection';
import { LearningCandidates } from '../components/learning/LearningCandidates';
import { PreviousMeetingsContext } from '../components/context/PreviousMeetingsContext';
import { getMeetingDetail, updateMeetingTitle, deleteMeeting, continueMeeting } from '../api/history';
import type { MeetingDetail, MeetingSuggestionRecord, TranscriptSegmentRecord } from '../types';

interface Props {
  meetingId: number;
  onBack: () => void;
  onContinue: () => void;
  backLabel?: string;
}

const NEGOTIATION_TYPE_LABELS: Record<string, string> = {
  sale: 'Продажа',
  claim: 'Претензия',
  negotiation: 'Переговоры',
};

const SUGGESTION_TYPE_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  priority: { label: 'ПРИОРИТЕТ', color: '#F5A623', bg: 'rgba(245,166,35,0.12)' },
  counter: { label: 'КОНТРАРГУМЕНТ', color: '#5B9CF6', bg: 'rgba(91,156,246,0.12)' },
  question: { label: 'ВОПРОС', color: '#2EE59D', bg: 'rgba(46,229,157,0.12)' },
  risk: { label: 'РИСК', color: '#FF4B6E', bg: 'rgba(255,75,110,0.12)' },
};

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
    + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

// Длительность = суммарное время записи (диктофон), не время открытой сессии.
function formatRecorded(recordedSeconds: number | null | undefined): string | null {
  if (!recordedSeconds || recordedSeconds <= 0) return null;
  const min = Math.floor(recordedSeconds / 60);
  if (min < 1) return `${recordedSeconds} сек записи`;
  if (min < 60) return `${min} мин записи`;
  return `${Math.floor(min / 60)}ч ${min % 60}м записи`;
}

function getSpeakerColor(speaker: string): string {
  const colors = ['#5B9CF6', '#2EE59D', '#F5A623', '#FF4B6E', '#8896B3'];
  let hash = 0;
  for (let i = 0; i < speaker.length; i++) hash = speaker.charCodeAt(i) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}

export function MeetingDetailPage({ meetingId, onBack, onContinue, backLabel = 'К истории' }: Props) {
  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [mobileTab, setMobileTab] = useState<'transcript' | 'suggestions' | 'context'>('transcript');
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    loadMeeting();
  }, [meetingId]);

  async function loadMeeting() {
    try {
      setLoading(true);
      const data = await getMeetingDetail(meetingId);
      setMeeting(data);
      setTitleDraft(data.title || '');
    } catch {
      setError('Ошибка загрузки встречи');
    } finally {
      setLoading(false);
    }
  }

  async function saveTitle() {
    if (!meeting || !titleDraft.trim()) return;
    try {
      await updateMeetingTitle(meetingId, titleDraft.trim());
      setMeeting({ ...meeting, title: titleDraft.trim() });
      setEditingTitle(false);
    } catch { /* ignore */ }
  }

  async function handleDelete() {
    try {
      await deleteMeeting(meetingId);
      onBack();
    } catch { /* ignore */ }
  }

  async function handleContinue() {
    try {
      await continueMeeting(meetingId);
      onContinue();
    } catch { /* ignore */ }
  }

  if (loading) return <div style={styles.loading}>Загрузка...</div>;
  if (error || !meeting) return <div style={{ ...styles.loading, color: theme.accent.red }}>{error || 'Не найдено'}</div>;

  const suggestions = meeting.suggestions.filter(s => s.source === 'suggestion');
  const strengthens = meeting.suggestions.filter(s => s.source === 'strengthen');

  return (
    <div className="detail-container" style={styles.container}>
      {/* Top bar */}
      <div style={styles.topBar}>
        <button onClick={onBack} style={styles.backBtn}>&larr; {backLabel}</button>
        <span style={styles.topTitle}>ДЕТАЛИ ВСТРЕЧИ</span>
        <button onClick={handleContinue} style={styles.continueBtn}>
          Продолжить
        </button>
        <button
          onClick={() => setConfirmDelete(true)}
          style={styles.deleteBtn}
        >
          Удалить
        </button>
      </div>

      {/* Delete confirm */}
      {confirmDelete && (
        <div style={styles.confirmBar}>
          <span style={{ color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 12 }}>
            Удалить встречу и все данные?
          </span>
          <button onClick={handleDelete} style={styles.confirmYes}>Да, удалить</button>
          <button onClick={() => setConfirmDelete(false)} style={styles.confirmNo}>Отмена</button>
        </div>
      )}

      {/* Title */}
      <div style={styles.titleRow}>
        {editingTitle ? (
          <input
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={(e) => e.key === 'Enter' && saveTitle()}
            autoFocus
            style={styles.titleInput}
          />
        ) : (
          <h2 style={styles.title} onClick={() => setEditingTitle(true)}>
            {meeting.title || 'Без названия'}
          </h2>
        )}
        <div style={styles.titleMeta}>
          {formatDateTime(meeting.started_at)}
          {meeting.ended_at && ` — ${formatTime(meeting.ended_at)}`}
          {formatRecorded(meeting.recorded_seconds) && ` · ${formatRecorded(meeting.recorded_seconds)}`}
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
      <div style={{ ...styles.section, padding: '12px 16px' }}>
        <div style={{ ...styles.panelHeader, padding: 0, border: 'none', marginBottom: 10 }}>
          <span style={styles.dot} />
          <span style={styles.panelTitle}>База знаний по встрече</span>
        </div>
        <LearningCandidates meetingId={meetingId} compact />
      </div>

      {/* Mobile tabs */}
      <div className="detail-mobile-tabs" style={styles.mobileTabs}>
        {(['transcript', 'suggestions', 'context'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setMobileTab(tab)}
            style={mobileTab === tab ? styles.mobileTabActive : styles.mobileTab}
          >
            {tab === 'transcript' ? 'Транскрипция' : tab === 'suggestions' ? 'Подсказки' : 'Контекст'}
          </button>
        ))}
      </div>

      {/* Two-panel layout */}
      <div className="detail-panels" style={styles.panels}>
        {/* Left: Transcript */}
        <div
          className={`detail-left ${mobileTab !== 'transcript' ? 'detail-hide-mobile' : ''}`}
          style={{
            ...styles.leftPanel,
            display: 'flex',
          }}
        >
          <div style={styles.panelHeader}>
            <span style={styles.dot} />
            <span style={styles.panelTitle}>Транскрипция</span>
            <span style={styles.panelMeta}>{meeting.segments.length} сегментов</span>
          </div>
          <div style={styles.transcriptList}>
            {meeting.segments.length === 0 && (
              <div style={styles.emptyPanel}>Нет данных транскрипции</div>
            )}
            {meeting.segments.map((seg, i) => (
              <TranscriptRow key={seg.segment_id || i} segment={seg} />
            ))}
          </div>
        </div>

        {/* Right: Suggestions + Context */}
        <div className={`detail-right ${mobileTab === 'transcript' ? 'detail-hide-mobile' : ''}`} style={styles.rightPanel}>
          {/* Context section */}
          <div className={mobileTab === 'suggestions' ? 'detail-hide-mobile' : ''} style={styles.section}>
            <div style={styles.panelHeader}>
              <span style={styles.dot} />
              <span style={styles.panelTitle}>Контекст</span>
            </div>
            <ContextBlock meeting={meeting} />
          </div>

          {/* Suggestions */}
          {suggestions.length > 0 && (
            <div className={mobileTab === 'context' ? 'detail-hide-mobile' : ''} style={styles.section}>
              <div style={styles.panelHeader}>
                <span style={styles.dot} />
                <span style={styles.panelTitle}>Подсказки</span>
                <span style={styles.panelMeta}>{suggestions.length}</span>
              </div>
              <div style={styles.suggestionList}>
                {suggestions.map((s) => (
                  <SuggestionCard key={s.id} suggestion={s} />
                ))}
              </div>
            </div>
          )}

          {/* Strengthen */}
          {strengthens.length > 0 && (
            <div className={mobileTab === 'context' ? 'detail-hide-mobile' : ''} style={styles.section}>
              <div style={styles.panelHeader}>
                <span style={{ ...styles.dot, background: theme.accent.green }} />
                <span style={styles.panelTitle}>Усиления позиции</span>
                <span style={styles.panelMeta}>{strengthens.length}</span>
              </div>
              <div style={styles.suggestionList}>
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
}

function TranscriptRow({ segment }: { segment: TranscriptSegmentRecord }) {
  const speaker = segment.speaker_label || segment.speaker_id;
  const color = getSpeakerColor(speaker);
  return (
    <div style={styles.transcriptRow}>
      <span style={styles.transcriptTime}>{formatTime(segment.wall_clock)}</span>
      <span style={{ ...styles.transcriptSpeaker, color }}>{speaker}</span>
      <span style={styles.transcriptText}>{segment.text}</span>
    </div>
  );
}

function getDocColor(ext: string): string {
  switch (ext.toUpperCase()) {
    case 'PDF': return '#FF4B6E';
    case 'DOCX': return '#5B9CF6';
    case 'XLSX': return '#2EE59D';
    default: return '#8896B3';
  }
}

function ContextBlock({ meeting }: { meeting: MeetingDetail }) {
  const fields = [
    { label: 'Тема', value: meeting.meeting_topic },
    { label: 'Тип переговоров', value: meeting.negotiation_type ? (NEGOTIATION_TYPE_LABELS[meeting.negotiation_type] || meeting.negotiation_type) : null },
    { label: 'Роль', value: meeting.meeting_role },
    { label: 'Заметки', value: meeting.meeting_notes },
    { label: 'Слабости оппонента', value: meeting.opponent_weaknesses },
  ].filter(f => f.value);

  const docs = meeting.documents || [];
  const hasContent = fields.length > 0 || docs.length > 0;

  if (!hasContent) {
    return <div style={styles.emptyPanel}>Контекст не заполнен</div>;
  }

  return (
    <div style={styles.contextFields}>
      {fields.map((f, i) => (
        <div key={i} style={styles.contextField}>
          <div style={styles.contextLabel}>{f.label}</div>
          <div style={styles.contextValue}>{f.value}</div>
        </div>
      ))}
      {docs.length > 0 && (
        <div style={styles.contextField}>
          <div style={styles.contextLabel}>Документы</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {docs.map((doc) => {
              const ext = doc.filename.split('.').pop() || '';
              const color = getDocColor(ext);
              const extLower = ext.toLowerCase();
              const countLabel = extLower === 'xlsx' ? `${doc.page_count} лист.`
                : ['txt', 'md'].includes(extLower) ? '' : `${doc.page_count} стр.`;
              return (
                <div key={doc.filename} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '6px 10px',
                  background: theme.bg.tertiary,
                  border: `1px solid ${theme.border.default}`,
                  borderRadius: 6,
                }}>
                  <span style={{
                    fontSize: 9,
                    fontFamily: theme.font.mono,
                    fontWeight: 700,
                    color,
                    minWidth: 30,
                  }}>
                    {ext.toUpperCase()}
                  </span>
                  <span style={{
                    fontSize: 12,
                    fontFamily: theme.font.body,
                    color: theme.text.primary,
                    flex: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {doc.filename}
                  </span>
                  <span style={{
                    fontSize: 9,
                    fontFamily: theme.font.mono,
                    color: theme.text.muted,
                  }}>
                    {doc.doc_type_label}{countLabel ? ` · ${countLabel}` : ''}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function SuggestionCard({ suggestion }: { suggestion: MeetingSuggestionRecord }) {
  const typeInfo = suggestion.suggestion_type
    ? (SUGGESTION_TYPE_LABELS[suggestion.suggestion_type]
       || { label: suggestion.suggestion_type.toUpperCase(), color: '#8896B3', bg: 'rgba(136,150,179,0.12)' })
    : null;

  return (
    <div style={styles.suggestionCard}>
      <div style={styles.suggestionTop}>
        {typeInfo && (
          <span style={{
            ...styles.typeBadge,
            color: typeInfo.color,
            background: typeInfo.bg,
            borderColor: typeInfo.color,
          }}>
            {typeInfo.label}
          </span>
        )}
        {suggestion.is_auto && <span style={styles.autoBadge}>АВТО</span>}
        <span style={styles.suggestionTime}>{formatTime(suggestion.created_at)}</span>
      </div>
      <div style={styles.suggestionText}>{suggestion.text}</div>
      {(suggestion.trigger || suggestion.context_info) && (
        <div style={styles.suggestionMeta}>
          {suggestion.trigger && <span>Триггер: {suggestion.trigger}</span>}
          {suggestion.context_info && <span>{suggestion.context_info}</span>}
        </div>
      )}
    </div>
  );
}

function StrengthenCard({ suggestion }: { suggestion: MeetingSuggestionRecord }) {
  return (
    <div style={{ ...styles.suggestionCard, borderLeft: `2px solid ${theme.accent.green}` }}>
      <div style={styles.suggestionTop}>
        <span style={{
          ...styles.typeBadge,
          color: theme.accent.green,
          background: theme.accent.greenDim,
          borderColor: theme.accent.green,
        }}>
          УСИЛЕНИЕ
        </span>
        <span style={styles.suggestionTime}>{formatTime(suggestion.created_at)}</span>
      </div>
      <div style={{ ...styles.suggestionText, whiteSpace: 'pre-wrap' }}>{suggestion.text}</div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '20px 24px',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
    overflow: 'hidden',
    flex: 1,
  },
  loading: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    color: theme.text.secondary,
    fontFamily: theme.font.mono,
    fontSize: 13,
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    paddingBottom: 12,
    borderBottom: `1px solid ${theme.border.default}`,
    flexShrink: 0,
  },
  backBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '6px 16px',
    background: 'transparent',
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 6,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 12,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.04em',
    flexShrink: 0,
  },
  topTitle: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    fontWeight: 500,
    letterSpacing: '0.16em',
    color: theme.text.secondary,
    flex: 1,
  },
  continueBtn: {
    padding: '4px 12px',
    background: theme.accent.amberGlow,
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 5,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.06em',
  },
  deleteBtn: {
    padding: '4px 12px',
    background: 'transparent',
    border: `1px solid ${theme.accent.red}`,
    borderRadius: 5,
    color: theme.accent.red,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    fontWeight: 500,
    letterSpacing: '0.06em',
  },
  confirmBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '8px 16px',
    background: 'rgba(255,75,110,0.08)',
    border: `1px solid rgba(255,75,110,0.2)`,
    borderRadius: 8,
    flexShrink: 0,
  },
  confirmYes: {
    padding: '4px 14px',
    background: theme.accent.red,
    border: 'none',
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.mono,
    fontWeight: 600,
  },
  confirmNo: {
    padding: '4px 14px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 4,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.mono,
  },
  titleRow: {
    flexShrink: 0,
  },
  title: {
    margin: 0,
    fontSize: 22,
    fontFamily: theme.font.body,
    fontWeight: 700,
    color: theme.text.primary,
    cursor: 'pointer',
  },
  titleInput: {
    fontSize: 22,
    fontFamily: theme.font.body,
    fontWeight: 700,
    color: theme.text.primary,
    background: theme.bg.input,
    border: `1px solid ${theme.border.focus}`,
    borderRadius: 6,
    padding: '4px 10px',
    width: '100%',
    outline: 'none',
  },
  titleMeta: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.text.muted,
    marginTop: 4,
  },
  mobileTabs: {
    display: 'none',
    gap: 4,
    flexShrink: 0,
  },
  mobileTab: {
    flex: 1,
    padding: '8px 0',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 6,
    color: theme.text.secondary,
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.mono,
    fontWeight: 500,
  },
  mobileTabActive: {
    flex: 1,
    padding: '8px 0',
    background: theme.accent.amberGlow,
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 6,
    color: theme.accent.amber,
    cursor: 'pointer',
    fontSize: 11,
    fontFamily: theme.font.mono,
    fontWeight: 600,
  },
  panels: {
    display: 'flex',
    gap: 16,
    flex: 1,
    overflow: 'hidden',
    minHeight: 0,
  },
  leftPanel: {
    flex: 3,
    flexDirection: 'column',
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 10,
    overflow: 'hidden',
  },
  rightPanel: {
    flex: 2,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    overflow: 'auto',
    minWidth: 280,
  },
  panelHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '12px 16px',
    borderBottom: `1px solid ${theme.border.default}`,
    flexShrink: 0,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent.amber,
    flexShrink: 0,
  },
  panelTitle: {
    fontFamily: theme.font.heading,
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: '0.12em',
    textTransform: 'uppercase' as const,
    color: theme.text.primary,
    flex: 1,
  },
  panelMeta: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
  },
  transcriptList: {
    flex: 1,
    overflow: 'auto',
    padding: '8px 0',
  },
  transcriptRow: {
    display: 'flex',
    gap: 8,
    padding: '4px 16px',
    alignItems: 'baseline',
    fontSize: 13,
    lineHeight: '1.5',
  },
  transcriptTime: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
    flexShrink: 0,
    width: 60,
  },
  transcriptSpeaker: {
    fontFamily: theme.font.mono,
    fontSize: 11,
    fontWeight: 600,
    flexShrink: 0,
    width: 100,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  transcriptText: {
    fontFamily: theme.font.body,
    color: theme.text.primary,
    flex: 1,
  },
  section: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 10,
    overflow: 'hidden',
  },
  contextFields: {
    padding: '12px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  contextField: {},
  contextLabel: {
    fontFamily: theme.font.mono,
    fontSize: 9,
    fontWeight: 600,
    letterSpacing: '0.1em',
    textTransform: 'uppercase' as const,
    color: theme.text.muted,
    marginBottom: 2,
  },
  contextValue: {
    fontFamily: theme.font.body,
    fontSize: 13,
    color: theme.text.primary,
    whiteSpace: 'pre-wrap',
  },
  emptyPanel: {
    padding: '20px 16px',
    textAlign: 'center',
    fontFamily: theme.font.mono,
    fontSize: 11,
    color: theme.text.muted,
  },
  suggestionList: {
    padding: '8px 12px',
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  suggestionCard: {
    padding: '10px 14px',
    background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 8,
  },
  suggestionTop: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 6,
  },
  typeBadge: {
    padding: '1px 6px',
    borderRadius: 3,
    fontSize: 8,
    fontFamily: theme.font.mono,
    fontWeight: 700,
    letterSpacing: '0.08em',
    border: '1px solid',
  },
  autoBadge: {
    padding: '1px 6px',
    background: 'rgba(91,156,246,0.1)',
    border: '1px solid rgba(91,156,246,0.25)',
    borderRadius: 3,
    fontSize: 8,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    color: theme.accent.blue,
    letterSpacing: '0.08em',
  },
  suggestionTime: {
    fontFamily: theme.font.mono,
    fontSize: 9,
    color: theme.text.muted,
    marginLeft: 'auto',
  },
  suggestionText: {
    fontFamily: theme.font.body,
    fontSize: 12,
    color: theme.text.primary,
    lineHeight: '1.5',
  },
  suggestionMeta: {
    display: 'flex',
    gap: 12,
    marginTop: 6,
    fontFamily: theme.font.mono,
    fontSize: 9,
    color: theme.text.muted,
  },
};
