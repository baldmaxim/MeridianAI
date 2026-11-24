import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { openUrl } from "@tauri-apps/plugin-opener";
import {
  ChevronLeft,
  Database,
  ExternalLink,
  Loader2,
  Play,
} from "lucide-react";
import { commands } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { AudioPlayerBar } from "@/components/shared/AudioPlayerBar";
import { useAudioPlayer } from "@/hooks/useAudioPlayer";
import { useAskChat } from "@/hooks/useAskChat";
import { useMeetingSources } from "@/hooks/useMeetingSources";
import { useRefineView } from "@/hooks/useRefineView";
import { useStoredChoice } from "@/hooks/useStoredChoice";
import { useLibraryStore } from "@/stores/libraryStore";
import { useMeetingStore } from "@/stores/meetingStore";
import { useSyncStore } from "@/stores/syncStore";
import { formatDateChip, formatTimeRange } from "@/lib/utils/meetingFormat";
import { DateTimeChips } from "./DateTimeChips";
import { ServerContextTab } from "./ServerContextTab";
import { MainChatPane } from "./MainChatPane";
import { MainViewSwitch, type MainViewOption } from "./MainViewSwitch";
import { ProjectChip } from "./ProjectChip";
import { ProtocolPane } from "./ProtocolPane";
import { RefineStatusChip } from "./RefineStatusChip";
import { ServerTranscriptPane } from "./ServerTranscriptPane";
import { SidePanel, type SidePanelTab } from "./SidePanel";
import { SourcesDropOverlay } from "./SourcesDropOverlay";

type PanelTab = "transcript" | "context";
type MainView = "protocol" | "chat";

const MAIN_VIEWS: readonly MainView[] = ["protocol", "chat"];

interface ServerMeetingScreenProps {
  serverMeetingId: number;
}

/** A meeting of the site without a local copy: read-only. */
export const ServerMeetingScreen: React.FC<ServerMeetingScreenProps> = ({
  serverMeetingId,
}) => {
  const { t, i18n } = useTranslation();
  const { view, fromCache, loading, error, reload } = useRefineView(
    serverMeetingId,
    "",
  );
  // One player for the protocol and the transcript; its link is asked for once
  // per meeting (not on every reload of the view).
  const player = useAudioPlayer(serverMeetingId, commands.meetingAudioUrl);
  const onTimecode = player.url ? player.seek : undefined;
  const chat = useAskChat(serverMeetingId);
  const sources = useMeetingSources({ meetingId: null, serverMeetingId });
  const [tab, setTab] = useState<PanelTab>("transcript");
  const [mainView, setMainView] = useStoredChoice<MainView>(
    "meridian.serverMeetingMainView",
    MAIN_VIEWS,
    "protocol",
  );
  const closeServer = useLibraryStore((s) => s.closeServer);
  const serverUrl = useSyncStore((s) => s.account?.server_url);
  const [adopting, setAdopting] = useState(false);

  // "Continue in the app": the server hands the meeting over, the local copy
  // opens (LocalMeetingScreen takes over from this screen).
  const handleContinue = async () => {
    setAdopting(true);
    const error = await useMeetingStore
      .getState()
      .adoptServerMeeting(serverMeetingId);
    setAdopting(false);
    if (error) {
      toast.error(t("meetings.errors.resumeFailed"), { description: error });
    }
  };

  // The site's meeting page (as `meeting_web_url` in the backend).
  const handleOpenOnSite = async () => {
    if (!serverUrl) return;
    const url = `${serverUrl.replace(/\/+$/, "")}/meetings/${serverMeetingId}`;
    try {
      await openUrl(url);
    } catch (e) {
      toast.error(t("meetings.errors.openSiteFailed"), {
        description: String(e),
      });
    }
  };

  const back = (
    <button
      type="button"
      aria-label={t("meetings.actions.back")}
      title={t("meetings.actions.back")}
      onClick={closeServer}
      className="shrink-0 cursor-pointer rounded-lg p-1 text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
    >
      <ChevronLeft className="h-5 w-5" aria-hidden="true" />
    </button>
  );

  if (!view) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 items-center border-b border-border bg-background px-4 py-2">
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
  ];
  const mainOptions: MainViewOption<MainView>[] = [
    { id: "protocol", label: t("meetings.view.tabProtocol") },
    { id: "chat", label: t("meetings.view.mainChat") },
  ];
  const title =
    view.title?.trim() ||
    view.meeting_topic?.trim() ||
    t("meetings.library.untitled");

  return (
    <div className="relative flex h-full flex-col">
      <div className="shrink-0 border-b border-border bg-background px-4 py-2">
        <div className="flex items-center gap-2">
          {back}
          <h1 className="min-w-0 truncate px-2 text-lg font-semibold text-text">
            {title}
          </h1>
          {serverUrl && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void handleOpenOnSite()}
              className="flex shrink-0 items-center gap-1.5"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              {t("meetings.actions.openOnSite")}
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            disabled={adopting}
            onClick={() => void handleContinue()}
            className="flex shrink-0 items-center gap-1.5"
          >
            {adopting ? (
              <Loader2
                className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
            ) : (
              <Play className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {adopting
              ? t("meetings.actions.resuming")
              : t("meetings.actions.continueInApp")}
          </Button>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 ps-9">
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
          {view.source === "desktop" && (
            <RefineStatusChip
              status={view.refine_status}
              error={view.refine_error}
            />
          )}
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

      <AudioPlayerBar player={player} />

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col p-3">
          <MainViewSwitch
            options={mainOptions}
            value={mainView}
            onChange={setMainView}
          />
          <div
            hidden={mainView !== "protocol"}
            className="flex min-h-0 flex-1 flex-col"
          >
            <section
              aria-label={t("meetings.view.tabProtocol")}
              className="flex min-h-0 flex-1 flex-col rounded-2xl border border-border bg-surface"
            >
              <h2 className="shrink-0 px-4 pt-3 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
                {t("meetings.view.tabProtocol")}
              </h2>
              <ProtocolPane
                markdown={view.protocol_markdown}
                status={view.finalization_status}
                loading={loading}
                error={null}
                onReload={reload}
                className="px-2"
                structured={view}
                onTimecode={onTimecode}
              />
            </section>
          </div>
          <div
            hidden={mainView !== "chat"}
            className="flex min-h-0 flex-1 flex-col"
          >
            <MainChatPane serverMeetingId={serverMeetingId} chat={chat} />
          </div>
        </div>
        <SidePanel tabs={tabs} active={tab} onChange={setTab}>
          {tab === "transcript" && (
            <ServerTranscriptPane segments={view.segments} player={player} />
          )}
          {tab === "context" && (
            <ServerContextTab
              view={view}
              serverMeetingId={serverMeetingId}
              sources={sources}
              onReloadView={reload}
            />
          )}
        </SidePanel>
      </div>
      <SourcesDropOverlay active={sources.dragActive} />
    </div>
  );
};
