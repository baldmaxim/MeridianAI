import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Note, Segment, ViewSegment } from "@/bindings";
import {
  buildSpeakerColors,
  speakerColorClass,
} from "@/lib/utils/speakerColors";
import { useMeetingStore } from "@/stores/meetingStore";
import { RefinedSegmentRow } from "./RefinedSegmentRow";
import { SegmentRow } from "./SegmentRow";
import { TranscriptNoteRow } from "./TranscriptNoteRow";

interface TranscriptPaneProps {
  segments: Segment[];
  /** The server's refined phrases; when set they replace the local `segments`. */
  refined?: ViewSegment[];
  notes: Note[];
  /** Meeting is recording: stick to the bottom and animate new phrases. */
  live: boolean;
  /** Tab state; changing it re-pins a live transcript to the bottom. */
  visible: boolean;
  className?: string;
}

type TimelineItem =
  | { kind: "segment"; time: number; segment: Segment }
  | { kind: "refined"; time: number; segment: ViewSegment; index: number }
  | { kind: "note"; time: number; note: Note };

const BOTTOM_THRESHOLD_PX = 48;

export const TranscriptPane: React.FC<TranscriptPaneProps> = ({
  segments,
  refined,
  notes,
  live,
  visible,
  className = "",
}) => {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const stuckRef = useRef(live);
  const [atBottom, setAtBottom] = useState(true);
  // The phrase the server is hearing right now (online recognition).
  const partial = useMeetingStore((s) => (live ? s.partial : ""));

  const items = useMemo<TimelineItem[]>(() => {
    const phrases: TimelineItem[] = refined
      ? refined.map((segment, index) => ({
          kind: "refined" as const,
          time: segment.start_time ?? 0,
          segment,
          index,
        }))
      : segments.map((segment) => ({
          kind: "segment" as const,
          time: segment.start_time,
          segment,
        }));
    const merged: TimelineItem[] = [
      ...phrases,
      ...notes.map((note) => ({
        kind: "note" as const,
        time: note.at_seconds,
        note,
      })),
    ];
    // Array.sort is stable: on a tie, phrases stay before notes.
    return merged.sort((a, b) => a.time - b.time);
  }, [segments, refined, notes]);

  // Colors by first appearance of a speaker among the shown phrases.
  const colors = useMemo(
    () =>
      buildSpeakerColors(
        refined
          ? refined.map((s) => s.speaker_label)
          : segments.map((s) => s.voice ?? s.speaker),
      ),
    [segments, refined],
  );

  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  useEffect(() => {
    // A hidden pane has no height, so this is a no-op until it is shown again.
    if (live && stuckRef.current) scrollToBottom();
  }, [items.length, live, visible, partial]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const bottom =
      el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_THRESHOLD_PX;
    stuckRef.current = bottom;
    setAtBottom(bottom);
  };

  const handleJump = () => {
    stuckRef.current = true;
    scrollToBottom();
  };

  return (
    <div className={`relative min-h-0 flex-1 ${className}`}>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="h-full select-text overflow-y-auto overscroll-contain px-4 py-3"
      >
        {items.length === 0 ? (
          <p className="mt-10 text-center text-sm text-muted">
            {live
              ? t("meetings.transcript.emptyLive")
              : t("meetings.transcript.empty")}
          </p>
        ) : (
          <div className="flex flex-col gap-3">
            {items.map((item) => {
              switch (item.kind) {
                case "segment":
                  return (
                    <SegmentRow
                      key={item.segment.id}
                      segment={item.segment}
                      animate={live}
                      speakerClass={speakerColorClass(
                        colors,
                        item.segment.voice ?? item.segment.speaker,
                      )}
                    />
                  );
                case "refined":
                  return (
                    <RefinedSegmentRow
                      key={`refined-${item.index}`}
                      segment={item.segment}
                      speakerClass={speakerColorClass(
                        colors,
                        item.segment.speaker_label,
                      )}
                    />
                  );
                case "note":
                  return (
                    <TranscriptNoteRow key={item.note.id} note={item.note} />
                  );
              }
            })}
          </div>
        )}
        {partial && (
          <p className="mt-3 break-words ps-[4.625rem] text-sm italic text-muted">
            {partial}
          </p>
        )}
      </div>
      <button
        type="button"
        onClick={handleJump}
        tabIndex={live && !atBottom ? 0 : -1}
        aria-hidden={!(live && !atBottom)}
        className={`absolute bottom-3 start-1/2 -translate-x-1/2 cursor-pointer rounded-full bg-background-ui px-3 py-1 text-xs font-medium text-white shadow-lg transition-opacity duration-200 motion-reduce:transition-none ${
          live && !atBottom ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      >
        {t("meetings.transcript.jumpToNew")}
      </button>
    </div>
  );
};
