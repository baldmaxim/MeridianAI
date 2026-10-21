import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useSyncStore } from "@/stores/syncStore";
import {
  formatDayLabel,
  groupByDay,
  type LibraryEntry,
} from "@/lib/utils/library";
import { LibraryCard } from "./LibraryCard";

interface LibraryListProps {
  /** Sorted newest first. */
  entries: LibraryEntry[];
  resumingId: string | null;
  onOpen: (entry: LibraryEntry) => void;
  onResume: (id: string) => void;
}

/** Cards grouped by day: "Сегодня", "Вчера", "21 октября". */
export const LibraryList: React.FC<LibraryListProps> = ({
  entries,
  resumingId,
  onOpen,
  onResume,
}) => {
  const { t, i18n } = useTranslation();
  const syncingId = useSyncStore((s) => s.status?.syncing_meeting_id ?? null);
  const groups = useMemo(() => groupByDay(entries), [entries]);
  const now = new Date();

  return (
    <div className="flex flex-col gap-5">
      {groups.map((group) => (
        <section key={group.key} className="flex flex-col gap-2">
          <h2 className="font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
            {group.date
              ? formatDayLabel(group.date, now, i18n.language, {
                  today: t("meetings.library.today"),
                  yesterday: t("meetings.library.yesterday"),
                })
              : t("meetings.library.noDate")}
          </h2>
          {group.entries.map((entry) => (
            <LibraryCard
              key={entry.key}
              entry={entry}
              syncingId={syncingId}
              resuming={entry.local !== null && resumingId === entry.local.id}
              onOpen={onOpen}
              onResume={onResume}
            />
          ))}
        </section>
      ))}
    </div>
  );
};
