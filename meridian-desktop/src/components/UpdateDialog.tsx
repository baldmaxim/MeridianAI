import React from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useUpdateStore } from "@/stores/updateStore";

/** «Доступна версия X»: установка и перезапуск только по кнопке. */
export const UpdateDialog: React.FC = () => {
  const { t } = useTranslation();
  const update = useUpdateStore((s) => s.update);
  const open = useUpdateStore((s) => s.dialogOpen);
  const installing = useUpdateStore((s) => s.status === "installing");
  const installUpdate = useUpdateStore((s) => s.installUpdate);
  const dismiss = useUpdateStore((s) => s.dismiss);

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
          <Button disabled={installing} onClick={() => void installUpdate()}>
            {installing ? t("update.installing") : t("update.now")}
          </Button>
        </>
      }
    >
      <div className="space-y-2 text-sm text-text">
        <p>{t("update.text", { version: update.version })}</p>
        {update.body && (
          <p className="whitespace-pre-wrap text-mid-gray">{update.body}</p>
        )}
      </div>
    </Dialog>
  );
};
