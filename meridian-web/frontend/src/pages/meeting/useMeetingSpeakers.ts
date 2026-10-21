import { useCallback, useEffect } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { getSpeakerRoles, putSpeakerRole } from '../../api/speakerRoles';
import { listSpeakerCorrections, putSpeakerCorrection, deleteSpeakerCorrection } from '../../api/speakerCorrections';
import { toPublicSpeakerSide, nextPublicSpeakerSide, type PublicSpeakerSide } from '../../lib/speakerSides';
import { segmentOverrideSide } from '../../lib/segmentCorrections';
import type { SpeakerSegmentCorrection, WSMessageToServer } from '../../types';

interface ISegmentCorrectionPatch {
  side?: PublicSpeakerSide | '';
  correctedSpeakerLabel?: string | null;
}

/**
 * Стороны, имена и исправления реплик спикеров встречи:
 * подгрузка persisted-данных при открытии встречи + сеттеры (optimistic + WS или REST fallback).
 * Встречу эти действия НЕ создают.
 */
export const useMeetingSpeakers = (
  currentMeetingId: number | null,
  sendJSON: (msg: WSMessageToServer) => void,
) => {
  // Этап 7: подтянуть persisted-стороны спикеров при открытии встречи (до live broadcast)
  useEffect(() => {
    const mid = currentMeetingId;
    if (mid == null) return;
    getSpeakerRoles(mid)
      .then((rows) => {
        const map: Record<string, PublicSpeakerSide> = {};
        const names: Record<string, string> = {};
        for (const r of rows) {
          const side = toPublicSpeakerSide(r.side);
          if (side) map[r.speaker_label] = side;
          if (r.display_name) names[r.speaker_label] = r.display_name;
        }
        useMeetingStore.getState().setSpeakerRoles(map);
        useMeetingStore.getState().setSpeakerNames(names);
      })
      .catch(() => {});  // тихо игнорируем — роли/имена подтянутся по WS
    // Этап 8: persisted segment-level коррекции
    listSpeakerCorrections(mid)
      .then((rows) => {
        const map: Record<string, SpeakerSegmentCorrection> = {};
        for (const r of rows) map[r.segment_key] = r;
        useMeetingStore.getState().setSpeakerCorrections(map);
      })
      .catch(() => {});
  }, [currentMeetingId]);

  // Этап 8.1: исправить ОДНУ реплику (side и/или corrected_speaker_label). Merge с существующей
  // коррекцией, оптимистично + REST. Пустой результат → delete. Встречу НЕ создаёт.
  const handleSetSegmentCorrection = useCallback(async (
    segmentKey: string,
    originalSpeaker: string,
    patch: ISegmentCorrectionPatch,
  ) => {
    const st = useMeetingStore.getState();
    const mid = st.currentMeetingId;
    if (mid == null || !segmentKey) return;
    const existing = st.speakerCorrections[segmentKey];
    const side: PublicSpeakerSide | '' = patch.side !== undefined
      ? patch.side
      : (toPublicSpeakerSide(existing?.side));
    const correctedLabel: string | null = patch.correctedSpeakerLabel !== undefined
      ? (patch.correctedSpeakerLabel || null)
      : (existing?.corrected_speaker_label ?? null);
    const prev = st.speakerCorrections;
    try {
      if (!side && !correctedLabel) {
        await deleteSpeakerCorrection(mid, segmentKey);
        const map = { ...prev };
        delete map[segmentKey];
        useMeetingStore.getState().setSpeakerCorrections(map);
      } else {
        const rows = await putSpeakerCorrection(mid, segmentKey, {
          side: side || '', corrected_speaker_label: correctedLabel,
          original_speaker_label: originalSpeaker,
        });
        const map: Record<string, SpeakerSegmentCorrection> = {};
        for (const r of rows) map[r.segment_key] = r;
        useMeetingStore.getState().setSpeakerCorrections(map);
      }
    } catch {
      useMeetingStore.getState().setError('Не удалось сохранить исправление реплики');
    }
  }, []);

  // Клик по бейджу реплики циклит сторону, сохраняя corrected_speaker_label.
  const handleCorrectSegment = useCallback((segmentKey: string, originalSpeaker: string) => {
    const current = segmentOverrideSide(useMeetingStore.getState().speakerCorrections, segmentKey);
    handleSetSegmentCorrection(segmentKey, originalSpeaker, { side: nextPublicSpeakerSide(current) });
  }, [handleSetSegmentCorrection]);

  // Единый сеттер стороны спикера: optimistic + WS (или REST fallback). Встречу НЕ создаёт.
  const handleSetSpeakerSide = useCallback(async (name: string, side: PublicSpeakerSide | '' | null) => {
    const label = name.trim();
    if (!label) return;
    const normalized = toPublicSpeakerSide(side);
    const st = useMeetingStore.getState();
    const prev = st.speakerRoles;
    const next: Record<string, string> = { ...prev };
    if (normalized) next[label] = normalized;
    else delete next[label];
    st.setSpeakerRoles(next);

    if (st.isConnected) {
      sendJSON({ type: 'set_speaker_role', name: label, side: normalized || '' });
    } else if (st.currentMeetingId != null) {
      try {
        await putSpeakerRole(st.currentMeetingId, label, { side: normalized || '' });
      } catch {
        useMeetingStore.getState().setSpeakerRoles(prev);  // откат optimistic
        useMeetingStore.getState().setError('Не удалось сохранить сторону спикера');
      }
    }
    // нет соединения и нет встречи → только локальный optimistic (встречу не создаём)
  }, [sendJSON]);

  // Имя спикера: optimistic + WS (или REST fallback). Сторону спикера сохраняем (шлём текущую).
  const handleSetSpeakerName = useCallback(async (name: string, displayName: string) => {
    const label = name.trim();
    if (!label) return;
    const trimmed = displayName.trim();
    const st = useMeetingStore.getState();
    const prev = st.speakerNames;
    const next: Record<string, string> = { ...prev };
    if (trimmed) next[label] = trimmed;
    else delete next[label];
    st.setSpeakerNames(next);

    const side = toPublicSpeakerSide(st.speakerRoles[label]);
    if (st.isConnected) {
      sendJSON({ type: 'set_speaker_role', name: label, side: side || '', display_name: trimmed });
    } else if (st.currentMeetingId != null) {
      try {
        await putSpeakerRole(st.currentMeetingId, label, { side: side || '', display_name: trimmed });
      } catch {
        useMeetingStore.getState().setSpeakerNames(prev);  // откат optimistic
        useMeetingStore.getState().setError('Не удалось сохранить имя спикера');
      }
    }
  }, [sendJSON]);

  // Число спикеров диаризации — per-meeting. Optimistic + WS (бэкенд персистит на встречу
  // и при активной записи перезапускает Speechmatics с новым значением).
  const handleMaxSpeakersChange = useCallback((n: number) => {
    const v = Math.max(2, Math.min(6, Math.round(n) || 3));
    useMeetingStore.getState().setMaxSpeakers(v);
    sendJSON({ type: 'change_settings', diarization_max_speakers: v });
  }, [sendJSON]);

  return {
    handleSetSegmentCorrection,
    handleCorrectSegment,
    handleSetSpeakerSide,
    handleSetSpeakerName,
    handleMaxSpeakersChange,
  };
};

export type TMeetingSpeakers = ReturnType<typeof useMeetingSpeakers>;
