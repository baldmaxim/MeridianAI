import { theme } from '../../styles/theme';

const STATUS_MAP: Record<string, { label: string; color: string; bg: string }> = {
  uploaded: { label: 'Загружено', color: theme.text.secondary, bg: 'rgba(136,150,179,0.1)' },
  compressing: { label: 'Сжатие...', color: theme.accent.blue, bg: 'rgba(91,156,246,0.1)' },
  transcribing: { label: 'Транскрипция...', color: theme.accent.amber, bg: theme.accent.amberGlow },
  generating_protocol: { label: 'Протокол...', color: theme.accent.amber, bg: theme.accent.amberGlow },
  done: { label: 'Готово', color: theme.accent.green, bg: theme.accent.greenDim },
  error: { label: 'Ошибка', color: theme.accent.red, bg: theme.accent.redDim },
};

export function BatchStatusBadge({ status }: { status: string }) {
  const info = STATUS_MAP[status] || STATUS_MAP.uploaded;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 10px',
        borderRadius: 12,
        fontSize: 10,
        fontFamily: theme.font.mono,
        fontWeight: 600,
        letterSpacing: '0.06em',
        color: info.color,
        background: info.bg,
        border: `1px solid ${info.color}33`,
      }}
    >
      {(status === 'compressing' || status === 'transcribing' || status === 'generating_protocol') && (
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: info.color,
            animation: 'pulse 1.5s infinite',
          }}
        />
      )}
      {info.label}
    </span>
  );
}
