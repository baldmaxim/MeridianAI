import { useState, useEffect, useCallback } from 'react';
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
import styles from './ObjectDetailPage.module.css';
import { cx } from '../utils/cx';

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
    <div className={styles.container}>
      <div className={styles.topBar}>
        <button onClick={onBack} className={cx('t-btn', styles.backBtn)} aria-label="К объектам" title="К объектам">
          <span>&larr;</span><span className={styles.btnLabel}> К объектам</span>
        </button>
        <div className={styles.titleWrap}>
          <span className={styles.topTitle}>{object?.name || 'ОБЪЕКТ'}</span>
          {object && (object.address || object.description) && (
            <div className={styles.infoWrap}>
              <button
                type="button"
                className={cx('t-btn', styles.infoBtn)}
                onClick={() => setInfoOpen((v) => !v)}
                aria-label="Информация об объекте"
                title="Информация об объекте"
              >ⓘ инфо</button>
              <Dropdown open={infoOpen} onClose={() => setInfoOpen(false)} origin="top-left" className={styles.infoMenu}>
                {object.customer_name && (
                  <div className={styles.infoRow}><span className={styles.infoLabel}>Заказчик</span><span className={styles.infoVal}>{object.customer_name}</span></div>
                )}
                {object.address && (
                  <div className={styles.infoRow}><span className={styles.infoLabel}>Адрес</span><span className={styles.infoVal}>{object.address}</span></div>
                )}
                {object.description && (
                  <div className={styles.infoRow}><span className={styles.infoLabel}>Описание</span><span className={styles.infoVal}>{object.description}</span></div>
                )}
              </Dropdown>
            </div>
          )}
        </div>
        {object && (
          <button className={cx('t-btn t-btn-amber', styles.newBtn)} onClick={() => onNewMeeting(object)} aria-label="Новая встреча" title="Новая встреча">
            <span>+</span><span className={styles.btnLabel}> Новая встреча</span>
          </button>
        )}
      </div>

      {loading && <div className={styles.muted}>Загрузка…</div>}
      {error && <div className={styles.error}>{error}</div>}

      {object && (
        <div className={styles.sectionTitle}>Встречи ({meetings.length})</div>
      )}

      {!loading && object && meetings.length === 0 && (
        <div className={styles.muted}>По объекту ещё нет встреч. Создайте первую — «+ Новая встреча».</div>
      )}

      <div className={styles.list}>
        {meetings.map((m) => {
          const isActive = m.status === 'active';
          const openRow = () => (isActive ? onOpenLiveMeeting(m.id) : onOpenMeeting(m.id));
          const href = isActive ? paths.meetingRoom(m.id) : paths.meetingDetail(m.id, 'object', objectId);
          const dur = formatDuration(m.recorded_seconds);
          return (
            <div
              key={m.id}
              className={styles.card}
              role="button"
              tabIndex={0}
              {...navTo(href, openRow)}
              onKeyDown={(e) => { if (e.key === 'Enter') openRow(); }}
            >
              <div className={styles.cardTop}>
                <div className={styles.cardTitle}>{meetingDisplayName(m)}</div>
                <div className={styles.cardDate}>{formatMoscowDateTime(m.started_at)}</div>
              </div>
              {(m.micro_summary || m.meeting_topic) && (
                <div className={styles.cardSummary}>{m.micro_summary || m.meeting_topic}</div>
              )}
              <div className={styles.cardFoot}>
                <div className={styles.statusWrap}>
                  {m.is_recording ? (
                    <span className={styles.recBadge}>
                      <span className={cx('pulse-dot', styles.recDot)} /> REC
                    </span>
                  ) : isActive ? (
                    <span className={styles.activeBadge}>
                      <span className={styles.activeDot} /> активна
                    </span>
                  ) : (
                    m.status && <span className={styles.badge}>{m.status}</span>
                  )}
                  {m.finalization_status && m.finalization_status !== 'not_started' && (
                    <span style={finBadgeStyle(m.finalization_status)}>{FIN_LABELS[m.finalization_status] || m.finalization_status}</span>
                  )}
                  {dur !== '--' && <span className={styles.badge}>{dur}</span>}
                  {m.suggestion_count > 0 && <span className={styles.badge}>{m.suggestion_count} подсказок</span>}
                  {m.tags && m.tags.length > 0 && m.tags.map((t) => (
                    <span key={t} className={styles.tagBadge}>#{t}</span>
                  ))}
                </div>
                <div className={styles.actions}>
                  {isActive && (
                    <button
                      className={cx('t-btn', styles.linkBtn)}
                      onClick={(e) => { e.stopPropagation(); copyLink(m.id); }}
                      onAuxClick={(e) => e.stopPropagation()}
                      title="Скопировать ссылку на встречу"
                    >
                      {copiedId === m.id ? '✓ скопировано' : '🔗 ссылка'}
                    </button>
                  )}
                  <div className={styles.menuWrap}>
                    <button
                      className={cx('t-btn', styles.menuBtn)}
                      onClick={(e) => { e.stopPropagation(); setMenuFor((v) => (v === m.id ? null : m.id)); }}
                      onAuxClick={(e) => e.stopPropagation()}
                      aria-label="Действия со встречей"
                    >⋮</button>
                    <Dropdown
                      open={menuFor === m.id}
                      onClose={() => setMenuFor(null)}
                      origin="top-right"
                      className={styles.menu}
                    >
                      <button
                        className={cx('t-btn t-btn-red', styles.menuItemDanger)}
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
        <div className={styles.modalTitle}>Удалить встречу?</div>
        <div className={styles.modalText}>
          «{confirmDelete?.title || confirmDelete?.meeting_topic || 'Без названия'}» будет удалена со всеми
          транскриптами и подсказками. Действие необратимо.
        </div>
        <div className={styles.modalActions}>
          <button className={cx('t-btn', styles.cancelBtn)} onClick={() => setConfirmDelete(null)} disabled={deleting}>Отмена</button>
          <button className={cx('t-btn t-btn-red', styles.deleteBtn)} onClick={doDelete} disabled={deleting}>{deleting ? 'Удаление…' : 'Удалить'}</button>
        </div>
      </Modal>
    </div>
  );
}
