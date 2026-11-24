import React from "react";
import { useTranslation } from "react-i18next";
import { splitTimecodes } from "@/lib/utils/timecodes";
import { AccentText } from "./AccentText";

interface TimecodeTextProps {
  text: string;
  onTimecode: (seconds: number) => void;
  /** The key numbers, sums and dates of the plain pieces are accents. */
  highlight?: boolean;
}

/** A text where every time ("12:34", "1:02:03") is a button that jumps there. */
export const TimecodeText: React.FC<TimecodeTextProps> = ({
  text,
  onTimecode,
  highlight = false,
}) => {
  const { t } = useTranslation();
  return (
    <>
      {splitTimecodes(text).map((part, index) =>
        part.seconds === null ? (
          <React.Fragment key={index}>
            {highlight ? <AccentText text={part.text} /> : part.text}
          </React.Fragment>
        ) : (
          <button
            key={index}
            type="button"
            aria-label={t("audioPlayer.seekTo", { time: part.text })}
            onClick={() => onTimecode(part.seconds as number)}
            className="inline cursor-pointer rounded-sm font-mono text-[0.85em] text-logo-primary underline-offset-2 hover:underline focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
          >
            {part.text}
          </button>
        ),
      )}
    </>
  );
};
