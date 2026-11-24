import React from "react";
import { highlightSegments } from "@/lib/utils/highlight";

interface AccentTextProps {
  text: string;
}

/** A text where the key numbers, sums, terms and dates are accents. */
export const AccentText: React.FC<AccentTextProps> = ({ text }) => (
  <>
    {highlightSegments(text).map((part, index) =>
      part.mark ? (
        <mark
          key={index}
          className="rounded-sm bg-amber/25 px-0.5 font-medium text-inherit[box-decoration-break:clone]"
        >
          {part.text}
        </mark>
      ) : (
        <React.Fragment key={index}>{part.text}</React.Fragment>
      ),
    )}
  </>
);
