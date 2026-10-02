import { useMemo } from 'react';
import { useMeetingStore } from '../store/meetingStore';
import { toPublicSpeakerSide } from '../lib/speakerSides';

// Без диаризации у всех реплик одна метка — привязывать сторону не к чему.
const NO_LABEL = new Set(['', 'unknown_speaker']);
// «Кто это?» спрашиваем только после стольких реплик голоса — сначала даём шанс кнопке.
const ASK_AFTER_REPLICAS = 4;
const PHRASE_MAX = 90;

export interface ISpeakerSideSummary {
  labels: string[];
  selfCount: number;
  opponentCount: number;
  unassigned: string[];
  calibrated: boolean;
  ask: { label: string; phrase: string } | null;
}

/**
 * Сводка сторон голосов текущей сессии распознавания (сообщения начиная с sinceIndex):
 * провайдер нумерует голоса заново на каждом старте, старые метки не считаем.
 * Реплика — серия подряд идущих сообщений одной метки (Speechmatics коммитит пословно).
 */
export const useSpeakerSideSummary = (sinceIndex: number): ISpeakerSideSummary => {
  const messages = useMeetingStore((s) => s.messages);
  const speakerRoles = useMeetingStore((s) => s.speakerRoles);

  return useMemo(() => {
    const replicas = new Map<string, number>();
    const firstText = new Map<string, string[]>();
    let prev = '';
    for (const m of messages.slice(Math.min(sinceIndex, messages.length))) {
      const label = m.speaker || '';
      if (NO_LABEL.has(label) || !m.text?.trim()) continue;
      if (label !== prev) replicas.set(label, (replicas.get(label) || 0) + 1);
      if (replicas.get(label) === 1) firstText.set(label, [...(firstText.get(label) || []), m.text.trim()]);
      prev = label;
    }
    const labels = Array.from(replicas.keys());
    const sideOf = (l: string) => toPublicSpeakerSide(speakerRoles[l]);
    const selfCount = labels.filter((l) => sideOf(l) === 'self').length;
    const opponentCount = labels.filter((l) => sideOf(l) === 'opponent').length;
    const unassigned = labels.filter((l) => sideOf(l) === '');
    const askLabel = unassigned.find((l) => (replicas.get(l) || 0) >= ASK_AFTER_REPLICAS);
    let ask: ISpeakerSideSummary['ask'] = null;
    if (askLabel) {
      const text = (firstText.get(askLabel) || []).join(' ');
      ask = { label: askLabel, phrase: text.length > PHRASE_MAX ? `${text.slice(0, PHRASE_MAX)}…` : text };
    }
    return {
      labels,
      selfCount,
      opponentCount,
      unassigned,
      calibrated: labels.length > 0 && unassigned.length === 0 && selfCount > 0 && opponentCount > 0,
      ask,
    };
  }, [messages, speakerRoles, sinceIndex]);
};
