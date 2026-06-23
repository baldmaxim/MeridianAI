import { useState, useEffect, useCallback } from 'react';
import { theme } from '../styles/theme';
import { getObject } from '../api/objects';
import { listMeetings, deleteMeeting } from '../api/history';
import { paths, navTo } from '../lib/navigation';
import { apiErrorMessage } from '../lib/apiError';
import { meetingDisplayName } from '../lib/meetingName';
import { formatMoscowDateTime } from '../lib/datetime';
import { FIN_LABELS, finBadgeStyle, formatDuration } from '../lib/meetingMeta';
import { useMeetingStore } from '../store/meetingStore';
import { Dropdown } from '../components/common/Dropdown';
import { Modal } from '../components/common/Modal';
import type { ProjectObject, MeetingListItem } from '../types';

interface Props {
  objectId: number;
  onBack: () => void;
  onOpenMeeting: (id: number) => void;       // завершённая встреча → история
  onOpenLiveMeeting: (id: number) => void;   // активная встреча → живая комната
  onNewMeeting: (obj: ProjectObject) => void;
}

export function ObjectDetailPage({ objectId, onBack, onOpenMeeting, onOpenLiveMeeting, onNewMeeting }: Props) {
  const setObjectHeader = useMeetingStore((s) => s.setObjectHeader);
  const [object, setObject] = useState<ProjectObject | null>(null);
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<MeetingListItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) { setLoading(true); setError(''); }
    try {
      const [obj, ms] = await Promise.all([getObject(objectId), listMeetings({ object_id: objectId, include_active: true })]);
      setObject(obj);
      setObjectHeader({ customer: obj.customer_name, object: obj.name });
      setMeetings(ms);
    } catch (e) {
      if (!silent) setError(apiErrorMessage(e, 'Не удалось загрузить объект'));
    } finally {
      if (!silent) setLoading(false);
    }
  }, [objectId, setObjectHeader]);

  useEffect(() => { load(); }, [load]);

  // Шапка показывает «Заказчик | Объект» только пока открыта эта страница;
  // при смене объекта/уходе — чистим, чтобы не мигали данные прошлого объекта.
  useEffect(() => {
    setObjectHeader(null);
    return () => setObjectHeader(null);
  }, [objectId, setObjectHeader]);

  // Пока есть активная встреча — тихо обновляем список, чтобы статус «активна»/REC были live.
  const hasActive = meetings.some((m) => m.status === 'active');
  useEffect(() => {
    if (!hasActive) return;
    const iv = setInterval(() => load(true), 5000);
    return () => clearInterval(iv);
  }, [hasActive, load]);

  const copyLink = (id: number) => {
    const url = window.location.origin + paths.meetingRoom(id);
    navigator.clipboard?.writeText(url);
    setCopiedId(id);
    setTimeout(() => setCopiedId((c) => (c === id ? null : c)), 1500);
  };

  const doDelete = useCallback(async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await deleteMeeting(confirmDelete.id);
      setMeetings((ms) => ms.filter((x) => x.id !== confirmDelete.id));
      setConfirmDelete(null);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось удалить встречу'));
    } finally {
      setDeleting(false);
    }
  }, [confirmDelete]);

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button onClick={onBack} style={styles.backBtn} className="od-backBtn t-btn" aria-label="К объектам" title="К объектам">
          <span>&larr;</span><span className="od-btn-label"> К объектам</span>
        </button>
        <div style={styles.titleWrap}>
          <span style={styles.topTitle}>{object?.name || 'ОБЪЕКТ'}</span>
          {object && (object.address || object.description) && (
            <div style={styles.infoWrap}>
              <button
                type="button"
                className="t-btn"
                style={styles.infoBtn}
                onClick={() => setInfoOpen((v) => !v)}
                aria-label="Информация об объекте"
                title="Информация об объекте"
              >ⓘ инфо</button>
              <Dropdown open={infoOpen} onClose={() => setInfoOpen(false)} origin="top-left" style={styles.infoMenu}>
                {object.customer_name && (
                  <div style={styles.infoRow}><span style={styles.infoLabel}>Заказчик</span><span style={styles.infoVal}>{object.customer_name}</span></div>
                )}
                {object.address && (
                  <div style={styles.infoRow}><span style={styles.infoLabel}>Адрес</span><span style={styles.infoVal}>{object.address}</span></div>
                )}
                {object.description && (
                  <div style={styles.infoRow}><span style={styles.infoLabel}>Описание</span><span style={styles.infoVal}>{object.description}</span></div>
                )}
              </Dropdown>
            </div>
          )}
        </div>
        {object && (
          <button style={styles.newBtn} className="od-newBtn t-btn t-btn-amber" onClick={() => onNewMeeting(object)} aria-label="Новая встреча" title="Новая встреча">
            <span>+</span><span className="od-btn-label"> Новая встреча</span>
          </button>
        )}
      </div>

      <style>{`
        @media (max-width: 767px) {
          .od-btn-label { display: none !important; }
          .od-backBtn { padding: 8px 12px !important; font-size: 16px !important; }
          .od-newBtn { padding: 8px 14px !important; font-size: 18px !important; line-height: 1 !important; }
        }
      `}</style>

      {loading && <div style={styles.muted}>Загрузка…</div>}
      {error && <div style={styles.error}>{error}</div>}

      {object && (
        <div style={styles.sectionTitle}>Встречи ({meetings.length})</div>
      )}

      {!loading && object && meetings.length === 0 && (
        <div style={styles.muted}>По объекту ещё нет встреч. Создайте первую — «+ Новая встреча».</div>
      )}

      <div style={styles.list}>
        {meetings.map((m) => {
          const isActive = m.status === 'active';
          const openRow = () => (isActive ? onOpenLiveMeeting(m.id) : onOpenMeeting(m.id));
          const href = isActive ? paths.meetingRoom(m.id) : paths.meetingDetail(m.id, 'object', objectId);
          const dur = formatDuration(m.recorded_seconds);
          return (
            <div
              key={m.id}
              style={styles.card}
              role="button"
              tabIndex={0}
              {...navTo(href, openRow)}
              onKeyDown={(e) => { if (e.key === 'Enter') openRow(); }}
            >
              <div style={styles.cardTop}>
                <div style={styles.cardTitle}>{meetingDisplayName(m)}</div>
                <div style={styles.cardDate}>{formatMoscowDateTime(m.started_at)}</div>
              </div>
              {(m.micro_summary || m.meeting_topic) && (
                <div style={styles.cardSummary}>{m.micro_summary || m.meeting_topic}</div>
              )}
              <div style={styles.cardFoot}>
                <div style={styles.statusWrap}>
                  {m.is_recording ? (
                    <span style={styles.recBadge}>
                      <span className="pulse-dot" style={styles.recDot} /> REC
                    </span>
                  ) : isActive ? (
                    <span style={styles.activeBadge}>
                      <span style={styles.activeDot} /> активна
                    </span>
                  ) : (
                    m.status && <span style={styles.badge}>{m.status}</span>
                  )}
                  {m.finalization_status && m.finalization_status !== 'not_started' && (
                    <span style={finBadgeStyle(m.finalization_status)}>{FIN_LABELS[m.finalization_status] || m.finalization_status}</span>
                  )}
                  {dur !== '--' && <span style={styles.badge}>{dur}</span>}
                  {m.suggestion_count > 0 && <span style={styles.badge}>{m.suggestion_count} подсказок</span>}
                  {m.tags && m.tags.length > 0 && m.tags.map((t) => (
                    <span key={t} style={styles.tagBadge}>#{t}</span>
                  ))}
                </div>
                <div style={styles.actions}>
                  {isActive && (
                    <button
                      className="t-btn"
                      style={styles.linkBtn}
                      onClick={(e) => { e.stopPropagation(); copyLink(m.id); }}
                      onAuxClick={(e) => e.stopPropagation()}
                      title="Скопировать ссылку на встречу"
                    >
                      {copiedId === m.id ? '✓ скопировано' : '🔗 ссылка'}
                    </button>
                  )}
                  <div style={styles.menuWrap}>
                    <button
                      className="t-btn"
                      style={styles.menuBtn}
                      onClick={(e) => { e.stopPropagation(); setMenuFor((v) => (v === m.id ? null : m.id)); }}
                      onAuxClick={(e) => e.stopPropagation()}
                      aria-label="Действия со встречей"
                    >⋮</button>
                    <Dropdown
                      open={menuFor === m.id}
                      onClose={() => setMenuFor(null)}
                      origin="top-right"
                      style={styles.menu}
                    >
                      <button
                        className="t-btn t-btn-red"
                        style={styles.menuItemDanger}
                        onClick={(e) => { e.stopPropagation(); setMenuFor(null); setConfirmDelete(m); }}
                      >Удалить встречу</button>
                    </Dropdown>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <Modal open={confirmDelete != null} onClose={() => { if (!deleting) setConfirmDelete(null); }} maxWidth={420}>
        <div style={styles.modalTitle}>Удалить встречу?</div>
        <div style={styles.modalText}>
          «{confirmDelete?.title || confirmDelete?.meeting_topic || 'Без названия'}» будет удалена со всеми
          транскриптами и подсказками. Действие необратимо.
        </div>
        <div style={styles.modalActions}>
          <button className="t-btn" style={styles.cancelBtn} onClick={() => setConfirmDelete(null)} disabled={deleting}>Отмена</button>
          <button className="t-btn t-btn-red" style={styles.deleteBtn} onClick={doDelete} disabled={deleting}>{deleting ? 'Удаление…' : 'Удалить'}</button>
        </div>
      </Modal>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', flex: 1, overflow: 'auto', padding: '20px 24px', gap: 14 },
  topBar: {
    display: 'flex', alignItems: 'center', gap: 16, paddingBottom: 12,
    borderBottom: `1px solid ${theme.border.default}`, flexShrink: 0, flexWrap: 'wrap' as const,
  },
  backBtn: {
    display: 'flex', alignItems: 'center', gap: 6, padding: '6px 16px',
    background: 'transparent', border: `1px solid ${theme.accent.amber}`, borderRadius: 6,
    color: theme.accent.amber, cursor: 'pointer', fontSize: 12,
    fontFamily: theme.font.mono, fontWeight: 500, letterSpacing: '0.04em', flexShrink: 0,
  },
  titleWrap: { display: 'flex', alignItems: 'center', gap: 10, flex: 1, minWidth: 0 },
  topTitle: {
    fontFamily: theme.font.body, fontSize: 15, fontWeight: 700,
    letterSpacing: '0.04em', color: theme.text.primary, flex: '0 1 auto', minWidth: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  infoWrap: { position: 'relative' as const, flexShrink: 0 },
  infoBtn: {
    padding: '4px 10px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 6, color: theme.text.secondary, cursor: 'pointer',
    fontFamily: theme.font.mono, fontSize: 10, fontWeight: 500, whiteSpace: 'nowrap' as const,
  },
  infoMenu: {
    position: 'absolute' as const, top: 32, left: 0, zIndex: 60, minWidth: 240, maxWidth: 360,
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, borderRadius: 8,
    padding: 12, boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
    display: 'flex', flexDirection: 'column', gap: 10,
  },
  newBtn: {
    padding: '8px 18px', background: theme.accent.amber, border: 'none', borderRadius: 8,
    color: '#080A0F', cursor: 'pointer', fontSize: 13, fontWeight: 600,
    fontFamily: theme.font.body, whiteSpace: 'nowrap',
  },
  infoRow: { display: 'flex', flexDirection: 'column', gap: 2 },
  infoLabel: {
    fontFamily: theme.font.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.1em',
    textTransform: 'uppercase' as const, color: theme.text.muted,
  },
  infoVal: { fontFamily: theme.font.body, fontSize: 13, color: theme.text.primary, whiteSpace: 'pre-wrap' as const },
  sectionTitle: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 12,
    letterSpacing: '0.1em', textTransform: 'uppercase' as const, color: theme.text.secondary, marginTop: 4,
  },
  list: { display: 'flex', flexDirection: 'column', gap: 10 },
  card: {
    display: 'flex', flexDirection: 'column', gap: 6, padding: 14, textAlign: 'left' as const,
    background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12,
    color: theme.text.primary, cursor: 'pointer', fontFamily: theme.font.body,
  },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10 },
  cardTitle: {
    fontFamily: theme.font.body, fontWeight: 700, fontSize: 14, flex: 1, minWidth: 0,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  cardDate: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, flexShrink: 0 },
  cardSummary: {
    fontSize: 12, color: theme.text.secondary, overflow: 'hidden', textOverflow: 'ellipsis',
    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const,
  },
  cardFoot: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
    flexWrap: 'wrap' as const, marginTop: 2,
  },
  statusWrap: { display: 'flex', gap: 6, flexWrap: 'wrap' as const, alignItems: 'center' },
  actions: { display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 },
  badge: {
    padding: '2px 8px', background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`,
    borderRadius: 4, fontFamily: theme.font.mono, fontSize: 9, color: theme.text.muted, textTransform: 'uppercase' as const,
  },
  tagBadge: {
    padding: '2px 8px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 4, fontFamily: theme.font.mono, fontSize: 9, color: theme.accent.amber,
  },
  activeBadge: {
    display: 'flex', alignItems: 'center', gap: 5, padding: '2px 9px',
    background: 'rgba(46,229,157,0.1)', border: '1px solid rgba(46,229,157,0.3)', borderRadius: 12,
    fontFamily: theme.font.mono, fontSize: 9, fontWeight: 600, letterSpacing: '0.06em',
    color: theme.accent.green, textTransform: 'uppercase' as const,
  },
  activeDot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.green, flexShrink: 0 },
  recBadge: {
    display: 'flex', alignItems: 'center', gap: 5, padding: '2px 9px',
    background: 'rgba(255,75,110,0.12)', border: '1px solid rgba(255,75,110,0.35)', borderRadius: 12,
    fontFamily: theme.font.mono, fontSize: 9, fontWeight: 700, letterSpacing: '0.1em',
    color: theme.accent.red, textTransform: 'uppercase' as const,
  },
  recDot: { width: 6, height: 6, borderRadius: '50%', background: theme.accent.red, flexShrink: 0 },
  linkBtn: {
    padding: '4px 10px', background: 'transparent', border: `1px solid ${theme.border.amber}`,
    borderRadius: 6, color: theme.accent.amber, cursor: 'pointer',
    fontFamily: theme.font.mono, fontSize: 10, fontWeight: 500, whiteSpace: 'nowrap' as const,
  },
  menuWrap: { position: 'relative' as const, flexShrink: 0 },
  menuBtn: {
    width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'transparent', border: `1px solid ${theme.border.default}`, borderRadius: 6,
    color: theme.text.secondary, cursor: 'pointer', fontSize: 16, lineHeight: 1,
  },
  menu: {
    position: 'absolute' as const, top: 32, right: 0, zIndex: 60, minWidth: 180,
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, borderRadius: 8,
    padding: 6, boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
  },
  menuItemDanger: {
    width: '100%', textAlign: 'left' as const, padding: '9px 12px',
    background: 'transparent', border: 'none', borderRadius: 6,
    color: theme.accent.red, cursor: 'pointer', fontSize: 13, fontFamily: theme.font.body,
  },
  modalTitle: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 16, color: theme.text.primary,
  },
  modalText: { fontFamily: theme.font.body, fontSize: 13, color: theme.text.secondary, lineHeight: 1.5 },
  modalActions: { display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 },
  cancelBtn: {
    padding: '8px 16px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 8, color: theme.text.secondary, cursor: 'pointer', fontSize: 13, fontFamily: theme.font.body,
  },
  deleteBtn: {
    padding: '8px 18px', background: theme.accent.red, border: 'none', borderRadius: 8,
    color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: theme.font.body,
  },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 13, padding: '12px 0' },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 13, padding: '8px 0' },
};
