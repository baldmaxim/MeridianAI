import { useState } from 'react';
import { useMeetingStore } from '../store/meetingStore';
import { theme } from '../styles/theme';

interface Props {
  updateAvailable: boolean;
}

/**
 * Слайд-баннер под шапкой: появляется, когда задеплоена новая версия
 * фронтенда, а вкладка всё ещё на старом бандле. «Обновить» делает hard
 * reload; при активной записи (isListening) сначала спрашивает подтверждение.
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
      <span style={styles.text}>
        <span style={styles.icon}>⬇</span>
        Доступно обновление приложения
        {isListening && (
          <span style={styles.warn}>— идёт запись, обновление прервёт сессию</span>
        )}
      </span>
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
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    padding: '8px 24px',
    flexShrink: 0,
    background: theme.bg.secondary,
    borderBottom: `1px solid ${theme.border.amber}`,
    fontFamily: theme.font.body,
    fontSize: 12,
    color: theme.text.secondary,
  },
  text: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    minWidth: 0,
  },
  icon: {
    color: theme.accent.amber,
    fontSize: 13,
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
