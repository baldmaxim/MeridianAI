import { useState } from 'react';
import { useMeetingStore } from '../store/meetingStore';
import { theme } from '../styles/theme';

interface Props {
  updateAvailable: boolean;
}

/**
 * Плавающий тост поверх интерфейса: появляется по центру сверху, когда
 * задеплоена новая версия фронтенда, а вкладка всё ещё на старом бандле.
 * «Обновить» делает hard reload; при активной записи (isListening) сначала
 * спрашивает подтверждение.
 */
export function AppUpdateBanner({ updateAvailable }: Props) {
  const isListening = useMeetingStore((s) => s.isListening);
  const [dismissed, setDismissed] = useState(false);

  if (!updateAvailable || dismissed) return null;

  const handleUpdate = () => {
    if (
      isListening &&
      !window.confirm(
        'Идёт активная сессия. Обновление перезагрузит страницу и прервёт запись. Обновить сейчас?'
      )
    ) {
      return;
    }
    window.location.reload();
  };

  return (
    <div className="t-update-banner" style={styles.bar}>
      <span style={styles.icon}>⬇</span>
      <div style={styles.body}>
        <span style={styles.title}>Доступно обновление приложения</span>
        {isListening && (
          <span style={styles.warn}>идёт запись — обновление прервёт сессию</span>
        )}
      </div>
      <div style={styles.actions}>
        <button onClick={handleUpdate} style={styles.update}>
          Обновить
        </button>
        <button onClick={() => setDismissed(true)} style={styles.dismiss}>
          Позже
        </button>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  bar: {
    position: 'fixed',
    top: 16,
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: 1000,
    width: 'max-content',
    maxWidth: 'min(440px, calc(100vw - 24px))',
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '12px 16px',
    background: theme.bg.elevated,
    border: `1px solid ${theme.accent.amber}`,
    borderRadius: 10,
    boxShadow: '0 10px 30px rgba(0,0,0,0.45), 0 0 0 4px rgba(245,166,35,0.08)',
    fontFamily: theme.font.body,
    fontSize: 12,
    color: theme.text.primary,
  },
  body: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    minWidth: 0,
  },
  title: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.text.primary,
  },
  icon: {
    color: theme.accent.amber,
    fontSize: 16,
    flexShrink: 0,
  },
  warn: {
    color: theme.accent.amber,
    fontFamily: theme.font.mono,
    fontSize: 11,
  },
  actions: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexShrink: 0,
  },
  update: {
    padding: '4px 14px',
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
  dismiss: {
    padding: '4px 10px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 5,
    color: theme.text.muted,
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: theme.font.mono,
    letterSpacing: '0.06em',
  },
};
