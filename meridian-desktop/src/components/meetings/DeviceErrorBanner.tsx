import React from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, X } from "lucide-react";
import { useMeetingStore } from "@/stores/meetingStore";

interface DeviceErrorBannerProps {
  meetingId: string;
}

/** Device failures reported by the backend while this meeting was recording. */
export const DeviceErrorBanner: React.FC<DeviceErrorBannerProps> = ({
  meetingId,
}) => {
  const { t } = useTranslation();
  const errors = useMeetingStore((s) => s.deviceErrors);
  const dismiss = useMeetingStore((s) => s.dismissDeviceError);
  const own = errors.filter((e) => e.meetingId === meetingId);
  if (own.length === 0) return null;

  return (
    <div className="flex flex-col gap-1 px-4 pt-2" role="alert">
      {own.map((error) => (
        <div
          key={error.key}
          className="flex items-start gap-2 rounded-lg bg-error/10 px-3 py-2 text-sm text-error"
        >
          <AlertTriangle
            className="mt-0.5 h-4 w-4 shrink-0"
            aria-hidden="true"
          />
          <p className="min-w-0 flex-1 break-words">
            {t("meetings.errors.deviceError", {
              channel:
                error.channel === "system"
                  ? t("meetings.errors.channelSystem")
                  : t("meetings.errors.channelMic"),
              message: error.message,
            })}
          </p>
          <button
            type="button"
            aria-label={t("meetings.errors.dismiss")}
            onClick={() => dismiss(error.key)}
            className="shrink-0 cursor-pointer opacity-80 hover:opacity-100"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
};
