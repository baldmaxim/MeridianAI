// Единое отображаемое имя встречи для списков/карточек.
// Совпадает по духу с buildDefaultMeetingName в MeetingPage (Заказчик_Объект_Дата),
// чтобы список не показывал «Без названия» у встреч без явно заданного title.

function formatDmy(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export interface MeetingNameFields {
  title?: string | null;
  meeting_topic?: string | null;
  customer_name?: string | null;
  object_name?: string | null;
  started_at?: string | null;
}

/** title → тема → «Заказчик_Объект_Дата» → «Встреча ДД.ММ.ГГГГ» → «Без названия». */
export function meetingDisplayName(m: MeetingNameFields): string {
  if (m.title && m.title.trim()) return m.title.trim();
  if (m.meeting_topic && m.meeting_topic.trim()) return m.meeting_topic.trim();
  const date = m.started_at ? formatDmy(m.started_at) : '';
  const composed = [m.customer_name, m.object_name, date]
    .filter((p): p is string => !!p && !!p.trim())
    .join('_');
  if (composed) return composed;
  return date ? `Встреча ${date}` : 'Без названия';
}
