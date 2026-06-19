import { useCallback, useEffect, useRef, useState } from 'react';
import {
  startMultiChannelBatchStt, getMultiChannelBatchSttJob, cancelMultiChannelBatchSttJob,
  type MultiChannelBatchJob, type MultiChannelBatchSttRequest, type MultiChannelBatchJobStatus,
} from '../api/multiChannelBatchStt';

// Этап 9.5: polling-хук batch multi-channel STT.

const TERMINAL: MultiChannelBatchJobStatus[] = ['succeeded', 'failed', 'cancelled', 'expired'];
const POLL_MS = 1000;
const MAX_POLL_ERRORS = 5;

function errMessage(e: unknown): string {
  const a = e as { response?: { data?: { detail?: { message?: string } | string } } };
  const d = a?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && d.message) return d.message;
  return 'Не удалось выполнить запрос';
}

export function useMultiChannelBatchStt({ meetingId }: { meetingId: number | null }) {
  const [job, setJob] = useState<MultiChannelBatchJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const runningRef = useRef(false);
  const startingRef = useRef(false);
  const pollErrRef = useRef(0);

  const running = job ? !TERMINAL.includes(job.status) : false;

  const stopPolling = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);

  const poll = useCallback(async () => {
    const jid = jobIdRef.current;
    if (meetingId == null || !jid) return;
    try {
      const j = await getMultiChannelBatchSttJob(meetingId, jid);
      pollErrRef.current = 0;
      setJob(j);
      if (TERMINAL.includes(j.status)) { stopPolling(); runningRef.current = false; }
    } catch (e) {
      pollErrRef.current += 1;
      if (pollErrRef.current >= MAX_POLL_ERRORS) {
        stopPolling();
        runningRef.current = false;
        setError(errMessage(e));
      }
    }
  }, [meetingId, stopPolling]);

  const start = useCallback(async (body: MultiChannelBatchSttRequest) => {
    if (meetingId == null || runningRef.current || startingRef.current) return;
    startingRef.current = true;
    setError(null);
    setJob(null);
    try {
      const j = await startMultiChannelBatchStt(meetingId, body);
      jobIdRef.current = j.job_id;
      runningRef.current = !TERMINAL.includes(j.status);
      pollErrRef.current = 0;
      setJob(j);
      stopPolling();
      if (runningRef.current) timerRef.current = setInterval(poll, POLL_MS);
    } catch (e) {
      setError(errMessage(e));
    } finally {
      startingRef.current = false;
    }
  }, [meetingId, poll, stopPolling]);

  const cancel = useCallback(async () => {
    stopPolling();
    runningRef.current = false;
    const jid = jobIdRef.current;
    if (meetingId != null && jid) {
      try { await cancelMultiChannelBatchSttJob(meetingId, jid); } catch { /* ignore */ }
    }
    setJob((j) => (j ? { ...j, status: 'cancelled' } : j));
  }, [meetingId, stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    runningRef.current = false;
    jobIdRef.current = null;
    pollErrRef.current = 0;
    setJob(null);
    setError(null);
  }, [stopPolling]);

  // meetingId change / unmount → стоп polling
  useEffect(() => {
    return () => { stopPolling(); runningRef.current = false; };
  }, [meetingId, stopPolling]);

  return { job, running, error, start, cancel, reset };
}
