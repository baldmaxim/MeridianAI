import { useState, useEffect } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import { PopNumber } from '../common/PopNumber';
import { SuccessCheck } from '../common/SuccessCheck';

interface Props {
  onSaveToHistory: () => void;
}

export function MeetingStats({ onSaveToHistory }: Props) {
  const stats = useMeetingStore((s) => s.meetingStats);
  const isListening = useMeetingStore((s) => s.isListening);
  const messages = useMeetingStore((s) => s.messages);
  const meetingSavedId = useMeetingStore((s) => s.meetingSavedId);
  const [elapsed, setElapsed] = useState('0м');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');

  useEffect(() => {
    if (!stats.meetingStartTime) {
      setElapsed('0м');
      return;
    }
    const tick = () => {
      const mins = Math.floor((Date.now() - stats.meetingStartTime!) / 60000);
      setElapsed(`${mins}м`);
    };
    tick();
    const id = setInterval(tick, 10000);
    return () => clearInterval(id);
  }, [stats.meetingStartTime]);

  useEffect(() => {
    if (meetingSavedId !== null) {
      setSaving(false);
      setSaveMsg('Сохранено в историю');
      const t = setTimeout(() => setSaveMsg(''), 3000);
      useMeetingStore.getState().setMeetingSavedId(null);
      return () => clearTimeout(t);
    }
  }, [meetingSavedId]);

  function handleSave() {
    if (messages.length === 0 || saving) return;
    setSaving(true);
    onSaveToHistory();
  }

  return (
    <div style={styles.container}>
      {/* Live indicator */}
      <div style={styles.header}>
        <div style={styles.title}>Динамика встречи</div>
        {isListening && (
          <div style={styles.liveRow}>
            <div style={styles.waveform}>
              {[4, 8, 14, 10, 6, 12, 7].map((h, i) => (
                <div
                  key={i}
                  className="waveform-bar"
                  style={{
                    ...styles.waveformBar,
                    height: h,
                    animationDelay: `${i * 0.08}s`,
                  }}
                />
              ))}
            </div>
            <span style={styles.liveText}>слушаю</span>
          </div>
        )}
      </div>

      <div className="meeting-stats-grid" style={styles.grid}>
        <div style={styles.item}>
          <div style={{ ...styles.value, color: stats.positionStrength >= 60 ? theme.accent.green : theme.accent.amber }}>
            <PopNumber value={`${stats.positionStrength}%`} />
          </div>
          <div style={styles.label}>Позиция силы</div>
        </div>
        <div style={styles.item}>
          <div style={{ ...styles.value, color: theme.accent.green }}>
            <PopNumber value={stats.suggestionsUsed} />
          </div>
          <div style={styles.label}>Подсказок принято</div>
        </div>
        <div style={styles.item}>
          <div style={{ ...styles.value, color: stats.activeObjections > 0 ? theme.accent.red : theme.text.primary }}>
            <PopNumber value={stats.activeObjections} />
          </div>
          <div style={styles.label}>Активных возражений</div>
        </div>
        <div style={styles.item}>
          <div style={styles.value}><PopNumber value={elapsed} /></div>
          <div style={styles.label}>Время встречи</div>
        </div>
      </div>

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={messages.length === 0 || saving}
        style={{
          ...styles.saveBtn,
          opacity: messages.length === 0 ? 0.4 : 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 6,
        }}
      >
        {saveMsg && !saving && <SuccessCheck show={!!saveMsg} size={13} />}
        <span>{saving ? 'Сохранение...' : saveMsg || 'Сохранить в историю'}</span>
      </button>

      {/* CSS keyframes for waveform */}
      <style>{`
        @keyframes wave {
          0%, 100% { transform: scaleY(1); opacity: 0.5; }
          50% { transform: scaleY(1.8); opacity: 1; }
        }
        .waveform-bar {
          animation: wave 0.8s ease-in-out infinite;
        }
      `}</style>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: '14px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    flexShrink: 0,
    background: theme.bg.tertiary,
    borderRadius: 10,
    border: `1px solid ${theme.border.default}`,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontFamily: theme.font.mono,
    fontSize: 9,
    color: theme.text.muted,
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
  },
  liveRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  waveform: {
    display: 'flex',
    alignItems: 'center',
    gap: 2,
    height: 16,
  },
  waveformBar: {
    width: 2,
    background: theme.accent.amber,
    borderRadius: 1,
    opacity: 0.7,
  },
  liveText: {
    fontFamily: theme.font.mono,
    fontSize: 9,
    color: theme.text.muted,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 8,
  },
  item: {
    background: theme.bg.tertiary,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 6,
    padding: '8px 10px',
  },
  value: {
    fontFamily: theme.font.heading,
    fontSize: 18,
    fontWeight: 700,
    lineHeight: 1,
    color: theme.text.primary,
  },
  label: {
    fontSize: 9,
    color: theme.text.muted,
    marginTop: 3,
    letterSpacing: '0.06em',
  },
  saveBtn: {
    padding: '8px 14px',
    background: theme.bg.elevated,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 7,
    color: theme.text.secondary,
    fontSize: 11,
    fontWeight: 500,
    cursor: 'pointer',
    fontFamily: theme.font.body,
    transition: 'all 0.2s',
    textAlign: 'center' as const,
  },
};
