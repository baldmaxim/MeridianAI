import React, { useState } from 'react';
import type { PublicSpeakerSide } from '../../types';
import { useSpeakerSideSummary } from '../../hooks/useSpeakerSideSummary';
import { Collapse, PopNumber, SuccessCheck } from '../common';
import styles from './SideCalibration.module.css';

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
    <div className={compact ? styles.wrapCompact : styles.wrap}>
      {showButton ? (
        <button
          type="button"
          className={`t-btn ${styles.holdBtn} ${compact ? styles.holdBtnCompact : ''} ${holding ? styles.holdBtnOn : ''}`}
          onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); onPress(); }}
          onPointerUp={onRelease}
          onPointerCancel={onRelease}
          onLostPointerCapture={onRelease}
          onContextMenu={(e) => e.preventDefault()}
          aria-pressed={holding}
        >
          <span className={styles.holdTitle}>{holding ? 'Говорим мы…' : 'Держите, пока говорим мы'}</span>
          <span className={styles.holdSub}>
            {holding ? 'Отпустите, когда заговорят они' : 'В начале встречи, пока голоса не определятся'}
            <span className={styles.keyHint}> · или держите M</span>
          </span>
        </button>
      ) : (
        <div className={styles.done}>
          <SuccessCheck show size={14} />
          <span>Голоса определены:</span>
          <PopNumber value={summary.selfCount} className={styles.num} /><span>наших,</span>
          <PopNumber value={summary.opponentCount} className={styles.num} /><span>их</span>
        </div>
      )}
      <Collapse open={!!summary.ask && !holding}>
        {shownAsk && (
          <div className={styles.ask}>
            <span className={styles.askText}>Кто это: «{shownAsk.phrase}»?</span>
            <span className={styles.askBtns}>
              <button type="button" className={`t-btn ${styles.askSelf}`} onClick={() => onSetSide(shownAsk.label, 'self')}>Мы</button>
              <button type="button" className={`t-btn ${styles.askOpp}`} onClick={() => onSetSide(shownAsk.label, 'opponent')}>Не мы</button>
            </span>
          </div>
        )}
      </Collapse>
    </div>
  );
};
