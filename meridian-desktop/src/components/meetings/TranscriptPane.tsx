import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Note, Segment } from "@/bindings";
import { SegmentRow } from "./SegmentRow";
import { TranscriptNoteRow } from "./TranscriptNoteRow";

interface TranscriptPaneProps {
  segments: Segment[];
  notes: Note[];
  /** Meeting is recording: stick to the bottom and animate new phrases. */
  live: boolean;
  /** Tab state; changing it re-pins a live transcript to the bottom. */
  visible: boolean;
  className?: string;
}

type TimelineItem =
  | { kind: "segment"; time: number; segment: Segment }
  | { kind: "note"; time: number; note: Note };

const BOTTOM_THRESHOLD_PX = 48;

export const TranscriptPane: React.FC<TranscriptPaneProps> = ({
  segments,
  notes,
  live,
  visible,
  className = "",
}) => {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const stuckRef = useRef(live);
  const [atBottom, setAtBottom] = useState(true);

  const items = useMemo<TimelineItem[]>(() => {
    const merged: TimelineItem[] = [
      ...segments.map((segment) => ({
        kind: "segment" as const,
        time: segment.start_time,
        segment,
      })),
      ...notes.map((note) => ({
        kind: "note" as const,
        time: note.at_seconds,
        note,
      })),
    ];
    // Array.sort is stable: on a tie, phrases stay before notes.
    return merged.sort((a, b) => a.time - b.time);
  }, [segments, notes]);

  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  useEffect(() => {
    // A hidden pane has no height, so this is a no-op until it is shown again.
    if (live && stuckRef.current) scrollToBottom();
  }, [items.length, live, visible]);

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
            {items.map((item) =>
              item.kind === "segment" ? (
                <SegmentRow
                  key={item.segment.id}
                  segment={item.segment}
                  animate={live}
                />
              ) : (
                <TranscriptNoteRow key={item.note.id} note={item.note} />
              ),
            )}
          </div>
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
