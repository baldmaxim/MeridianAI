import React from "react";
import { CalendarDays, Clock } from "lucide-react";

interface DateTimeChipsProps {
  date: string;
  time: string;
}

const CHIP_CLASS =
  "inline-flex items-center gap-1.5 rounded-full border border-border bg-elevated px-2.5 py-0.5 font-mono text-xs tabular-nums text-muted";

/** Date and time of a meeting as two small chips. */
export const DateTimeChips: React.FC<DateTimeChipsProps> = ({ date, time }) => (
  <>
    {date && (
      <span className={CHIP_CLASS}>
        <CalendarDays className="h-3 w-3" aria-hidden="true" />
        {date}
      </span>
    )}
    {time && (
      <span className={CHIP_CLASS}>
        <Clock className="h-3 w-3" aria-hidden="true" />
        {time}
      </span>
    )}
  </>
);
