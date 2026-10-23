import React from "react";
import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";
import { useUpdateStore } from "@/stores/updateStore";

/** Янтарная кнопка в шапке, пока обновление найдено и не поставлено. */
export const UpdatePill: React.FC = () => {
  const { t } = useTranslation();
  const version = useUpdateStore((s) =>
    s.status === "available" ? (s.update?.version ?? null) : null,
  );
  const openDialog = useUpdateStore((s) => s.openDialog);

  if (!version) return null;

  const label = t("shell.update.pill", { version });
  return (
    <button
      type="button"
      onClick={openDialog}
      title={label}
      aria-label={label}
      className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full border border-amber/40 bg-amber/10 px-2.5 py-1 text-xs font-medium text-amber transition-colors duration-200 hover:bg-amber/20 focus:outline-none focus-visible:ring-1 focus-visible:ring-amber motion-reduce:transition-none"
    >
      <Download className="h-3.5 w-3.5" strokeWidth={2} />
      <span className="hidden min-[900px]:inline">{label}</span>
    </button>
  );
};
