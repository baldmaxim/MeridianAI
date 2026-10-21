import type { CSSProperties } from 'react';
import type { Suggestion, SuggestionTypeConfig } from '../../types';

/** Оформление типа подсказки: цвет (токен темы или значение из конфига типов) + тексты. */
export interface ISuggestionTypeStyle {
  badge: string;
  color: string;
  metaLabel?: string;
  actionLabel: string;
  secondaryAction?: string;
}

/** Метаданные структурированных карточек (label + цвет по токену темы). */
export const CARD_TYPE_META: Record<string, { label: string; color: string }> = {
  say_now: { label: 'Сказать', color: 'var(--accent-amber)' },
  ask: { label: 'Вопрос', color: 'var(--accent-green)' },
  counter: { label: 'Контраргумент', color: 'var(--accent-blue)' },
  risk: { label: 'Риск', color: 'var(--accent-red)' },
  fixation: { label: 'Зафиксировать', color: 'var(--accent-red)' },
  trade_concession: { label: 'Уступка в обмен', color: 'var(--accent-amber)' },
  pause: { label: 'Пауза', color: 'var(--text-secondary)' },
  clarify: { label: 'Уточнить', color: 'var(--accent-green)' },
  summarize: { label: 'Резюмировать', color: 'var(--accent-blue)' },
};

export const DEFAULT_TYPE_STYLES: Record<string, ISuggestionTypeStyle> = {
  priority: {
    badge: '✦ ПРИОРИТЕТ',
    color: 'var(--accent-amber)',
    metaLabel: 'Контекст',
    actionLabel: 'Использовать',
  },
  counter: {
    badge: '⇄ КОНТРАРГУМЕНТ',
    color: 'var(--accent-blue)',
    metaLabel: 'Триггер',
    actionLabel: 'Использовать',
    secondaryAction: 'Подробнее',
  },
  question: {
    badge: '? ВОПРОС-ЗАЦЕП',
    color: 'var(--accent-green)',
    metaLabel: 'Метод',
    actionLabel: 'Использовать',
  },
  risk: {
    badge: '⚠ РИСК',
    color: 'var(--accent-red)',
    metaLabel: 'Паттерн',
    actionLabel: 'Принял к сведению',
  },
};

export const buildTypeStyles = (customTypes: SuggestionTypeConfig[] | null): Record<string, ISuggestionTypeStyle> => {
  if (!customTypes) return DEFAULT_TYPE_STYLES;
  const result: Record<string, ISuggestionTypeStyle> = {};
  for (const t of customTypes) {
    if (!t.enabled) continue;
    result[t.key] = {
      badge: t.badge,
      color: t.color, // цвет из пользовательского конфига типов (данные)
      metaLabel: t.metaLabel,
      actionLabel: t.actionLabel,
      secondaryAction: t.secondaryAction,
    };
  }
  return Object.keys(result).length > 0 ? result : DEFAULT_TYPE_STYLES;
};

export const getTypeStyle = (
  suggestion: Suggestion,
  typeStyles: Record<string, ISuggestionTypeStyle>,
): ISuggestionTypeStyle => {
  if (suggestion.type && typeStyles[suggestion.type]) return typeStyles[suggestion.type];
  // Fallback: неизвестный тип — нейтральный серый стиль
  if (suggestion.type) {
    return {
      badge: suggestion.type.toUpperCase(),
      color: 'var(--text-secondary)',
      actionLabel: 'Принял к сведению',
    };
  }
  return typeStyles.priority || DEFAULT_TYPE_STYLES.priority;
};

/** CSS-переменная --c с цветом карточки: от неё в CSS считаются фон/рамка (color-mix). */
export const colorVar = (color: string): CSSProperties => ({ '--c': color } as CSSProperties);
