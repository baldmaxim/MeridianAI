import React, { useState } from 'react';
import { theme } from '../../styles/theme';
import type { PublicSpeakerSide } from '../../types';
import { useSpeakerSideSummary } from '../../hooks/useSpeakerSideSummary';
import { Collapse, PopNumber, SuccessCheck } from '../common';

interface ISideCalibrationProps {
  sinceIndex: number;
  holding: boolean;
  onPress: () => void;
  onRelease: () => void;
  onSetSide: (label: string, side: PublicSpeakerSide) => void;
  compact?: boolean;
}

/**
 * Калибровка сторон в начале очной встречи: держат кнопку, пока говорит наша сторона.
 * Когда у всех голосов есть сторона — кнопка сворачивается в строку «✓ Голоса определены».
 * Голос, который кнопкой так и не определился, спрашиваем карточкой «Кто это?».
 */
export const SideCalibration: React.FC<ISideCalibrationProps> = ({
  sinceIndex, holding, onPress, onRelease, onSetSide, compact = false,
}) => {
  const summary = useSpeakerSideSummary(sinceIndex);
  const showButton = holding || !summary.calibrated;
  // Карточка держит последний вопрос на время exit-анимации.
  const [shownAsk, setShownAsk] = useState(summary.ask);
  if (summary.ask && (summary.ask.label !== shownAsk?.label || summary.ask.phrase !== shownAsk?.phrase)) {
    setShownAsk(summary.ask);
  }

  return (
    <div style={compact ? styles.wrapCompact : styles.wrap}>
      <style>{`
        .sc-key-hint { display: none; }
        @media (min-width: 768px) { .sc-key-hint { display: inline; } }
      `}</style>
      {showButton ? (
        <button
          type="button"
          className="t-btn"
          style={{ ...styles.holdBtn, ...(compact ? styles.holdBtnCompact : {}), ...(holding ? styles.holdBtnOn : {}) }}
          onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); onPress(); }}
          onPointerUp={onRelease}
          onPointerCancel={onRelease}
          onLostPointerCapture={onRelease}
          onContextMenu={(e) => e.preventDefault()}
          aria-pressed={holding}
        >
          <span style={styles.holdTitle}>{holding ? 'Говорим мы…' : 'Держите, пока говорим мы'}</span>
          <span style={styles.holdSub}>
            {holding ? 'Отпустите, когда заговорят они' : 'В начале встречи, пока голоса не определятся'}
            <span className="sc-key-hint"> · или держите M</span>
          </span>
        </button>
      ) : (
        <div style={styles.done}>
          <SuccessCheck show size={14} />
          <span>Голоса определены:</span>
          <PopNumber value={summary.selfCount} style={styles.num} /><span>наших,</span>
          <PopNumber value={summary.opponentCount} style={styles.num} /><span>их</span>
        </div>
      )}
      <Collapse open={!!summary.ask && !holding}>
        {shownAsk && (
          <div style={styles.ask}>
            <span style={styles.askText}>Кто это: «{shownAsk.phrase}»?</span>
            <span style={styles.askBtns}>
              <button type="button" className="t-btn" style={styles.askSelf} onClick={() => onSetSide(shownAsk.label, 'self')}>Мы</button>
              <button type="button" className="t-btn" style={styles.askOpp} onClick={() => onSetSide(shownAsk.label, 'opponent')}>Не мы</button>
            </span>
          </div>
        )}
      </Collapse>
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  wrap: { width: '100%', maxWidth: 320, display: 'flex', flexDirection: 'column', gap: 8, margin: '12px auto 0' },
  wrapCompact: { display: 'flex', flexDirection: 'column', gap: 6, padding: '6px 12px', flexShrink: 0 },
  holdBtn: {
    width: '100%', minHeight: 64, padding: '10px 16px', borderRadius: 14,
    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 3,
    background: theme.bg.elevated, border: `1px solid ${theme.border.default}`, color: theme.text.primary,
    cursor: 'pointer', fontFamily: theme.font.body,
    touchAction: 'none', userSelect: 'none', WebkitUserSelect: 'none', WebkitTouchCallout: 'none',
  } as React.CSSProperties,
  holdBtnCompact: { minHeight: 56, borderRadius: 10 },
  holdBtnOn: { background: 'rgba(46,229,157,0.14)', border: `1px solid ${theme.accent.green}`, color: theme.accent.green },
  holdTitle: { fontSize: 15, fontWeight: 600 },
  holdSub: { fontSize: 11, color: theme.text.secondary, fontFamily: theme.font.mono },
  done: {
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, flexWrap: 'wrap',
    color: theme.text.secondary, fontSize: 12, fontFamily: theme.font.mono,
  },
  num: { color: theme.text.primary, fontWeight: 600 },
  ask: {
    display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'space-between',
    background: theme.accent.amberGlow, border: `1px solid ${theme.border.amber}`, borderRadius: 8, padding: '8px 10px',
  },
  askText: { color: theme.text.primary, fontSize: 12, fontFamily: theme.font.body, overflowWrap: 'anywhere', flex: '1 1 180px' },
  askBtns: { display: 'flex', gap: 6, flexShrink: 0 },
  askSelf: {
    minHeight: 44, padding: '0 14px', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600,
    background: 'transparent', border: `1px solid ${theme.accent.green}`, color: theme.accent.green,
  },
  askOpp: {
    minHeight: 44, padding: '0 14px', borderRadius: 6, cursor: 'pointer', fontSize: 13, fontWeight: 600,
    background: 'transparent', border: `1px solid ${theme.accent.red}`, color: theme.accent.red,
  },
};
