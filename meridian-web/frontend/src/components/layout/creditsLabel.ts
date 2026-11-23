import type { IElevenLabsUsage } from '../../api/usage';

const fmt = (n: number): string => n.toLocaleString('ru-RU');

/** «2026-12-05» → «05.12» */
const fmtReset = (iso: string): string => {
  const [, m, d] = iso.split('-');
  return d && m ? `${d}.${m}` : iso;
};

/** Текст остатка кредитов ElevenLabs: подпись/title кольца в шапке и строка в панели «Лимиты». */
export const buildCreditsLabel = (u: IElevenLabsUsage): string => {
  const base = `ElevenLabs: осталось ${fmt(u.remaining)} из ${fmt(u.limit)} кредитов`;
  return u.next_reset ? `${base} · сброс ${fmtReset(u.next_reset)}` : base;
};
