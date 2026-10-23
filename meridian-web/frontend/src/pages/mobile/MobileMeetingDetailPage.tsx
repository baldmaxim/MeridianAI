import { useState, useEffect } from 'react';
import { MobileLayout } from '../../components/mobile/MobileLayout';
import { getMobileMeeting, getLiveState } from '../../api/mobile';
import { finalizeMeeting } from '../../api/finalization';
import { navigate } from '../../lib/navigation';
import { apiErrorMessage } from '../../lib/apiError';
import type { MobileMeetingDetail, LiveState } from '../../types';
import { MobileDocumentsCard } from './MobileDocumentsCard';
import styles from './MobileMeetingDetailPage.module.css';
import { cx } from '../../utils/cx';

interface Props {
  meetingId: number;
}

export function MobileMeetingDetailPage({ meetingId }: Props) {
  const [m, setM] = useState<MobileMeetingDetail | null>(null);
  const [live, setLive] = useState<LiveState | null>(null);
  const [error, setError] = useState('');
  const [finalizing, setFinalizing] = useState(false);

  async function handleFinalize() {
    if (finalizing) return;
    setFinalizing(true);
    try {
      await finalizeMeeting(meetingId);
      const d = await getMobileMeeting(meetingId);
      setM(d); setLive(d.live_state);
    } catch (e) {
      setError(apiErrorMessage(e, 'Не удалось завершить встречу'));
    } finally {
      setFinalizing(false);
    }
  }

  useEffect(() => {
    getMobileMeeting(meetingId)
      .then((d) => { setM(d); setLive(d.live_state); })
      .catch((e) => setError(apiErrorMessage(e, 'Не удалось загрузить встречу')));
  }, [meetingId]);

  // лёгкий поллинг live-состояния
  useEffect(() => {
    const t = setInterval(() => {
      getLiveState(meetingId).then(setLive).catch(() => { /* поллинг: пропускаем сбойный тик */ });
    }, 4000);
    return () => clearInterval(t);
  }, [meetingId]);

  if (error) {
    return (
      <MobileLayout title="ВСТРЕЧА" onBack={() => navigate('/mobile/meetings')}>
        <div className={styles.error}>{error}</div>
      </MobileLayout>
    );
  }
  if (!m) {
    return (
      <MobileLayout title="ВСТРЕЧА" onBack={() => navigate('/mobile/meetings')}>
        <div className={styles.muted}>Загрузка…</div>
      </MobileLayout>
    );
  }

  const canRecord = m.can_current_user_record;

  return (
    <MobileLayout title="ВСТРЕЧА" onBack={() => navigate('/mobile/meetings')}>
      <h2 className={styles.title}>{m.title || m.meeting_topic || 'Без названия'}</h2>
      <div className={styles.meta}>
        {m.customer_name && <span>🏢 {m.customer_name}</span>}
        {m.object_name && <span>📍 {m.object_name}</span>}
        {m.status && <span className={styles.badge}>{m.status}</span>}
      </div>

      {/* Live статус */}
      <div className={styles.card}>
        <div className={styles.cardLabel}>LIVE</div>
        <div className={styles.liveRow}><Dot on={!!live?.desktop_connected} /> Desktop подключён</div>
        <div className={styles.liveRow}><Dot on={!!live?.phone_connected} /> Устройство подключено</div>
        <div className={styles.liveRow}><Dot on={!!live?.phone_recording || !!(live?.active_audio_source)} tone="red" /> Запись: {live?.active_audio_source ? 'идёт' : 'нет'}</div>
        <div className={styles.liveSub}>Источник аудио: {live?.active_audio_source ? (live?.phone_recording ? 'устройство' : 'desktop') : 'нет'}</div>
      </div>

      {/* Тема / контекст */}
      {(m.meeting_topic || m.meeting_notes) && (
        <div className={styles.card}>
          <div className={styles.cardLabel}>КОНТЕКСТ</div>
          {m.meeting_topic && <div className={styles.ctxRow}><b>Тема:</b> {m.meeting_topic}</div>}
          {m.meeting_role && <div className={styles.ctxRow}><b>Роль:</b> {m.meeting_role}</div>}
          {m.meeting_notes && <div className={styles.ctxRow}><b>Заметки:</b> {m.meeting_notes}</div>}
        </div>
      )}

      {/* Участники */}
      {m.participants.length > 0 && (
        <div className={styles.card}>
          <div className={styles.cardLabel}>УЧАСТНИКИ</div>
          {m.participants.map((p) => (
            <div key={p.user_id} className={styles.partRow}>
              <span>{p.display_name || p.email}</span>
              <span className={styles.partRole}>{p.role}</span>
            </div>
          ))}
        </div>
      )}

      {/* micro_summary если есть */}
      {m.micro_summary && (
        <div className={styles.card}>
          <div className={styles.cardLabel}>КРАТКО</div>
          <div className={styles.ctxRow}>{m.micro_summary}</div>
        </div>
      )}

      {/* Итоги встречи (Этап 5) */}
      {m.finalization_status && m.finalization_status !== 'not_started' && (
        <div className={styles.card}>
          <div className={styles.cardLabel}>ИТОГИ ВСТРЕЧИ</div>
          {(m.finalization_status === 'queued' || m.finalization_status === 'running') && (
            <div className={styles.ctxRow}>Формируется протокол…</div>
          )}
          {m.finalization_status === 'error' && (
            <div className={cx(styles.ctxRow, styles.ctxError)}>{m.finalization_error || 'Ошибка формирования протокола'}</div>
          )}
          {(m.finalization_status === 'completed' || m.finalization_status === 'partial') && (
            <>
              {m.tags.length > 0 && (
                <div className={styles.chips}>
                  {m.tags.map((t) => <span key={t} className={styles.partRole}>#{t}</span>)}
                </div>
              )}
              {m.action_items.length > 0 && (
                <>
                  <div className={styles.subLabel}>Задачи</div>
                  {m.action_items.map((a) => (
                    <div key={a.id} className={styles.ctxRow}>• {a.task} <span className={styles.partRole}>({a.owner_text || 'не указано'})</span></div>
                  ))}
                </>
              )}
              {m.risks.length > 0 && (
                <>
                  <div className={styles.subLabel}>Риски</div>
                  {m.risks.map((r) => (
                    <div key={r.id} className={styles.ctxRow}>⚠ {r.text} <span className={styles.partRole}>({r.severity})</span></div>
                  ))}
                </>
              )}
              {m.open_questions.length > 0 && (
                <>
                  <div className={styles.subLabel}>Открытые вопросы</div>
                  {m.open_questions.map((q) => (
                    <div key={q.id} className={styles.ctxRow}>? {q.text}</div>
                  ))}
                </>
              )}
            </>
          )}
        </div>
      )}

      {/* Документы: прикреплённые + унаследованные, включение в контекст */}
      {m.documents.length > 0 && (
        <MobileDocumentsCard
          meetingId={meetingId}
          documents={m.documents}
          onChange={(update) => setM((prev) => (prev ? { ...prev, documents: update(prev.documents) } : prev))}
        />
      )}

      {/* Этап 9: AI-настройки (read-only) */}
      {m.ai_settings_summary && (
        <div className={styles.card}>
          <div className={styles.cardLabel}>AI-НАСТРОЙКИ</div>
          <div className={styles.partRow}>
            <span>Режим</span>
            <span className={styles.partRole}>{String(m.ai_settings_summary.mode ?? '—')}</span>
          </div>
          <div className={styles.partRow}>
            <span>Авто-подсказки</span>
            <span className={styles.partRole}>{m.ai_settings_summary.auto_suggestions_enabled ? 'вкл' : 'выкл'}</span>
          </div>
          <div className={styles.partRow}>
            <span>Документы / База знаний / Прошлые</span>
            <span className={styles.partRole}>
              {[m.ai_settings_summary.document_context_enabled,
                m.ai_settings_summary.knowledge_context_enabled,
                m.ai_settings_summary.previous_meetings_context_enabled]
                .map((v) => (v ? '✓' : '✕')).join(' ')}
            </span>
          </div>
        </div>
      )}

      {/* Этап 8: прошлые встречи как контекст (read-only) */}
      {m.previous_context && m.previous_context.length > 0 && (
        <div className={styles.card}>
          <div className={styles.cardLabel}>КОНТЕКСТ ИЗ ПРОШЛЫХ ВСТРЕЧ</div>
          {m.previous_context.map((p) => (
            <div key={p.meeting_id} className={styles.partRow}>
              <span className={styles.ellipsis}>
                {p.title || `Встреча #${p.meeting_id}`}
                {p.micro_summary ? ` — ${p.micro_summary}` : ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Действия */}
      <div className={styles.actions}>
        <button className={styles.primaryBtn} onClick={() => navigate(`/recorder/${m.id}`)}>
          {canRecord ? '🎙 Открыть диктофон' : '👁 Подключиться к просмотру'}
        </button>
        {canRecord && m.status === 'active' && (
          <button className={styles.finalizeBtn} onClick={handleFinalize} disabled={finalizing}>
            {finalizing ? 'Завершение…' : '✓ Завершить встречу'}
          </button>
        )}
        {!canRecord && (
          <div className={styles.permNote}>
            У вас есть доступ к просмотру встречи, но нет права запускать запись.
          </div>
        )}
      </div>
    </MobileLayout>
  );
}

function Dot({ on, tone = 'green' }: { on: boolean; tone?: 'green' | 'red' }) {
  return (
    <span className={cx(styles.dot, on ? (tone === 'red' ? styles.dotRed : styles.dotGreen) : styles.dotOff)} />
  );
}
