import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAskChat } from "@/hooks/useAskChat";
import { useMeetingSources } from "@/hooks/useMeetingSources";
import { useRefineView } from "@/hooks/useRefineView";
import { useStoredChoice } from "@/hooks/useStoredChoice";
import { useMeetingStore } from "@/stores/meetingStore";
import { isResumable } from "@/lib/utils/meetingFormat";
import { DeleteMeetingDialog } from "./DeleteMeetingDialog";
import { DeviceErrorBanner } from "./DeviceErrorBanner";
import { InterruptedBanner } from "./InterruptedBanner";
import { LocalMeetingHeader } from "./LocalMeetingHeader";
import { LocalContextTab } from "./LocalContextTab";
import { LocalProtocolTab } from "./LocalProtocolTab";
import { MainChatPane } from "./MainChatPane";
import { MainViewSwitch, type MainViewOption } from "./MainViewSwitch";
import { NotesPane } from "./NotesPane";
import { SidePanel, type SidePanelTab } from "./SidePanel";
import { SourcesDropOverlay } from "./SourcesDropOverlay";
import { SpeakersPanel } from "./SpeakersPanel";
import { SystemSilentBanner } from "./SystemSilentBanner";
import {
  TranscriptModeToggle,
  type TranscriptMode,
} from "./TranscriptModeToggle";
import { TranscriptPane } from "./TranscriptPane";

type PanelTab = "transcript" | "context" | "protocol";
type MainView = "notes" | "chat";

const MAIN_VIEWS: readonly MainView[] = ["notes", "chat"];

interface LocalMeetingScreenProps {
  resuming: boolean;
  onResume: (id: string) => void;
}

/**
 * A meeting recorded here: notes or chat in the middle, the speakers, then
 * transcript/context/protocol aside.
 */
export const LocalMeetingScreen: React.FC<LocalMeetingScreenProps> = ({
  resuming,
  onResume,
}) => {
  const { t } = useTranslation();
  const details = useMeetingStore((s) => s.details);
  const loading = useMeetingStore((s) => s.detailsLoading);
  const loadError = useMeetingStore((s) => s.detailsError);
  const isActive = useMeetingStore(
    (s) => s.details !== null && s.active?.id === s.details.meeting.id,
  );
  const [tab, setTab] = useState<PanelTab>("transcript");
  const [mainView, setMainView] = useStoredChoice<MainView>(
    "meridian.localMeetingMainView",
    MAIN_VIEWS,
    "notes",
  );
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [mode, setMode] = useState<TranscriptMode>("refined");
  const serverMeetingId = details?.meeting.server_meeting_id ?? null;
  const meetingId = details?.meeting.id ?? null;
  const { view, reload } = useRefineView(
    serverMeetingId,
    details?.meeting.sync_state ?? "",
  );
  const sources = useMeetingSources({ meetingId, serverMeetingId });
  const chat = useAskChat(serverMeetingId);

  // Another meeting: back to the refined transcript.
  useEffect(() => {
    setMode("refined");
  }, [meetingId]);

  if (!details) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-sm text-muted">
        {loadError
          ? `${t("meetings.errors.loadFailed")}: ${loadError}`
          : loading
            ? t("meetings.view.loading")
            : t("meetings.view.notFound")}
      </div>
    );
  }

  const { meeting, segments, notes } = details;
  const refine =
    view && serverMeetingId !== null
      ? { status: view.refine_status ?? null, error: view.refine_error ?? null }
      : null;
  const refinedSegments =
    !isActive &&
    meeting.status === "stopped" &&
    view?.refine_status === "done" &&
    view.segments.length > 0
      ? view.segments
      : null;
  const tabs: SidePanelTab<PanelTab>[] = [
    { id: "transcript", label: t("meetings.view.tabTranscript") },
    { id: "context", label: t("meetings.view.tabContext") },
    { id: "protocol", label: t("meetings.view.tabProtocol") },
  ];
  const mainOptions: MainViewOption<MainView>[] = [
    { id: "notes", label: t("meetings.view.mainNotes") },
    { id: "chat", label: t("meetings.view.mainChat") },
  ];

  return (
    <div className="relative flex h-full flex-col">
      <LocalMeetingHeader
        meeting={meeting}
        resuming={resuming}
        onResume={onResume}
        onDelete={() => setConfirmDelete(true)}
        refine={refine}
      />
      <DeviceErrorBanner meetingId={meeting.id} />
      <SystemSilentBanner meetingId={meeting.id} />
      {meeting.status === "interrupted" && isResumable(meeting) && (
        <InterruptedBanner
          meeting={meeting}
          resuming={resuming}
          onResume={onResume}
        />
      )}

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col p-3">
          <MainViewSwitch
            options={mainOptions}
            value={mainView}
            onChange={setMainView}
          />
          {/* Both stay mounted: a note being typed and the chat survive a switch. */}
          <div
            hidden={mainView !== "notes"}
            className="flex min-h-0 flex-1 flex-col"
          >
            <NotesPane notes={notes} segments={segments} />
          </div>
          <div
            hidden={mainView !== "chat"}
            className="flex min-h-0 flex-1 flex-col"
          >
            <MainChatPane serverMeetingId={serverMeetingId} chat={chat} />
          </div>
        </div>
        <SpeakersPanel meeting={meeting} />
        <SidePanel tabs={tabs} active={tab} onChange={setTab}>
          {tab === "transcript" && (
            <>
              {refinedSegments && (
                <TranscriptModeToggle value={mode} onChange={setMode} />
              )}
              <TranscriptPane
                segments={segments}
                refined={
                  mode === "refined"
                    ? (refinedSegments ?? undefined)
                    : undefined
                }
                notes={notes}
                live={isActive}
                visible
              />
            </>
          )}
          {tab === "context" && (
            <LocalContextTab
              key={meeting.id}
              meeting={meeting}
              sources={sources}
              view={view}
              onReloadView={reload}
            />
          )}
          {tab === "protocol" && (
            <LocalProtocolTab serverMeetingId={serverMeetingId} />
          )}
        </SidePanel>
      </div>

      <SourcesDropOverlay active={sources.dragActive} />
      <DeleteMeetingDialog
        meetingId={meeting.id}
        title={meeting.title}
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
      />
    </div>
  );
};
