import { Fragment, useMemo } from 'react';
import type { FC, RefObject } from 'react';
import type { TranscriptWordTiming } from '../../types';
import { cx } from '../../utils/cx';
import { alignWordsToText } from './alignWords';
import { useActiveWord } from './useActiveWord';
import styles from './KaraokeText.module.css';

interface IKaraokeTextProps {
  text: string;
  words: TranscriptWordTiming[];
  audioRef: RefObject<HTMLAudioElement | null>;
  className?: string;
}

/** Текст реплики с обводкой слова, которое звучит в записи сейчас. Не сопоставилось — обычный текст. */
export const KaraokeText: FC<IKaraokeTextProps> = ({ text, words, audioRef, className }) => {
  const tokens = useMemo(() => alignWordsToText(text, words), [text, words]);
  const activeIdx = useActiveWord(audioRef, tokens, tokens !== null);

  if (!tokens) return <span className={className}>{text}</span>;
  return (
    <span className={className}>
      {tokens.map((token, i) =>
        !token.text.trim() ? (
          <Fragment key={i}>{token.text}</Fragment>
        ) : (
          <span key={i} className={cx(styles.word, i === activeIdx && styles.wordActive)}>
            {token.text}
          </span>
        ),
      )}
    </span>
  );
};
