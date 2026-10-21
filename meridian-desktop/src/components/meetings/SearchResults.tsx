import React from "react";
import { useTranslation } from "react-i18next";
import type { SearchHit } from "@/bindings";
import type { MeetingSearchState } from "@/hooks/useMeetingSearch";
import { formatDateChip, formatTimeOfDay } from "@/lib/utils/meetingFormat";
import { SnippetText } from "./SnippetText";

interface SearchResultsProps {
  search: MeetingSearchState;
  onOpen: (hit: SearchHit) => void;
}

/** Search hits instead of the library list: title and the found passage. */
export const SearchResults: React.FC<SearchResultsProps> = ({
  search,
  onOpen,
}) => {
  const { t, i18n } = useTranslation();
  const { hits, loading, error } = search;

  if (error) {
    return (
      <p className="rounded-lg bg-error/10 px-3 py-2 text-sm text-error">
        {t("meetings.library.searchFailed")}: {error}
      </p>
    );
  }
  if (hits.length === 0) {
    return (
      <p className="mt-10 text-center text-sm text-muted">
        {loading
          ? t("meetings.library.searching")
          : t("meetings.library.searchEmpty")}
      </p>
    );
  }

  return (
    <ul
      aria-label={t("meetings.library.searchResults")}
      className="flex flex-col gap-2"
    >
      {hits.map((hit) => {
        const when = [
          formatDateChip(hit.started_at, i18n.language),
          formatTimeOfDay(hit.started_at, i18n.language),
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <li key={`${hit.kind}:${hit.id}`}>
            <button
              type="button"
              onClick={() => onOpen(hit)}
              className="flex w-full cursor-pointer flex-col gap-1 rounded-xl border border-border bg-card px-4 py-3 text-start transition-colors duration-200 hover:border-logo-primary/60 focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
            >
              <span className="min-w-0 break-words text-sm font-semibold text-text">
                {hit.title || t("meetings.library.untitled")}
              </span>
              <span className="line-clamp-3 break-words text-xs text-muted">
                <SnippetText snippet={hit.snippet} />
              </span>
              {when && (
                <span className="font-mono text-[11px] text-subtle">
                  {when}
                </span>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
};
