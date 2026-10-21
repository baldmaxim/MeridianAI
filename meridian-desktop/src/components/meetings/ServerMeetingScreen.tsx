import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, Database } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useAskChat } from "@/hooks/useAskChat";
import { useMeetingView } from "@/hooks/useMeetingView";
import { useLibraryStore } from "@/stores/libraryStore";
import { formatDateChip, formatTimeRange } from "@/lib/utils/meetingFormat";
import { AskPane } from "./AskPane";
import { DateTimeChips } from "./DateTimeChips";
import { DocumentsPane } from "./DocumentsPane";
import { ServerContextTab } from "./ServerContextTab";
import { ProjectChip } from "./ProjectChip";
import { ProtocolPane } from "./ProtocolPane";
import { ServerTranscriptPane } from "./ServerTranscriptPane";
import { SidePanel, type SidePanelTab } from "./SidePanel";

type PanelTab = "transcript" | "context" | "documents" | "ask";

interface ServerMeetingScreenProps {
  serverMeetingId: number;
}

/** A meeting of the site without a local copy: read-only. */
export const ServerMeetingScreen: React.FC<ServerMeetingScreenProps> = ({
  serverMeetingId,
}) => {
  const { t, i18n } = useTranslation();
  const { view, fromCache, loading, error, reload } =
    useMeetingView(serverMeetingId);
  const chat = useAskChat(serverMeetingId);
  const [tab, setTab] = useState<PanelTab>("transcript");
  const closeServer = useLibraryStore((s) => s.closeServer);

  const back = (
    <button
      type="button"
      aria-label={t("meetings.actions.back")}
      title={t("meetings.actions.back")}
      onClick={closeServer}
      className="shrink-0 cursor-pointer rounded-lg p-1.5 text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
    >
      <ChevronLeft className="h-5 w-5" aria-hidden="true" />
    </button>
  );

  if (!view) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 items-center border-b border-border bg-background px-5 py-3">
          {back}
        </div>
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
          <p className={`text-sm ${error ? "text-error" : "text-muted"}`}>
            {error
              ? `${t("meetings.server.loadFailed")}: ${error}`
              : t("meetings.view.loading")}
          </p>
          {error && !loading && (
            <Button variant="primary" onClick={reload}>
              {t("meetings.server.retry")}
            </Button>
          )}
        </div>
      </div>
    );
  }

  const tabs: SidePanelTab<PanelTab>[] = [
    { id: "transcript", label: t("meetings.view.tabTranscript") },
    { id: "context", label: t("meetings.view.tabContext") },
    { id: "documents", label: t("meetings.view.tabDocuments") },
    { id: "ask", label: t("meetings.view.tabAsk") },
  ];
  const title =
    view.title?.trim() ||
    view.meeting_topic?.trim() ||
    t("meetings.library.untitled");

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border bg-background px-5 py-3">
        <div className="flex items-center gap-2">
          {back}
          <h1 className="min-w-0 truncate px-2 text-lg font-semibold text-text">
            {title}
          </h1>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1.5 ps-10">
          <DateTimeChips
            date={formatDateChip(view.started_at, i18n.language)}
            time={formatTimeRange(
              view.started_at,
              view.ended_at,
              i18n.language,
            )}
          />
          <ProjectChip
            showEmpty
            customerName={view.customer_name}
            objectName={view.object_name}
          />
          {fromCache && (
            <span
              title={t("meetings.server.fromCacheHint")}
              className="inline-flex items-center gap-1.5 rounded-full border border-amber/40 px-2.5 py-0.5 text-xs text-amber"
            >
              <Database className="h-3 w-3" aria-hidden="true" />
              {t("meetings.server.fromCache")}
            </span>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col p-4">
          <section
            aria-label={t("meetings.view.tabProtocol")}
            className="flex min-h-0 flex-1 flex-col rounded-2xl border border-border bg-surface"
          >
            <h2 className="shrink-0 px-5 pt-4 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
              {t("meetings.view.tabProtocol")}
            </h2>
            <ProtocolPane
              markdown={view.protocol_markdown}
              status={view.finalization_status}
              loading={loading}
              error={null}
              onReload={reload}
              className="px-2"
            />
          </section>
        </div>
        <SidePanel tabs={tabs} active={tab} onChange={setTab}>
          {tab === "transcript" && (
            <ServerTranscriptPane segments={view.segments} />
          )}
          {tab === "context" && <ServerContextTab view={view} />}
          {tab === "documents" && <DocumentsPane documents={view.documents} />}
          {tab === "ask" && (
            <AskPane serverMeetingId={serverMeetingId} chat={chat} />
          )}
        </SidePanel>
      </div>
    </div>
  );
};
