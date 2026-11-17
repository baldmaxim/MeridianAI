import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { FilePlus2, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useTranscriptions } from "@/hooks/useTranscriptions";
import { TranscriptionRow } from "./TranscriptionRow";
import { TranscriptionView } from "./TranscriptionView";

/** «Расшифровка»: audio files go to the server and come back as a transcript. */
export const TranscriptionsScreen: React.FC = () => {
  const { t } = useTranslation();
  const { items, dragActive, pickFiles, remove } = useTranscriptions();
  const [openId, setOpenId] = useState<string | null>(null);

  // A removed file closes its transcript.
  const openItem = items?.find((item) => item.id === openId);
  if (openId !== null && openItem) {
    return <TranscriptionView id={openId} onBack={() => setOpenId(null)} />;
  }

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border bg-background px-4 py-3 sm:px-5">
        <h1 className="shrink-0 font-display text-2xl font-extrabold text-text">
          {t("transcriptions.title")}
        </h1>
        <Button
          variant="primary"
          className="ms-auto px-3 py-1.5 text-sm"
          onClick={() => void pickFiles()}
        >
          <span className="inline-flex items-center gap-2">
            <FilePlus2 className="h-4 w-4" aria-hidden="true" />
            {t("transcriptions.pick")}
          </span>
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border px-4 py-6 text-center">
            <UploadCloud className="h-7 w-7 text-muted" aria-hidden="true" />
            <p className="text-sm font-medium text-text">
              {t("transcriptions.dropZone")}
            </p>
            <p className="text-xs text-muted">{t("transcriptions.hint")}</p>
          </div>
          {items !== null && items.length === 0 && (
            <p className="py-4 text-center text-sm text-muted">
              {t("transcriptions.empty")}
            </p>
          )}
          {items !== null && items.length > 0 && (
            <ul className="flex flex-col gap-2">
              {items.map((item) => (
                <TranscriptionRow
                  key={item.id}
                  item={item}
                  onOpen={setOpenId}
                  onRemove={(id) => void remove(id)}
                />
              ))}
            </ul>
          )}
        </div>
      </div>
      {dragActive && (
        <div
          className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 border-2 border-dashed border-logo-primary bg-background/90 p-6 text-center"
          aria-hidden="true"
        >
          <UploadCloud className="h-8 w-8 text-logo-primary" />
          <p className="text-sm font-medium text-text">
            {t("transcriptions.dropHint")}
          </p>
        </div>
      )}
    </div>
  );
};
