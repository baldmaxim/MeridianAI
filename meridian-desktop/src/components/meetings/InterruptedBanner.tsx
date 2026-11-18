import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { AlertTriangle, Play } from "lucide-react";
import type { MeetingInfo } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { useMeetingStore } from "@/stores/meetingStore";

interface InterruptedBannerProps {
  meeting: MeetingInfo;
  resuming: boolean;
  onResume: (id: string) => void;
}

/** An interrupted recording: continue it in the same meeting, or finish it. */
export const InterruptedBanner: React.FC<InterruptedBannerProps> = ({
  meeting,
  resuming,
  onResume,
}) => {
  const { t } = useTranslation();
  const [finishing, setFinishing] = useState(false);

  const handleFinish = async () => {
    setFinishing(true);
    const error = await useMeetingStore
      .getState()
      .finishInterrupted(meeting.id);
    setFinishing(false);
    if (error)
      toast.error(t("meetings.errors.finishFailed"), { description: error });
  };

  return (
    <div
      role="status"
      className="mx-5 mt-2 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-amber/10 px-3 py-2 text-sm text-amber"
    >
      <div className="flex min-w-0 flex-1 items-start gap-2">
        <AlertTriangle
          className="mt-0.5 h-4 w-4 shrink-0"
          aria-hidden="true"
        />
        <div className="min-w-0">
          <p className="font-medium">{t("meetings.interrupted.title")}</p>
          <p className="break-words">{t("meetings.interrupted.hint")}</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button
          variant="primary"
          disabled={resuming || finishing}
          onClick={() => onResume(meeting.id)}
          className="flex items-center gap-1.5"
        >
          <Play className="h-3.5 w-3.5" aria-hidden="true" />
          {resuming
            ? t("meetings.actions.resuming")
            : t("meetings.actions.resume")}
        </Button>
        <Button
          variant="secondary"
          disabled={resuming || finishing}
          onClick={() => void handleFinish()}
        >
          {t("meetings.interrupted.finish")}
        </Button>
      </div>
    </div>
  );
};
