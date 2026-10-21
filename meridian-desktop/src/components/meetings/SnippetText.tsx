import React from "react";
import { splitSnippet } from "@/lib/utils/library";

interface SnippetTextProps {
  /** Search snippet; the found words are in `[` `]`. */
  snippet: string;
}

/** The snippet with the found words highlighted (no raw HTML involved). */
export const SnippetText: React.FC<SnippetTextProps> = ({ snippet }) => (
  <>
    {splitSnippet(snippet).map((part, index) =>
      part.match ? (
        <mark
          key={index}
          className="rounded bg-logo-primary/25 px-0.5 text-text"
        >
          {part.text}
        </mark>
      ) : (
        <React.Fragment key={index}>{part.text}</React.Fragment>
      ),
    )}
  </>
);
