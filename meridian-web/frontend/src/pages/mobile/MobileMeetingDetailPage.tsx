import { useState, useEffect } from 'react';
import { theme } from '../../styles/theme';
import { MobileLayout } from '../../components/mobile/MobileLayout';
import { getMobileMeeting, getLiveState } from '../../api/mobile';
import { finalizeMeeting } from '../../api/finalization';
import { navigate } from '../../lib/navigation';
import { apiErrorMessage } from '../../lib/apiError';
import type { MobileMeetingDetail, LiveState } from '../../types';

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
      getLiveState(meetingId).then(setLive).catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [meetingId]);

  if (error) {
    return (
      <MobileLayout title="ВСТРЕЧА" onBack={() => navigate('/mobile/meetings')}>
        <div style={styles.error}>{error}</div>
      </MobileLayout>
    );
  }
  if (!m) {
    return (
      <MobileLayout title="ВСТРЕЧА" onBack={() => navigate('/mobile/meetings')}>
        <div style={styles.muted}>Загрузка…</div>
      </MobileLayout>
    );
  }

  const canRecord = m.can_current_user_record;

  return (
    <MobileLayout title="ВСТРЕЧА" onBack={() => navigate('/mobile/meetings')}>
      <h2 style={styles.title}>{m.title || m.meeting_topic || 'Без названия'}</h2>
      <div style={styles.meta}>
        {m.customer_name && <span>🏢 {m.customer_name}</span>}
        {m.object_name && <span>📍 {m.object_name}</span>}
        {m.status && <span style={styles.badge}>{m.status}</span>}
      </div>

      {/* Live статус */}
      <div style={styles.card}>
        <div style={styles.cardLabel}>LIVE</div>
        <div style={styles.liveRow}><Dot on={!!live?.desktop_connected} /> Desktop подключён</div>
        <div style={styles.liveRow}><Dot on={!!live?.phone_connected} /> Телефон подключён</div>
        <div style={styles.liveRow}><Dot on={!!live?.phone_recording || !!(live?.active_audio_source)} color={theme.accent.red} /> Запись: {live?.active_audio_source ? 'идёт' : 'нет'}</div>
        <div style={styles.liveSub}>Источник аудио: {live?.active_audio_source ? (live?.phone_recording ? 'телефон' : 'desktop') : 'нет'}</div>
      </div>

      {/* Тема / контекст */}
      {(m.meeting_topic || m.meeting_notes) && (
        <div style={styles.card}>
          <div style={styles.cardLabel}>КОНТЕКСТ</div>
          {m.meeting_topic && <div style={styles.ctxRow}><b>Тема:</b> {m.meeting_topic}</div>}
          {m.meeting_role && <div style={styles.ctxRow}><b>Роль:</b> {m.meeting_role}</div>}
          {m.meeting_notes && <div style={styles.ctxRow}><b>Заметки:</b> {m.meeting_notes}</div>}
        </div>
      )}

      {/* Участники */}
      {m.participants.length > 0 && (
        <div style={styles.card}>
          <div style={styles.cardLabel}>УЧАСТНИКИ</div>
          {m.participants.map((p) => (
            <div key={p.user_id} style={styles.partRow}>
              <span>{p.display_name || p.email}</span>
              <span style={styles.partRole}>{p.role}</span>
            </div>
          ))}
        </div>
      )}

      {/* micro_summary если есть */}
      {m.micro_summary && (
        <div style={styles.card}>
          <div style={styles.cardLabel}>КРАТКО</div>
          <div style={styles.ctxRow}>{m.micro_summary}</div>
        </div>
      )}

      {/* Итоги встречи (Этап 5) */}
      {m.finalization_status && m.finalization_status !== 'not_started' && (
        <div style={styles.card}>
          <div style={styles.cardLabel}>ИТОГИ ВСТРЕЧИ</div>
          {(m.finalization_status === 'queued' || m.finalization_status === 'running') && (
            <div style={styles.ctxRow}>Формируется протокол…</div>
          )}
          {m.finalization_status === 'error' && (
            <div style={{ ...styles.ctxRow, color: theme.accent.red }}>{m.finalization_error || 'Ошибка формирования протокола'}</div>
          )}
          {(m.finalization_status === 'completed' || m.finalization_status === 'partial') && (
            <>
              {m.tags.length > 0 && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {m.tags.map((t) => <span key={t} style={styles.partRole}>#{t}</span>)}
                </div>
              )}
              {m.action_items.length > 0 && (
                <>
                  <div style={styles.subLabel}>Задачи</div>
                  {m.action_items.map((a) => (
                    <div key={a.id} style={styles.ctxRow}>• {a.task} <span style={styles.partRole}>({a.owner_text || 'не указано'})</span></div>
                  ))}
                </>
              )}
              {m.risks.length > 0 && (
                <>
                  <div style={styles.subLabel}>Риски</div>
                  {m.risks.map((r) => (
                    <div key={r.id} style={styles.ctxRow}>⚠ {r.text} <span style={styles.partRole}>({r.severity})</span></div>
                  ))}
                </>
              )}
              {m.open_questions.length > 0 && (
                <>
                  <div style={styles.subLabel}>Открытые вопросы</div>
                  {m.open_questions.map((q) => (
                    <div key={q.id} style={styles.ctxRow}>? {q.text}</div>
                  ))}
                </>
              )}
            </>
          )}
        </div>
      )}

      {/* Документы (read-only) */}
      {m.documents.length > 0 && (
        <div style={styles.card}>
          <div style={styles.cardLabel}>ДОКУМЕНТЫ</div>
          {m.documents.map((d) => (
            <div key={d.id} style={styles.partRow}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.original_name}</span>
              <span style={styles.partRole}>
                {d.status}{d.status === 'ready' ? ` · ${d.chunks_count} фр.` : ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Этап 9: AI-настройки (read-only) */}
      {m.ai_settings_summary && (
        <div style={styles.card}>
          <div style={styles.cardLabel}>AI-НАСТРОЙКИ</div>
          <div style={styles.partRow}>
            <span>Режим</span>
            <span style={styles.partRole}>{String(m.ai_settings_summary.mode ?? '—')}</span>
          </div>
          <div style={styles.partRow}>
            <span>Авто-подсказки</span>
            <span style={styles.partRole}>{m.ai_settings_summary.auto_suggestions_enabled ? 'вкл' : 'выкл'}</span>
          </div>
          <div style={styles.partRow}>
            <span>Документы / База знаний / Прошлые</span>
            <span style={styles.partRole}>
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
        <div style={styles.card}>
          <div style={styles.cardLabel}>КОНТЕКСТ ИЗ ПРОШЛЫХ ВСТРЕЧ</div>
          {m.previous_context.map((p) => (
            <div key={p.meeting_id} style={styles.partRow}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {p.title || `Встреча #${p.meeting_id}`}
                {p.micro_summary ? ` — ${p.micro_summary}` : ''}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Действия */}
      <div style={styles.actions}>
        <button style={styles.primaryBtn} onClick={() => navigate(`/recorder/${m.id}`)}>
          {canRecord ? '🎙 Открыть диктофон' : '👁 Подключиться к просмотру'}
        </button>
        {canRecord && m.status === 'active' && (
          <button style={styles.finalizeBtn} onClick={handleFinalize} disabled={finalizing}>
            {finalizing ? 'Завершение…' : '✓ Завершить встречу'}
          </button>
        )}
        {!canRecord && (
          <div style={styles.permNote}>
            У вас есть доступ к просмотру встречи, но нет права запускать запись.
          </div>
        )}
      </div>
    </MobileLayout>
  );
}

function Dot({ on, color }: { on: boolean; color?: string }) {
  return (
    <span style={{
      width: 8, height: 8, borderRadius: '50%', display: 'inline-block', marginRight: 8,
      background: on ? (color || theme.accent.green) : theme.text.muted, flexShrink: 0,
    }} />
  );
}

const styles: Record<string, React.CSSProperties> = {
  title: { margin: '4px 0 8px', fontFamily: theme.font.body, fontWeight: 700, fontSize: 20, color: theme.text.primary },
  meta: { display: 'flex', gap: 12, flexWrap: 'wrap' as const, alignItems: 'center', fontFamily: theme.font.mono, fontSize: 12, color: theme.text.secondary, marginBottom: 14 },
  badge: { padding: '2px 8px', background: theme.bg.tertiary, border: `1px solid ${theme.border.default}`, borderRadius: 4, fontSize: 9, color: theme.text.muted, textTransform: 'uppercase' as const },
  card: { background: theme.bg.card, border: `1px solid ${theme.border.default}`, borderRadius: 12, padding: 14, marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 6 },
  cardLabel: { fontFamily: theme.font.mono, fontSize: 10, letterSpacing: '0.12em', color: theme.accent.amber, marginBottom: 2 },
  subLabel: { fontFamily: theme.font.mono, fontSize: 10, letterSpacing: '0.08em', color: theme.text.secondary, marginTop: 6 },
  liveRow: { display: 'flex', alignItems: 'center', fontSize: 13, color: theme.text.primary, fontFamily: theme.font.body },
  liveSub: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, marginTop: 2 },
  ctxRow: { fontSize: 13, color: theme.text.secondary, lineHeight: 1.5 },
  partRow: { display: 'flex', justifyContent: 'space-between', fontSize: 13, color: theme.text.primary },
  partRole: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, textTransform: 'uppercase' as const },
  actions: { display: 'flex', flexDirection: 'column', gap: 10, marginTop: 6 },
  primaryBtn: {
    padding: '14px', background: theme.accent.amber, border: 'none', borderRadius: 10,
    color: '#080A0F', fontSize: 15, fontWeight: 700, fontFamily: theme.font.body, cursor: 'pointer',
  },
  finalizeBtn: {
    padding: '14px', background: 'transparent', border: `1px solid ${theme.accent.green}`, borderRadius: 10,
    color: theme.accent.green, fontSize: 15, fontWeight: 700, fontFamily: theme.font.body, cursor: 'pointer',
  },
  permNote: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, textAlign: 'center' as const, lineHeight: 1.5 },
  muted: { color: theme.text.muted, fontFamily: theme.font.mono, fontSize: 13, padding: '12px 0' },
  error: { color: theme.accent.red, fontFamily: theme.font.mono, fontSize: 13, padding: '8px 0' },
};
