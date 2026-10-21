import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Mic } from "lucide-react";
import type { SearchHit } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { useMeetingSearch } from "@/hooks/useMeetingSearch";
import {
  buildObjectOwners,
  buildProjectTree,
  findLocalForServer,
  matchesFilter,
  mergeLibrary,
  resolveCustomerId,
  type LibraryEntry,
} from "@/lib/utils/library";
import { useLibraryStore } from "@/stores/libraryStore";
import { useMeetingStore } from "@/stores/meetingStore";
import { LibraryBanners } from "./LibraryBanners";
import { LibraryHeader } from "./LibraryHeader";
import { LibraryList } from "./LibraryList";
import { ProjectSelect } from "./ProjectSelect";
import { ProjectsPanel } from "./ProjectsPanel";
import { SearchResults } from "./SearchResults";

interface LibraryScreenProps {
  resumingId: string | null;
  onNew: () => void;
  onOpenAccount: () => void;
  onResume: (id: string) => void;
}

/** "Встречи": local and site meetings in one list, projects, search. */
export const LibraryScreen: React.FC<LibraryScreenProps> = ({
  resumingId,
  onNew,
  onOpenAccount,
  onResume,
}) => {
  const { t } = useTranslation();
  const locals = useMeetingStore((s) => s.meetings);
  const listLoaded = useMeetingStore((s) => s.listLoaded);
  const listError = useMeetingStore((s) => s.listError);
  const snapshot = useLibraryStore((s) => s.snapshot);
  const loading = useLibraryStore((s) => s.loading);
  const loadError = useLibraryStore((s) => s.error);
  const filter = useLibraryStore((s) => s.filter);
  const [query, setQuery] = useState("");
  const search = useMeetingSearch(query);

  // The cache answers at once; the refresh from the server follows.
  useEffect(() => {
    const library = useLibraryStore.getState();
    void (async () => {
      await library.load(false);
      await library.load(true);
    })();
  }, []);

  const all = useMemo(
    () => mergeLibrary(locals, snapshot?.items ?? []),
    [locals, snapshot],
  );
  const tree = useMemo(
    () => buildProjectTree(snapshot?.projects ?? [], all),
    [snapshot, all],
  );
  const owners = useMemo(
    () => buildObjectOwners(snapshot?.projects ?? []),
    [snapshot],
  );
  const visible = useMemo(
    () => all.filter((entry) => matchesFilter(entry, filter, owners)),
    [all, filter, owners],
  );
  const noProjectCount = all.filter(
    (e) => resolveCustomerId(e, owners) === null,
  ).length;

  const openEntry = (entry: LibraryEntry) => {
    if (entry.local)
      void useMeetingStore.getState().openMeeting(entry.local.id);
    else if (entry.server) {
      useLibraryStore.getState().openServer(entry.server.meeting_id);
    }
  };

  const openHit = (hit: SearchHit) => {
    const meetings = useMeetingStore.getState();
    if (hit.kind === "local") {
      void meetings.openMeeting(hit.id);
      return;
    }
    const serverId = Number(hit.id);
    const local = findLocalForServer(
      meetings.meetings,
      snapshot?.items ?? [],
      serverId,
    );
    if (local) void meetings.openMeeting(local.id);
    else useLibraryStore.getState().openServer(serverId);
  };

  const setFilter = useLibraryStore.getState().setFilter;
  const loaded = listLoaded && (snapshot !== null || loadError !== null);
  const errorText = listError
    ? `${t("meetings.errors.listFailed")}: ${listError}`
    : null;

  let body: React.ReactNode;
  if (search.active) {
    body = <SearchResults search={search} onOpen={openHit} />;
  } else if (!loaded && all.length === 0) {
    body = <p className="text-sm text-muted">{t("meetings.list.loading")}</p>;
  } else if (all.length === 0) {
    body = (
      <div className="mx-auto mt-16 flex max-w-sm flex-col items-center gap-3 text-center">
        <Mic className="h-10 w-10 text-subtle" aria-hidden="true" />
        <p className="text-base font-semibold text-text">
          {t("meetings.list.emptyTitle")}
        </p>
        <p className="text-sm text-muted">{t("meetings.list.emptyHint")}</p>
        <Button variant="primary" onClick={onNew}>
          {t("meetings.list.new")}
        </Button>
      </div>
    );
  } else if (visible.length === 0) {
    body = (
      <p className="mt-10 text-center text-sm text-muted">
        {t("meetings.library.filterEmpty")}
      </p>
    );
  } else {
    body = (
      <LibraryList
        entries={visible}
        resumingId={resumingId}
        onOpen={openEntry}
        onResume={onResume}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <LibraryHeader
        query={query}
        onQueryChange={setQuery}
        refreshing={loading}
        onRefresh={() => void useLibraryStore.getState().load(true)}
        onNew={onNew}
      />
      <div className="flex min-h-0 flex-1">
        <ProjectsPanel
          tree={tree}
          totalCount={all.length}
          noProjectCount={noProjectCount}
          filter={filter}
          onChange={setFilter}
        />
        <div className="min-w-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="mx-auto flex max-w-3xl flex-col gap-3 px-5 py-4">
            <ProjectSelect
              tree={tree}
              totalCount={all.length}
              noProjectCount={noProjectCount}
              filter={filter}
              onChange={setFilter}
            />
            <LibraryBanners
              snapshot={snapshot}
              error={loadError}
              onOpenAccount={onOpenAccount}
            />
            {errorText && (
              <p className="rounded-xl bg-error/10 px-4 py-2.5 text-sm text-error">
                {errorText}
              </p>
            )}
            {body}
          </div>
        </div>
      </div>
    </div>
  );
};
