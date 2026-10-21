import React from "react";
import { useTranslation } from "react-i18next";
import { Mic, Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useMeetingStore } from "@/stores/meetingStore";
import { MeetingCard } from "./MeetingCard";
import { SignInHint } from "./SignInHint";

interface MeetingListProps {
  resumingId: string | null;
  onNew: () => void;
  onOpenAccount: () => void;
  onResume: (id: string) => void;
}

export const MeetingList: React.FC<MeetingListProps> = ({
  resumingId,
  onNew,
  onOpenAccount,
  onResume,
}) => {
  const { t } = useTranslation();
  const meetings = useMeetingStore((s) => s.meetings);
  const listLoaded = useMeetingStore((s) => s.listLoaded);
  const listError = useMeetingStore((s) => s.listError);
  const openMeeting = useMeetingStore((s) => s.openMeeting);

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-mid-gray/20 bg-deep px-4 py-3">
        <h1 className="text-lg font-semibold text-text">
          {t("meetings.list.title")}
        </h1>
        <Button
          variant="primary"
          onClick={onNew}
          className="flex items-center gap-1.5"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          {t("meetings.list.new")}
        </Button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <SignInHint onOpenAccount={onOpenAccount} />
        {listError && (
          <p className="mb-3 rounded-lg bg-error/10 px-3 py-2 text-sm text-error">
            {t("meetings.errors.listFailed")}: {listError}
          </p>
        )}
        {!listLoaded && (
          <p className="text-sm text-muted">{t("meetings.list.loading")}</p>
        )}
        {listLoaded && meetings.length === 0 && !listError && (
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
        )}
        <div className="mx-auto flex max-w-3xl flex-col gap-2">
          {meetings.map((meeting) => (
            <MeetingCard
              key={meeting.id}
              meeting={meeting}
              resuming={resumingId === meeting.id}
              onOpen={(id) => void openMeeting(id)}
              onResume={onResume}
            />
          ))}
        </div>
      </div>
    </div>
  );
};
