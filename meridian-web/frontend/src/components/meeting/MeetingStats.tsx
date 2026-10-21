import { useState, useEffect } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { PopNumber } from '../common/PopNumber';
import { SuccessCheck } from '../common/SuccessCheck';
import styles from './MeetingStats.module.css';
import tone from './Tone.module.css';

interface Props {
  onSaveToHistory: () => void;
}

export function MeetingStats({ onSaveToHistory }: Props) {
  const stats = useMeetingStore((s) => s.meetingStats);
  const isListening = useMeetingStore((s) => s.isListening);
  const messages = useMeetingStore((s) => s.messages);
    const [now, setNow] = useState(() => Date.now());
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');

  // Время встречи в минутах — выводится из «текущего времени», которое обновляется раз в 10 с
  const startTime = stats.meetingStartTime;
  const elapsed = startTime ? `${Math.max(0, Math.floor((now - startTime) / 60000))}м` : '0м';

  useEffect(() => {
    if (!startTime) return;
    const id = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(id);
  }, [startTime]);

  // Подтверждение сохранения приходит из стора (WS): подписка на внешнее хранилище
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = useMeetingStore.subscribe((state, prev) => {
      if (state.meetingSavedId === null || state.meetingSavedId === prev.meetingSavedId) return;
      setSaving(false);
      setSaveMsg('Сохранено в историю');
      clearTimeout(timer);
      timer = setTimeout(() => setSaveMsg(''), 3000);
      useMeetingStore.getState().setMeetingSavedId(null);
    });
    return () => {
      unsubscribe();
      clearTimeout(timer);
    };
  }, []);

  function handleSave() {
    if (messages.length === 0 || saving) return;
    setSaving(true);
    onSaveToHistory();
  }

  return (
    <div className={styles.container}>
      {/* Live indicator */}
      <div className={styles.header}>
        <div className={styles.title}>Динамика встречи</div>
        {isListening && (
          <div className={styles.liveRow}>
            <div className={styles.waveform}>
              {[4, 8, 14, 10, 6, 12, 7].map((h, i) => (
                <div
                  key={i}
                  className={styles.waveformBar}
                  style={{ height: h, animationDelay: `${i * 0.08}s` }}
                />
              ))}
            </div>
            <span className={styles.liveText}>слушаю</span>
          </div>
        )}
      </div>

      <div className={`meeting-stats-grid ${styles.grid}`}>
        <div className={styles.item}>
          <div className={`${styles.value} ${stats.positionStrength >= 60 ? tone.green : tone.amber}`}>
            <PopNumber value={`${stats.positionStrength}%`} />
          </div>
          <div className={styles.label}>Позиция силы</div>
        </div>
        <div className={styles.item}>
          <div className={`${styles.value} ${tone.green}`}>
            <PopNumber value={stats.suggestionsUsed} />
          </div>
          <div className={styles.label}>Подсказок принято</div>
        </div>
        <div className={styles.item}>
          <div className={`${styles.value} ${stats.activeObjections > 0 ? tone.red : tone.primary}`}>
            <PopNumber value={stats.activeObjections} />
          </div>
          <div className={styles.label}>Активных возражений</div>
        </div>
        <div className={styles.item}>
          <div className={styles.value}><PopNumber value={elapsed} /></div>
          <div className={styles.label}>Время встречи</div>
        </div>
      </div>

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={messages.length === 0 || saving}
        className={`${styles.saveBtn} ${messages.length === 0 ? styles.saveBtnEmpty : ''}`}
      >
        {saveMsg && !saving && <SuccessCheck show={!!saveMsg} size={13} />}
        <span>{saving ? 'Сохранение...' : saveMsg || 'Сохранить в историю'}</span>
      </button>
    </div>
  );
}
