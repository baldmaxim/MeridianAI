import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { parseNotesBody } from "@/lib/changelog";
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

  const notes = update.body ? parseNotesBody(update.body) : [];

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
        {notes.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted">
              {t("update.notesFor", { version: update.version })}
            </p>
            <ul className="max-h-48 list-disc space-y-1 overflow-y-auto overscroll-contain rounded-lg bg-deep p-3 pl-7 text-mid-gray">
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Dialog>
  );
};
