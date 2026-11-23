import { useCallback, useEffect, useRef, useState } from 'react';
import { getMeetingAISettings, patchMeetingSpeakerIdentityHints } from '../../api/aiSettings';
import { useMeetingStore } from '../../store/meetingStore';
import {
  buildSpeakerIdentityHintsPatch, existingHintsToDrafts, isStrictSpeakerLabel,
} from '../../features/speakerIdentity/speakerIdentityHints';
import type {
  FunctionalRole, RawSpeakerIdentityHints, SpeakerSide,
} from '../../features/speakerIdentity/speakerIdentityTypes';
import type { PublicSpeakerSide } from '../../lib/speakerSides';

const SPEAKER_LABEL_CONFIDENCE = 0.95;

const toIdentitySide = (side: PublicSpeakerSide | ''): SpeakerSide =>
  side === 'self' ? 'our_side' : side === 'opponent' ? 'counterparty' : 'unknown';

const toPublic = (side: SpeakerSide): PublicSpeakerSide | '' =>
  side === 'our_side' ? 'self' : side === 'unknown' ? '' : 'opponent';

export interface ISpeakerRoles {
  /** Подтверждённая функциональная роль голоса ('unknown' — не задана). */
  roleOf: (label: string) => FunctionalRole;
  /** Роль можно хранить только для машинных меток (SM_0 / Speaker 1), не для имён. */
  canHaveRole: (label: string) => boolean;
  /** Сохранить роль голоса; сторона берётся из текущей публичной стороны («Мы»/«Оппонент»). */
  setRole: (label: string, role: FunctionalRole, side: PublicSpeakerSide | '') => void;
  ready: boolean;
}

/**
 * Роли голосов: те же speaker_identity_hints, что в «Роли и стороны» (REST PATCH, без PII).
 * Подгружает сохранённые hints встречи и автосохраняет роль при выборе. Остальные записи
 * (каналы, третья сторона, stable_ids) переносятся как есть — PATCH заменяет группы целиком.
 */
export const useSpeakerRoles = (meetingId: number | null, canEdit: boolean): ISpeakerRoles => {
  const [hints, setHints] = useState<RawSpeakerIdentityHints>(null);
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  const hintsRef = useRef<RawSpeakerIdentityHints>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    if (meetingId == null) return;
    let cancelled = false;
    getMeetingAISettings(meetingId)
      .then((data) => {
        if (cancelled) return;
        const loaded = (data.resolved?.speaker_identity_hints ?? null) as RawSpeakerIdentityHints;
        hintsRef.current = loaded;
        setHints(loaded);
        setLoadedFor(meetingId);
      })
      .catch(() => {});  // роли не критичны для встречи — панель остаётся без выбора роли
    return () => { cancelled = true; };
  }, [meetingId]);

  const ready = meetingId != null && loadedFor === meetingId && canEdit;

  const roleOf = useCallback((label: string): FunctionalRole => {
    const draft = existingHintsToDrafts(hints).find((d) => d.kind === 'speaker_label' && d.key === label);
    return draft?.functionalRole ?? 'unknown';
  }, [hints]);

  const setRole = useCallback((label: string, role: FunctionalRole, side: PublicSpeakerSide | '') => {
    if (meetingId == null || loadedFor !== meetingId || !isStrictSpeakerLabel(label)) return;
    const run = async () => {
      const current = hintsRef.current;
      const drafts = existingHintsToDrafts(current);
      const idx = drafts.findIndex((d) => d.kind === 'speaker_label' && d.key === label);
      const prevSide = idx >= 0 ? drafts[idx].side : 'unknown';
      // «Третья сторона» из прежних hints не переписываем, пока публичная сторона не менялась
      const nextSide = toPublic(prevSide) === side && side !== '' ? prevSide : toIdentitySide(side);
      if (idx >= 0) {
        drafts[idx] = { ...drafts[idx], side: nextSide, functionalRole: role };
      } else {
        drafts.push({
          kind: 'speaker_label', key: label, displayLabel: label, side: nextSide, functionalRole: role,
          confidence: SPEAKER_LABEL_CONFIDENCE, source: 'manual_correction', enabled: true,
        });
      }
      try {
        const patch = buildSpeakerIdentityHintsPatch(drafts, current);
        const data = await patchMeetingSpeakerIdentityHints(meetingId, patch as Record<string, unknown> | null);
        const saved = (data.resolved?.speaker_identity_hints ?? null) as RawSpeakerIdentityHints;
        hintsRef.current = saved;
        setHints(saved);
      } catch {
        useMeetingStore.getState().setError('Не удалось сохранить роль спикера');
      }
    };
    queue.current = queue.current.then(run);
  }, [meetingId, loadedFor]);

  const canHaveRole = useCallback((label: string) => isStrictSpeakerLabel(label), []);

  return { roleOf, canHaveRole, setRole, ready };
};
