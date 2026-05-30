import { useState, useEffect, useMemo } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { theme } from '../../styles/theme';
import { useExitTransition } from '../../hooks/useExitTransition';
import type { Suggestion, SuggestionTypeConfig } from '../../types';

interface TypeStyle {
  badge: string;
  color: string;
  bg: string;
  border: string;
  metaLabel?: string;
  actionLabel: string;
  secondaryAction?: string;
}

const DEFAULT_TYPE_STYLES: Record<string, TypeStyle> = {
  priority: {
    badge: '\u2726 \u041f\u0420\u0418\u041e\u0420\u0418\u0422\u0415\u0422',
    color: theme.accent.amber,
    bg: 'rgba(245,166,35,0.08)',
    border: 'rgba(245,166,35,0.2)',
    metaLabel: '\u041a\u043e\u043d\u0442\u0435\u043a\u0441\u0442',
    actionLabel: '\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c',
  },
  counter: {
    badge: '\u21c4 \u041a\u041e\u041d\u0422\u0420\u0410\u0420\u0413\u0423\u041c\u0415\u041d\u0422',
    color: theme.accent.blue,
    bg: 'rgba(91,156,246,0.08)',
    border: 'rgba(91,156,246,0.2)',
    metaLabel: '\u0422\u0440\u0438\u0433\u0433\u0435\u0440',
    actionLabel: '\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c',
    secondaryAction: '\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u0435\u0435',
  },
  question: {
    badge: '? \u0412\u041e\u041f\u0420\u041e\u0421-\u0417\u0410\u0426\u0415\u041f',
    color: theme.accent.green,
    bg: 'rgba(46,229,157,0.08)',
    border: 'rgba(46,229,157,0.2)',
    metaLabel: '\u041c\u0435\u0442\u043e\u0434',
    actionLabel: '\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c',
  },
  risk: {
    badge: '\u26a0 \u0420\u0418\u0421\u041a',
    color: theme.accent.red,
    bg: 'rgba(255,75,110,0.08)',
    border: 'rgba(255,75,110,0.2)',
    metaLabel: '\u041f\u0430\u0442\u0442\u0435\u0440\u043d',
    actionLabel: '\u041f\u0440\u0438\u043d\u044f\u043b \u043a \u0441\u0432\u0435\u0434\u0435\u043d\u0438\u044e',
  },
};

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16) || 0;
  const g = parseInt(hex.slice(3, 5), 16) || 0;
  const b = parseInt(hex.slice(5, 7), 16) || 0;
  return `rgba(${r},${g},${b},${alpha})`;
}

function buildTypeStyles(customTypes: SuggestionTypeConfig[] | null): Record<string, TypeStyle> {
  if (!customTypes) return DEFAULT_TYPE_STYLES;
  const result: Record<string, TypeStyle> = {};
  for (const t of customTypes) {
    if (!t.enabled) continue;
    result[t.key] = {
      badge: t.badge,
      color: t.color,
      bg: hexToRgba(t.color, 0.08),
      border: hexToRgba(t.color, 0.2),
      metaLabel: t.metaLabel,
      actionLabel: t.actionLabel,
      secondaryAction: t.secondaryAction,
    };
  }
  return Object.keys(result).length > 0 ? result : DEFAULT_TYPE_STYLES;
}

function useRelativeTime(ts: number | null): string {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!ts) return;
    const id = setInterval(() => setTick((t) => t + 1), 5000);
    return () => clearInterval(id);
  }, [ts]);
  if (!ts) return '';
  const sec = Math.floor((Date.now() - ts) / 1000);
  if (sec < 60) return `обновлено ${sec}с назад`;
  return `обновлено ${Math.floor(sec / 60)}м назад`;
}

function useTimeTick(intervalMs = 5000) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}

function formatRelative(date: Date): string {
  const sec = Math.floor((Date.now() - date.getTime()) / 1000);
  if (sec < 60) return `${sec}с назад`;
  return `${Math.floor(sec / 60)}м назад`;
}

function ConfidenceBar({ value, color }: { value: number; color: string }) {
  return (
    <div style={styles.confidenceRow}>
      <span style={{ ...styles.confidenceLabel, color: theme.text.muted }}>
        УВЕРЕННОСТЬ
      </span>
      <div style={styles.confidenceTrack}>
        <div style={{
          ...styles.confidenceFill,
          width: `${Math.min(100, Math.max(0, value))}%`,
          background: color,
        }} />
      </div>
      <span style={{ ...styles.confidenceValue, color }}>{value}</span>
    </div>
  );
}

function getTypeStyle(suggestion: Suggestion, typeStyles: Record<string, TypeStyle>): TypeStyle {
  if (suggestion.type && typeStyles[suggestion.type]) return typeStyles[suggestion.type];
  // Fallback: unknown type — generic gray style
  if (suggestion.type) {
    return {
      badge: suggestion.type.toUpperCase(),
      color: '#8896B3',
      bg: 'rgba(136,150,179,0.08)',
      border: 'rgba(136,150,179,0.2)',
      actionLabel: '\u041f\u0440\u0438\u043d\u044f\u043b \u043a \u0441\u0432\u0435\u0434\u0435\u043d\u0438\u044e',
    };
  }
  return typeStyles.priority || DEFAULT_TYPE_STYLES.priority;
}

function SuggestionCard({ suggestion, typeStyles }: { suggestion: Suggestion; typeStyles: Record<string, TypeStyle> }) {
  const ts = getTypeStyle(suggestion, typeStyles);
  const meta = suggestion.trigger || suggestion.context_info;

  return (
    <div style={{ ...styles.card, borderLeftColor: ts.color }}>
      {/* Top: badge + confidence/time */}
      <div style={styles.cardTop}>
        <span style={{
          ...styles.badge,
          color: ts.color,
          background: ts.bg,
          border: `1px solid ${ts.border}`,
        }}>
          {ts.badge}
        </span>
        {suggestion.type === 'priority' && suggestion.confidence != null ? (
          <div style={styles.confidenceCompact}>
            <span style={styles.confidenceBars}>
              {[...Array(4)].map((_, i) => (
                <span key={i} style={{
                  ...styles.confidenceBarItem,
                  background: i < Math.ceil((suggestion.confidence! / 100) * 4)
                    ? ts.color : 'rgba(255,255,255,0.1)',
                }} />
              ))}
            </span>
            <span style={{ fontSize: 11, color: ts.color, fontFamily: theme.font.mono }}>
              {suggestion.confidence}%
            </span>
          </div>
        ) : (
          <span style={styles.cardTime}>{formatRelative(suggestion.timestamp)}</span>
        )}
      </div>

      {/* Confidence bar for priority */}
      {suggestion.type === 'priority' && suggestion.confidence != null && (
        <ConfidenceBar value={suggestion.confidence} color={ts.color} />
      )}

      {/* Main text */}
      <div style={styles.cardText}>{suggestion.text}</div>

      {/* Meta info: trigger / context / method / pattern */}
      {meta && (
        <div style={styles.metaLine}>
          — {ts.metaLabel}: <span style={styles.metaValue}>
            {suggestion.trigger
              ? suggestion.trigger.split(',').map(t => `«${t.trim()}»`).join(', ')
              : suggestion.context_info}
          </span>
        </div>
      )}

      {/* Actions */}
      <div style={styles.cardActions}>
        <button style={{
          ...styles.actionBtn,
          borderColor: ts.border,
          color: theme.text.secondary,
        }}>
          {ts.actionLabel}
        </button>
        {ts.secondaryAction && (
          <button style={styles.actionBtnSecondary}>
            {ts.secondaryAction}
          </button>
        )}
      </div>
    </div>
  );
}

export function SuggestionPanel() {
  const suggestions = useMeetingStore((s) => s.suggestions);
  const streamingText = useMeetingStore((s) => s.currentStreamingText);
  const lastSuggestionTime = useMeetingStore((s) => s.lastSuggestionTime);
  const analysisStatus = useMeetingStore((s) => s.analysisStatus);
  const suggestionLoading = useMeetingStore((s) => s.suggestionLoading);
  const strengthenLoading = useMeetingStore((s) => s.strengthenLoading);
  const customSuggestionTypes = useMeetingStore((s) => s.customSuggestionTypes);
  const typeStyles = useMemo(() => buildTypeStyles(customSuggestionTypes), [customSuggestionTypes]);

  const isAnalyzing = analysisStatus != null || streamingText !== null || suggestionLoading || strengthenLoading;
  const relTime = useRelativeTime(lastSuggestionTime);
  useTimeTick(5000);

  const statusText = analysisStatus
    || (streamingText !== null ? 'Генерирую подсказку...'
    : suggestionLoading ? 'Формирую тактические подсказки...'
    : strengthenLoading ? 'Анализирую позицию и аргументы...'
    : null);

  // panel-reveal (transitions.dev 07): анализ-бар плавно въезжает/уезжает.
  const analysis = useExitTransition(isAnalyzing && statusText != null, {
    closeVar: '--panel-close-dur',
    fallbackMs: 350,
  });

  return (
    <div className="suggestion-panel" style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <span style={{
          ...styles.dot,
          background: isAnalyzing ? theme.accent.green : theme.accent.amber,
          animation: isAnalyzing ? 'pulse 1.5s infinite' : 'none',
        }} />
        <span style={styles.title}>Тактические подсказки AI</span>
        {suggestions.length > 0 && (
          <span style={styles.meta}>
            {suggestions.length} актуальных{relTime ? ` · ${relTime}` : ''}
          </span>
        )}
      </div>

      {/* Analysis status bar */}
      {analysis.mounted && (
        <div
          className="t-panel-slide"
          data-open={analysis.open ? 'true' : 'false'}
          style={{ ...styles.analysisBar, ['--panel-translate-y']: '10px' } as React.CSSProperties}
        >
          <span style={styles.analysisDots}>•••</span> {statusText}
        </div>
      )}

      {/* Cards */}
      <div style={styles.cards}>
        {suggestions.length === 0 && !isAnalyzing && (
          <div style={styles.placeholder}>
            Здесь появятся тактические подсказки AI.
            Начните прослушивание переговоров или запросите подсказку вручную.
          </div>
        )}

        {/* Streaming card (for backward compat with streaming suggestions) */}
        {streamingText !== null && (
          <div style={{ ...styles.card, borderLeftColor: theme.accent.blue }}>
            <span style={{
              ...styles.badge,
              color: theme.accent.blue,
              background: 'rgba(91,156,246,0.1)',
              border: '1px solid rgba(91,156,246,0.2)',
            }}>
              Генерация...
            </span>
            <div style={styles.cardText}>{streamingText}</div>
          </div>
        )}

        {/* Suggestion cards (newest first) */}
        {[...suggestions].reverse().map((s, i) => (
          <SuggestionCard key={i} suggestion={s} typeStyles={typeStyles} />
        ))}
      </div>

      {/* Pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '0 0 12px 0',
    flexShrink: 0,
  },
  dot: {
    width: 6, height: 6, borderRadius: '50%',
    background: theme.accent.amber, flexShrink: 0,
  },
  title: {
    fontFamily: theme.font.heading, fontWeight: 700, fontSize: 11,
    letterSpacing: '0.14em', textTransform: 'uppercase' as const,
    color: theme.text.primary, flex: 1,
  },
  meta: {
    fontFamily: theme.font.mono, fontSize: 10, color: theme.text.muted,
    whiteSpace: 'nowrap',
  },
  analysisBar: {
    padding: '10px 16px',
    background: 'linear-gradient(90deg, rgba(245,166,35,0.08), rgba(46,229,157,0.08))',
    border: '1px solid rgba(245,166,35,0.15)',
    borderRadius: 8,
    fontSize: 12,
    fontFamily: theme.font.mono,
    color: theme.accent.amber,
    marginBottom: 12,
    flexShrink: 0,
  },
  analysisDots: {
    fontWeight: 700,
    marginRight: 6,
    letterSpacing: 2,
  },
  cards: {
    flex: 1,
    overflow: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  placeholder: {
    color: theme.text.muted,
    fontSize: 13,
    fontFamily: theme.font.body,
    textAlign: 'center',
    padding: '40px 20px',
    lineHeight: 1.6,
  },
  card: {
    background: theme.bg.card,
    border: `1px solid ${theme.border.default}`,
    borderLeft: '3px solid',
    borderRadius: 10,
    padding: '16px 18px',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  cardTop: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '3px 10px',
    borderRadius: 5,
    fontSize: 9,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
  },
  cardTime: {
    fontFamily: theme.font.mono,
    fontSize: 10,
    color: theme.text.muted,
  },
  confidenceCompact: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  confidenceBars: {
    display: 'flex',
    gap: 2,
    alignItems: 'flex-end',
  },
  confidenceBarItem: {
    width: 3,
    height: 12,
    borderRadius: 1,
  },
  confidenceRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  confidenceLabel: {
    fontSize: 8,
    fontFamily: theme.font.mono,
    fontWeight: 600,
    letterSpacing: '0.1em',
    textTransform: 'uppercase' as const,
    flexShrink: 0,
  },
  confidenceTrack: {
    flex: 1,
    height: 3,
    borderRadius: 2,
    background: 'rgba(255,255,255,0.06)',
    overflow: 'hidden',
  },
  confidenceFill: {
    height: '100%',
    borderRadius: 2,
    transition: 'width 0.5s ease',
  },
  confidenceValue: {
    fontSize: 12,
    fontFamily: theme.font.mono,
    fontWeight: 700,
    flexShrink: 0,
    minWidth: 20,
    textAlign: 'right' as const,
  },
  cardText: {
    fontSize: 13,
    lineHeight: 1.65,
    color: theme.text.primary,
    fontFamily: theme.font.body,
    whiteSpace: 'pre-wrap' as const,
  },
  metaLine: {
    fontSize: 11,
    fontFamily: theme.font.mono,
    color: theme.text.muted,
    lineHeight: 1.4,
  },
  metaValue: {
    color: theme.text.secondary,
  },
  cardActions: {
    display: 'flex',
    gap: 8,
    marginTop: 4,
  },
  actionBtn: {
    padding: '5px 14px',
    background: theme.bg.elevated,
    border: `1px solid ${theme.border.default}`,
    borderRadius: 5,
    color: theme.text.secondary,
    fontSize: 11,
    fontFamily: theme.font.body,
    cursor: 'pointer',
  },
  actionBtnSecondary: {
    padding: '5px 14px',
    background: 'transparent',
    border: `1px solid ${theme.border.default}`,
    borderRadius: 5,
    color: theme.text.muted,
    fontSize: 11,
    fontFamily: theme.font.body,
    cursor: 'pointer',
  },
};
