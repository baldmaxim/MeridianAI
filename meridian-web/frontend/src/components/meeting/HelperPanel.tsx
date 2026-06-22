import { useEffect, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { useSecondaryShadow } from '../../hooks/useSecondaryShadow';
import { uniqueParticipantUsers } from '../../lib/participants';
import { SyncBadge } from './SyncBadge';
import { theme } from '../../styles/theme';

// Авто-помощь распознаванию (задача 2). Роль устройства выводится из состояния комнаты:
// если звук уже пишет ДРУГОЕ устройство, а это может слать аудио — оно становится
// помощником (shadow). Браузеру для микрофона нужен жест → одна кнопка-согласие,
// дальше захват идёт сам. Ручных тумблеров observer/shadow больше нет.
export function HelperPanel() {
  const meetingId = useMeetingStore((s) => s.currentMeetingId);
  const connectionId = useMeetingStore((s) => s.connectionId);
  const activeAudioSource = useMeetingStore((s) => s.activeAudioSource);
  const canSendAudio = useMeetingStore((s) => s.canSendAudio);
  const participants = useMeetingStore((s) => s.participants);

  const { active, side, level, error, sync, start, stop, setSideHint } = useSecondaryShadow(meetingId);
  // Активная помощь свёрнута в пилюлю; по тапу раскрывается выбор стороны и «стоп».
  const [expanded, setExpanded] = useState(false);

  const isPrimary = !!connectionId && activeAudioSource === connectionId;
  const someoneElseRecording = !!activeAudioSource && activeAudioSource !== connectionId;
  const shouldHelp = someoneElseRecording && canSendAudio && !isPrimary;

  // Авто-стоп: помощь больше не нужна (стали primary / запись остановлена) → гасим shadow.
  useEffect(() => {
    if (active && !shouldHelp) stop();
  }, [active, shouldHelp, stop]);

  const helpers = uniqueParticipantUsers(participants).filter((u) => u.isHelper);
  const pct = Math.min(100, Math.round(level * 100));

  // 1) Это устройство уже помогает распознаванию — компактная пилюля.
  //    Тап по строке раскрывает выбор стороны и «Перестать помогать».
  if (active) {
    return (
      <div style={styles.panelTight}>
        <div
          role="button"
          tabIndex={0}
          style={styles.pillHeader}
          onClick={() => setExpanded((v) => !v)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded((v) => !v); } }}
        >
          <span style={{ ...styles.dot, background: theme.accent.amber, animation: 'pulse 1.4s ease-in-out infinite' }} />
          <span style={styles.pillText}>Помогаю распознаванию</span>
          <span style={styles.pillMeter}><span style={{ ...styles.meterFill, width: `${pct}%` }} /></span>
          <SyncBadge sync={sync} compact />
          <span style={{ ...styles.chevron, transform: expanded ? 'rotate(180deg)' : 'none' }}>⌄</span>
        </div>
        {expanded && (
          <div style={styles.expandWrap}>
            <div style={styles.sideRow}>
              <span style={styles.label}>Рядом с:</span>
              <button type="button" style={side === 'self' ? styles.sideOnSelf : styles.sideOff}
                onClick={() => setSideHint('self')}>Нами</button>
              <button type="button" style={side === 'opponent' ? styles.sideOnOpp : styles.sideOff}
                onClick={() => setSideHint('opponent')}>Другой стороной</button>
            </div>
            <div style={styles.controls}>
              <button type="button" style={styles.stopBtn} onClick={stop}>Перестать помогать</button>
              <span style={styles.muted}>звук в текст шлёт основное устройство</span>
            </div>
          </div>
        )}
        {error && <div style={styles.error}>{error}</div>}
      </div>
    );
  }

  // 2) Можно помочь (кто-то другой пишет звук) — предложить согласие на микрофон.
  //    Кнопка активна всегда: shouldHelp ⇒ комната подключена ⇒ meetingId проставлен.
  if (shouldHelp) {
    return (
      <div style={styles.panel}>
        <div style={styles.note}>
          Запись уже идёт с другого устройства. Это устройство может помочь распознаванию:
          положите его ближе к одной из сторон и включите помощь.
        </div>
        <button type="button" style={styles.startBtn} onClick={() => void start()}>
          Помогать распознаванию
        </button>
        {error && <div style={styles.error}>{error}</div>}
      </div>
    );
  }

  // 3) Это устройство — основной источник И кто-то уже помогает: тонкая строка статуса.
  if (isPrimary && helpers.length > 0) {
    return (
      <div style={styles.panel}>
        <div style={styles.statusRow}>
          <span style={{ ...styles.dot, background: theme.accent.amber }} />
          <span style={styles.muted}>
            Помогают распознаванию: {helpers.map((h) => h.label).join(', ')}
          </span>
        </div>
      </div>
    );
  }

  // 4) Нечего показывать (нет записи / помощь не нужна) — баннер скрыт.
  return null;
}

const styles: Record<string, React.CSSProperties> = {
  panel: {
    display: 'flex', flexDirection: 'column', gap: 10,
    margin: '8px 16px 0', padding: '12px 16px', background: theme.bg.card,
    border: `1px solid ${theme.border.amber}`, borderRadius: 10, flexShrink: 0,
  },
  panelTight: {
    display: 'flex', flexDirection: 'column', gap: 6,
    margin: '8px 16px 0', padding: '8px 12px', background: theme.bg.card,
    border: `1px solid ${theme.border.amber}`, borderRadius: 10, flexShrink: 0,
  },
  pillHeader: {
    display: 'flex', alignItems: 'center', gap: 8, width: '100%',
    background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
    textAlign: 'left' as const, color: theme.text.primary,
  },
  pillText: { flex: 1, fontFamily: theme.font.body, fontSize: 13, fontWeight: 600, color: theme.text.primary },
  pillMeter: { width: 48, height: 6, borderRadius: 3, background: theme.bg.input, overflow: 'hidden', flexShrink: 0 },
  chevron: { fontFamily: theme.font.mono, fontSize: 14, color: theme.text.muted, transition: 'transform 0.15s ease', lineHeight: 1 },
  expandWrap: { display: 'flex', flexDirection: 'column', gap: 8 },
  note: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.secondary, lineHeight: 1.5 },
  muted: { fontFamily: theme.font.mono, fontSize: 11, color: theme.text.muted, lineHeight: 1.5 },
  statusRow: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const },
  dot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  sideRow: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const },
  label: { fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted, letterSpacing: '0.06em' },
  sideOff: {
    padding: '8px 14px', background: 'transparent', border: `1px solid ${theme.border.default}`,
    borderRadius: 8, color: theme.text.secondary, cursor: 'pointer', fontSize: 12, fontFamily: theme.font.body,
  },
  sideOnSelf: {
    padding: '8px 14px', background: 'rgba(46,229,157,0.12)', border: `1px solid ${theme.accent.green}`,
    borderRadius: 8, color: theme.accent.green, cursor: 'pointer', fontSize: 12, fontWeight: 600, fontFamily: theme.font.body,
  },
  sideOnOpp: {
    padding: '8px 14px', background: 'rgba(255,75,110,0.12)', border: `1px solid ${theme.accent.red}`,
    borderRadius: 8, color: theme.accent.red, cursor: 'pointer', fontSize: 12, fontWeight: 600, fontFamily: theme.font.body,
  },
  meterFill: { height: '100%', background: theme.accent.amber, borderRadius: 4, transition: 'width 0.1s linear' },
  controls: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' as const },
  startBtn: {
    padding: '10px 18px', background: theme.accent.amber, border: 'none', borderRadius: 8,
    color: '#080A0F', cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: theme.font.body,
    alignSelf: 'flex-start',
  },
  stopBtn: {
    padding: '10px 18px', background: 'transparent', border: `1px solid ${theme.accent.red}`, borderRadius: 8,
    color: theme.accent.red, cursor: 'pointer', fontSize: 13, fontWeight: 600, fontFamily: theme.font.body,
  },
  error: { fontFamily: theme.font.mono, fontSize: 11, color: theme.accent.red },
};
