import React from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, X } from "lucide-react";
import { useMeetingStore } from "@/stores/meetingStore";

interface SystemSilentBannerProps {
  meetingId: string;
}

/** Computer sound of a recording online meeting is silent: the call app may use another device. */
export const SystemSilentBanner: React.FC<SystemSilentBannerProps> = ({
  meetingId,
}) => {
  const { t } = useTranslation();
  const visible = useMeetingStore(
    (s) =>
      s.silentMeetingId === meetingId &&
      s.active?.id === meetingId &&
      s.details?.meeting.id === meetingId &&
      s.details.meeting.capture_mode === "online",
  );
  const dismiss = useMeetingStore((s) => s.dismissSystemSilent);
  if (!visible) return null;

  return (
    <div className="px-4 pt-2" role="alert">
      <div className="flex items-start gap-2 rounded-lg bg-amber/10 px-3 py-2 text-sm text-amber">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <p className="min-w-0 flex-1 break-words">
          {t("meetings.errors.systemSilent")}
        </p>
        <button
          type="button"
          aria-label={t("meetings.errors.dismiss")}
          onClick={dismiss}
          className="shrink-0 cursor-pointer opacity-80 hover:opacity-100"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
};
