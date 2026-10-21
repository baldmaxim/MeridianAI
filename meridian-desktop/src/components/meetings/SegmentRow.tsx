import React from "react";
import { useTranslation } from "react-i18next";
import type { Segment } from "@/bindings";
import { formatClock } from "@/lib/utils/meetingFormat";

interface SegmentRowProps {
  segment: Segment;
  animate: boolean;
}

const SIDE_CLASSES: Record<
  string,
  { label: string; text: string; bar: string }
> = {
  mic: { label: "mic", text: "text-amber", bar: "bg-amber" },
  system: { label: "system", text: "text-info", bar: "bg-info" },
  mixed: { label: "mixed", text: "text-muted", bar: "bg-subtle" },
};

export const SegmentRow: React.FC<SegmentRowProps> = ({ segment, animate }) => {
  const { t } = useTranslation();
  const side = SIDE_CLASSES[segment.channel] ?? SIDE_CLASSES.mixed;

  return (
    <div className={`flex gap-3 ${animate ? "meeting-enter" : ""}`}>
      <span className="w-12 shrink-0 pt-0.5 text-end font-mono text-xs tabular-nums text-muted">
        {formatClock(segment.start_time)}
      </span>
      <span
        className={`w-0.5 shrink-0 rounded-full ${side.bar}`}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <span className={`text-xs font-semibold ${side.text}`}>
          {t(`meetings.speaker.${side.label}`)}
        </span>
        <p className="break-words text-sm text-text">{segment.text}</p>
      </div>
    </div>
  );
};
