// Единый формат даты/времени по Москве (UTC+3) — явно, независимо от пояса браузера.
// Вид: «17.06.26 07:41 МСК».
export function formatMoscowDateTime(iso: string): string {
  const tz = { timeZone: 'Europe/Moscow' } as const;
  const d = new Date(iso);
  const date = d.toLocaleDateString('ru-RU', { ...tz, day: '2-digit', month: '2-digit', year: '2-digit' });
  const time = d.toLocaleTimeString('ru-RU', { ...tz, hour: '2-digit', minute: '2-digit' });
  return `${date} ${time} МСК`;
}
