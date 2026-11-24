import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getVersion } from "@tauri-apps/api/app";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { bundledReleaseNotes } from "@/lib/changelog";

/** Версия, при которой пользователь последний раз видел приложение. */
const LAST_SEEN_VERSION_KEY = "meridian.lastSeenVersion";

interface WhatsNewDialogProps {
  enabled: boolean;
  onShowAll: () => void;
}

/** Один раз после обновления: что нового в установленной версии. Первый запуск — молча. */
export const WhatsNewDialog: React.FC<WhatsNewDialogProps> = ({
  enabled,
  onShowAll,
}) => {
  const { t } = useTranslation();
  const [version, setVersion] = useState<string | null>(null);
  const [items, setItems] = useState<string[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void (async () => {
      try {
        const current = await getVersion();
        const seen = localStorage.getItem(LAST_SEEN_VERSION_KEY);
        localStorage.setItem(LAST_SEEN_VERSION_KEY, current);
        if (cancelled || !seen || seen === current) return;
        const notes = bundledReleaseNotes(current);
        if (notes.length === 0) return;
        setVersion(current);
        setItems(notes);
        setOpen(true);
      } catch (error) {
        console.warn("What's new check failed:", error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  if (!version) return null;

  return (
    <Dialog
      open={open}
      onOpenChange={setOpen}
      title={t("whatsNew.title", { version })}
      closeLabel={t("common.close")}
      contentFades={false}
      footer={
        <>
          <Button
            variant="secondary"
            onClick={() => {
              setOpen(false);
              onShowAll();
            }}
          >
            {t("whatsNew.all")}
          </Button>
          <Button onClick={() => setOpen(false)}>{t("whatsNew.ok")}</Button>
        </>
      }
    >
      <ul className="max-h-64 list-disc space-y-1 overflow-y-auto overscroll-contain pl-5 text-sm text-text">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </Dialog>
  );
};
