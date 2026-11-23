import { useMemo } from 'react';
import { useMeetingStore } from '../../store/meetingStore';
import { toPublicSpeakerSide } from '../../lib/speakerSides';

export interface ISpeakerList {
  /** Метки спикеров в стабильном порядке (по имени), чтобы строки не «прыгали» при назначении. */
  speakers: string[];
  assignedCount: number;
  unassignedCount: number;
}

/** Все распознанные спикеры встречи (реплики, дерево, стороны, имена) — те же источники, что и раньше. */
export const useSpeakerList = (): ISpeakerList => {
  const turns = useMeetingStore((s) => s.turns);
  const messages = useMeetingStore((s) => s.messages);
  const committedSegments = useMeetingStore((s) => s.committedSegments);
  const treeUnassigned = useMeetingStore((s) => s.treeUnassigned);
  const speakerRoles = useMeetingStore((s) => s.speakerRoles);
  const speakerNames = useMeetingStore((s) => s.speakerNames);

  const speakers = useMemo(() => {
    const set = new Set<string>();
    turns.forEach((t) => t.speaker && set.add(t.speaker));
    messages.forEach((m) => m.speaker && set.add(m.speaker));
    committedSegments.forEach((s) => { if (s.speaker) set.add(s.speaker); });
    treeUnassigned.forEach((n) => n && set.add(n));
    Object.keys(speakerRoles).forEach((n) => n && set.add(n));
    Object.keys(speakerNames).forEach((n) => n && set.add(n));
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'ru', { numeric: true }));
  }, [turns, messages, committedSegments, treeUnassigned, speakerRoles, speakerNames]);

  const assignedCount = speakers.filter((s) => toPublicSpeakerSide(speakerRoles[s]) !== '').length;
  return { speakers, assignedCount, unassignedCount: speakers.length - assignedCount };
};
