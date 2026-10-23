import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useMeetingStore } from "@/stores/meetingStore";
import { useUpdateStore } from "@/stores/updateStore";

/** «Доступна версия X»: установка и перезапуск только по кнопке и не во время записи. */
export const UpdateDialog: React.FC = () => {
  const { t } = useTranslation();
  const update = useUpdateStore((s) => s.update);
  const open = useUpdateStore((s) => s.dialogOpen);
  const installing = useUpdateStore((s) => s.status === "installing");
  const error = useUpdateStore((s) => s.error);
  const installUpdate = useUpdateStore((s) => s.installUpdate);
  const dismiss = useUpdateStore((s) => s.dismiss);
  const recording = useMeetingStore((s) => s.active !== null);

  if (!update) return null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) dismiss();
      }}
      title={t("update.title", { version: update.version })}
      closeLabel={t("common.close")}
      dismissible={!installing}
      contentFades={false}
      footer={
        <>
          <Button variant="secondary" disabled={installing} onClick={dismiss}>
            {t("update.later")}
          </Button>
          <Button
            disabled={installing || recording}
            onClick={() => void installUpdate()}
          >
            {installing ? t("update.installing") : t("update.now")}
          </Button>
        </>
      }
    >
      <div className="space-y-2 text-sm text-text">
        <p className="font-mono text-xs text-mid-gray">
          {t("update.versions", {
            current: update.currentVersion,
            next: update.version,
          })}
        </p>
        <p>{t("update.text", { version: update.version })}</p>
        {recording && <p className="text-amber">{t("update.recordingHint")}</p>}
        {error && (
          <p className="text-error">{t("update.installFailed", { error })}</p>
        )}
        {update.body && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted">
              {t("update.notes")}
            </p>
            <p className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-deep p-3 text-mid-gray">
              {update.body}
            </p>
          </div>
        )}
      </div>
    </Dialog>
  );
};
