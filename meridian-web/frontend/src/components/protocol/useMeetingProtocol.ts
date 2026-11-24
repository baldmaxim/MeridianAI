import { useCallback, useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { getFinalizationStatus, getMeetingProtocol, retryFinalization } from '../../api/finalization';
import type { FinalizationStatus, MeetingProtocol } from '../../types';

const POLL_INTERVAL_MS = 3000;

export interface IMeetingProtocolState {
  status: FinalizationStatus;
  protocol: MeetingProtocol | null;
  /** Первый ответ статуса ещё не получен. */
  loading: boolean;
  /** Статус недоступен (запрос упал). */
  unavailable: boolean;
  /** Идёт запуск сборки/пересборки. */
  busy: boolean;
  actionError: string | null;
  /** Запустить (пере)сборку протокола. */
  rebuild: () => Promise<void>;
}

/**
 * Статус финализации и протокол встречи. Пока queued/running — опрос раз в 3 с;
 * протокол грузится при completed/partial с has_protocol. Смена refreshKey — перезапрос.
 * Прежний протокол остаётся на экране на время пересборки.
 */
export const useMeetingProtocol = (meetingId: number, refreshKey = 0): IMeetingProtocolState => {
  const [status, setStatus] = useState<FinalizationStatus>('not_started');
  const [protocol, setProtocol] = useState<MeetingProtocol | null>(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pollTick, setPollTick] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const s = await getFinalizationStatus(meetingId);
        if (!alive) return;
        setStatus(s.status);
        setUnavailable(false);
        setLoading(false);
        if (s.status === 'queued' || s.status === 'running') {
          timer = setTimeout(load, POLL_INTERVAL_MS);
        } else if ((s.status === 'completed' || s.status === 'partial') && s.has_protocol) {
          try {
            const p = await getMeetingProtocol(meetingId);
            if (alive) setProtocol(p);
          } catch { /* протокол не загрузился — останется прежний */ }
        }
      } catch {
        if (!alive) return;
        setUnavailable(true);
        setLoading(false);
      }
    };
    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [meetingId, refreshKey, pollTick]);

  const rebuild = useCallback(async () => {
    setBusy(true);
    setActionError(null);
    try {
      const s = await retryFinalization(meetingId);
      setStatus(s.status);
      setPollTick((t) => t + 1);
    } catch (e) {
      if (isAxiosError(e) && e.response?.status === 409) {
        setPollTick((t) => t + 1); // уже собирается — просто начинаем опрос
      } else {
        setActionError('Не удалось запустить сборку протокола');
      }
    } finally {
      setBusy(false);
    }
  }, [meetingId]);

  return { status, protocol, loading, unavailable, busy, actionError, rebuild };
};
