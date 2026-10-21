import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { openUrl } from "@tauri-apps/plugin-opener";
import { ExternalLink, RotateCw } from "lucide-react";
import { commands, type MeetingInfo } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { useMeetingStore } from "@/stores/meetingStore";

interface MeetingSyncActionsProps {
  meeting: MeetingInfo;
}

/** "Retry" for a refused upload, "Open on site" for a synced meeting. */
export const MeetingSyncActions: React.FC<MeetingSyncActionsProps> = ({
  meeting,
}) => {
  const { t } = useTranslation();
  const [retrying, setRetrying] = useState(false);

  const handleRetry = async () => {
    setRetrying(true);
    const result = await commands.retryMeetingSync(meeting.id);
    setRetrying(false);
    if (result.status === "error") {
      toast.error(t("meetings.errors.retryFailed"), {
        description: result.error,
      });
      return;
    }
    void useMeetingStore.getState().openMeeting(meeting.id);
  };

  const handleOpen = async (url: string) => {
    try {
      await openUrl(url);
    } catch (e) {
      toast.error(t("meetings.errors.openSiteFailed"), {
        description: String(e),
      });
    }
  };

  const webUrl = meeting.web_url;
  return (
    <>
      {meeting.sync_state === "error" && (
        <Button
          variant="secondary"
          disabled={retrying}
          onClick={() => void handleRetry()}
          className="flex items-center gap-1.5"
        >
          <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
          {t("meetings.actions.retrySync")}
        </Button>
      )}
      {meeting.sync_state === "synced" && webUrl && (
        <Button
          variant="secondary"
          onClick={() => void handleOpen(webUrl)}
          className="flex items-center gap-1.5"
        >
          <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          {t("meetings.actions.openOnSite")}
        </Button>
      )}
    </>
  );
};
