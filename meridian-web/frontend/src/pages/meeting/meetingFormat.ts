// Форматирование даты и названия встречи для страницы встречи.

// Дата в формате ДД.ММ.ГГГГ.
export const formatDmy = (d: Date): string =>
  `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`;

// Дефолтное название встречи: «Заказчик_Объект_ДД.ММ.ГГГГ» (непустые части через «_»).
export const buildDefaultMeetingName = (customerName: string | null, objectName: string | null): string =>
  [customerName, objectName, formatDmy(new Date())].filter((p) => p && p.trim()).join('_');

// Дата начала записи встречи для показа в шапке (ISO → ДД.ММ.ГГГГ).
export const formatMeetingDate = (iso: string | null): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : formatDmy(d);
};
