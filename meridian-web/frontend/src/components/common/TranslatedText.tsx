import type { FC, ReactNode } from 'react';
import { foreignLanguageBadge } from '../../lib/segmentMeta';
import styles from './TranslatedText.module.css';

interface ITranslatedTextProps {
  /** Оригинал реплики. */
  text: ReactNode;
  /** Русский перевод; нет — показываем только оригинал как основной текст. */
  translation?: ReactNode;
  /** ISO-код языка оригинала (для метки «TR · оригинал»). */
  language?: string | null;
  /** Класс основного текста (шрифт/размер места использования). */
  className?: string;
}

// Иноязычная реплика: русский перевод — главным, оригинал под ним приглушённо с меткой языка.
export const TranslatedText: FC<ITranslatedTextProps> = ({ text, translation, language, className }) => {
  if (!translation) return <span className={className}>{text}</span>;
  const code = foreignLanguageBadge(language);
  return (
    <span className={styles.root}>
      <span className={`${className ?? ''} ${styles.primary}`} title="Перевод на русский">{translation}</span>
      <span className={styles.original}>
        <span className={styles.tag}>{code ? `${code} · оригинал` : 'оригинал'}</span>
        {text}
      </span>
    </span>
  );
};
