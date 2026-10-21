import { useCallback, useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { useMeetingStore } from "@/stores/meetingStore";
import { isModelError } from "@/lib/utils/meetingFormat";

/**
 * Resumes a stopped / interrupted meeting. A failure shows a toast; model
 * errors carry a shortcut to the model settings.
 */
export const useResumeMeeting = (onOpenModelSettings: () => void) => {
  const { t } = useTranslation();
  const [resumingId, setResumingId] = useState<string | null>(null);

  const resume = useCallback(
    async (id: string) => {
      setResumingId(id);
      const error = await useMeetingStore.getState().resumeMeeting(id);
      setResumingId(null);
      if (error) {
        toast.error(t("meetings.errors.resumeFailed"), {
          description: error,
          action: isModelError(error)
            ? {
                label: t("meetings.errors.openModelSettings"),
                onClick: onOpenModelSettings,
              }
            : undefined,
        });
      }
    },
    [onOpenModelSettings, t],
  );

  return { resume, resumingId };
};
