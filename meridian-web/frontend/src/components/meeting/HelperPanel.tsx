import { useEffect, useState } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { useSecondaryShadow } from '../../hooks/useSecondaryShadow';
import { uniqueParticipantUsers } from '../../lib/participants';
import { SyncBadge } from './SyncBadge';
import styles from './HelperPanel.module.css';

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
      <div className={styles.panelTight}>
        <div
          role="button"
          tabIndex={0}
          className={styles.pillHeader}
          onClick={() => setExpanded((v) => !v)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded((v) => !v); } }}
        >
          <span className={`pulse-dot ${styles.dot}`} />
          <span className={styles.pillText}>Помогаю распознаванию</span>
          <span className={styles.pillMeter}><span className={styles.meterFill} style={{ transform: `scaleX(${pct / 100})` }} /></span>
          <SyncBadge sync={sync} compact />
          <span className={`${styles.chevron} ${expanded ? styles.chevronOpen : ''}`}>⌄</span>
        </div>
        {expanded && (
          <div className={styles.expandWrap}>
            <div className={styles.sideRow}>
              <span className={styles.label}>Рядом с:</span>
              <button type="button" className={side === 'self' ? styles.sideOnSelf : styles.sideOff}
                onClick={() => setSideHint('self')}>Нами</button>
              <button type="button" className={side === 'opponent' ? styles.sideOnOpp : styles.sideOff}
                onClick={() => setSideHint('opponent')}>Другой стороной</button>
            </div>
            <div className={styles.controls}>
              <button type="button" className={styles.stopBtn} onClick={stop}>Перестать помогать</button>
              <span className={styles.muted}>звук в текст шлёт основное устройство</span>
            </div>
          </div>
        )}
        {error && <div className={styles.error}>{error}</div>}
      </div>
    );
  }

  // 2) Можно помочь (кто-то другой пишет звук) — предложить согласие на микрофон.
  //    Кнопка активна всегда: shouldHelp ⇒ комната подключена ⇒ meetingId проставлен.
  if (shouldHelp) {
    return (
      <div className={styles.panel}>
        <div className={styles.note}>
          Запись уже идёт с другого устройства. Это устройство может помочь распознаванию:
          положите его ближе к одной из сторон и включите помощь.
        </div>
        <button type="button" className={styles.startBtn} onClick={() => void start()}>
          Помогать распознаванию
        </button>
        {error && <div className={styles.error}>{error}</div>}
      </div>
    );
  }

  // 3) Это устройство — основной источник И кто-то уже помогает: тонкая строка статуса.
  if (isPrimary && helpers.length > 0) {
    return (
      <div className={styles.panel}>
        <div className={styles.statusRow}>
          <span className={styles.dot} />
          <span className={styles.muted}>
            Помогают распознаванию: {helpers.map((h) => h.label).join(', ')}
          </span>
        </div>
      </div>
    );
  }

  // 4) Нечего показывать (нет записи / помощь не нужна) — баннер скрыт.
  return null;
}
