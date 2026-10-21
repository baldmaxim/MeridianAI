import React from "react";
import { useTranslation } from "react-i18next";
import type { LibrarySnapshot } from "@/bindings";

interface LibraryBannersProps {
  snapshot: LibrarySnapshot | null;
  /** The last refresh failed for another reason than being offline. */
  error: string | null;
  onOpenAccount: () => void;
}

const formatFetchedAt = (iso: string | null, locale: string): string | null => {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

const BANNER_CLASS =
  "flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-xl border px-4 py-2.5 text-sm";

/** Notices above the list: signed out, offline (cache), refresh failure. */
export const LibraryBanners: React.FC<LibraryBannersProps> = ({
  snapshot,
  error,
  onOpenAccount,
}) => {
  const { t, i18n } = useTranslation();
  if (!snapshot && !error) return null;

  const fetchedAt = formatFetchedAt(
    snapshot?.fetched_at ?? null,
    i18n.language,
  );
  return (
    <>
      {snapshot && !snapshot.signed_in && (
        <div className={`${BANNER_CLASS} border-border bg-card text-muted`}>
          <p className="min-w-0">{t("meetings.library.signedOut")}</p>
          <button
            type="button"
            onClick={onOpenAccount}
            className="shrink-0 cursor-pointer text-logo-primary underline-offset-2 hover:underline focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
          >
            {t("meetings.library.signIn")}
          </button>
        </div>
      )}
      {snapshot?.signed_in && snapshot.offline && (
        <p className={`${BANNER_CLASS} border-amber/40 bg-amber/10 text-amber`}>
          {fetchedAt
            ? t("meetings.library.offline", { time: fetchedAt })
            : t("meetings.library.offlineNoTime")}
        </p>
      )}
      {error && (
        <p className={`${BANNER_CLASS} border-error/40 bg-error/10 text-error`}>
          {t("meetings.errors.libraryFailed")}: {error}
        </p>
      )}
    </>
  );
};
