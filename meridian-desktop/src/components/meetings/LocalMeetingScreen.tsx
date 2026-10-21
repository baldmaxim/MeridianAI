import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAskChat } from "@/hooks/useAskChat";
import { useMeetingStore } from "@/stores/meetingStore";
import { AskPane } from "./AskPane";
import { DeleteMeetingDialog } from "./DeleteMeetingDialog";
import { DeviceErrorBanner } from "./DeviceErrorBanner";
import { LocalMeetingHeader } from "./LocalMeetingHeader";
import { LocalContextTab } from "./LocalContextTab";
import { LocalProtocolTab } from "./LocalProtocolTab";
import { NotesPane } from "./NotesPane";
import { SidePanel, type SidePanelTab } from "./SidePanel";
import { TranscriptPane } from "./TranscriptPane";

type PanelTab = "transcript" | "context" | "protocol" | "ask";

interface LocalMeetingScreenProps {
  resuming: boolean;
  onResume: (id: string) => void;
}

/** A meeting recorded here: notes in the middle, transcript/protocol/ask aside. */
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
  const [confirmDelete, setConfirmDelete] = useState(false);
  const serverMeetingId = details?.meeting.server_meeting_id ?? null;
  const chat = useAskChat(serverMeetingId);

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
  const tabs: SidePanelTab<PanelTab>[] = [
    { id: "transcript", label: t("meetings.view.tabTranscript") },
    { id: "context", label: t("meetings.view.tabContext") },
    { id: "protocol", label: t("meetings.view.tabProtocol") },
    { id: "ask", label: t("meetings.view.tabAsk") },
  ];

  return (
    <div className="flex h-full flex-col">
      <LocalMeetingHeader
        meeting={meeting}
        resuming={resuming}
        onResume={onResume}
        onDelete={() => setConfirmDelete(true)}
      />
      <DeviceErrorBanner meetingId={meeting.id} />
      {meeting.status === "interrupted" && (
        <p className="mx-5 mt-2 rounded-lg bg-amber/10 px-3 py-2 text-sm text-amber">
          {t("meetings.interrupted.hint")}
        </p>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col p-4">
          <NotesPane notes={notes} segments={segments} />
        </div>
        <SidePanel tabs={tabs} active={tab} onChange={setTab}>
          {tab === "transcript" && (
            <TranscriptPane
              segments={segments}
              notes={notes}
              live={isActive}
              visible
            />
          )}
          {tab === "context" && (
            <LocalContextTab key={meeting.id} meeting={meeting} />
          )}
          {tab === "protocol" && (
            <LocalProtocolTab serverMeetingId={serverMeetingId} />
          )}
          {tab === "ask" && (
            <AskPane serverMeetingId={serverMeetingId} chat={chat} />
          )}
        </SidePanel>
      </div>

      <DeleteMeetingDialog
        meetingId={meeting.id}
        title={meeting.title}
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
      />
    </div>
  );
};
