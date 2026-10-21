import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMeetingStore } from "@/stores/meetingStore";
import { DeleteMeetingDialog } from "./DeleteMeetingDialog";
import { DeviceErrorBanner } from "./DeviceErrorBanner";
import { MeetingHeader } from "./MeetingHeader";
import { NotesPane } from "./NotesPane";
import { TranscriptPane } from "./TranscriptPane";

type Tab = "transcript" | "notes";

interface MeetingViewProps {
  resuming: boolean;
  onResume: (id: string) => void;
}

export const MeetingView: React.FC<MeetingViewProps> = ({
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
  const [tab, setTab] = useState<Tab>("transcript");
  const [confirmDelete, setConfirmDelete] = useState(false);

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
  const tabClass = (value: Tab) =>
    `flex-1 cursor-pointer border-b-2 px-3 py-2 text-sm font-medium focus:outline-none ${
      tab === value
        ? "border-logo-primary text-text"
        : "border-transparent text-muted hover:text-text"
    }`;

  return (
    <div className="flex h-full flex-col">
      <MeetingHeader
        meeting={meeting}
        resuming={resuming}
        onResume={onResume}
        onDelete={() => setConfirmDelete(true)}
      />
      <DeviceErrorBanner meetingId={meeting.id} />
      {meeting.status === "interrupted" && (
        <p className="mx-4 mt-2 rounded-lg bg-amber/10 px-3 py-2 text-sm text-amber">
          {t("meetings.interrupted.hint")}
        </p>
      )}

      <div
        role="tablist"
        className="flex shrink-0 border-b border-mid-gray/20 lg:hidden"
      >
        <button
          type="button"
          role="tab"
          aria-selected={tab === "transcript"}
          onClick={() => setTab("transcript")}
          className={tabClass("transcript")}
        >
          {t("meetings.view.tabTranscript")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "notes"}
          onClick={() => setTab("notes")}
          className={tabClass("notes")}
        >
          {t("meetings.view.tabNotes")}
        </button>
      </div>

      <div className="flex min-h-0 flex-1">
        <div
          className={`min-h-0 min-w-0 flex-1 flex-col lg:flex ${tab === "transcript" ? "flex" : "hidden"}`}
        >
          <TranscriptPane
            segments={segments}
            notes={notes}
            live={isActive}
            visible={tab === "transcript"}
          />
        </div>
        <div
          className={`min-h-0 min-w-0 flex-1 flex-col border-mid-gray/20 lg:flex lg:max-w-sm lg:border-s ${tab === "notes" ? "flex" : "hidden"}`}
        >
          <h2 className="hidden shrink-0 px-4 pt-3 text-xs font-medium uppercase tracking-wide text-muted lg:block">
            {t("meetings.notes.title")}
          </h2>
          <NotesPane notes={notes} segments={segments} />
        </div>
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
