import React from "react";
import { useTranslation } from "react-i18next";
import { Plus, RefreshCw, Search } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

interface LibraryHeaderProps {
  query: string;
  onQueryChange: (query: string) => void;
  refreshing: boolean;
  onRefresh: () => void;
  onNew: () => void;
}

/** Title, search field and the main actions of the library screen. */
export const LibraryHeader: React.FC<LibraryHeaderProps> = ({
  query,
  onQueryChange,
  refreshing,
  onRefresh,
  onNew,
}) => {
  const { t } = useTranslation();
  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-border bg-background px-5 py-3">
      <h1 className="shrink-0 font-display text-2xl font-extrabold text-text">
        {t("meetings.list.title")}
      </h1>
      <div className="relative min-w-0 max-w-md flex-1">
        <Search
          className="pointer-events-none absolute start-3 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted"
          aria-hidden="true"
        />
        <Input
          type="search"
          value={query}
          placeholder={t("meetings.library.searchPlaceholder")}
          aria-label={t("meetings.library.searchLabel")}
          clearLabel={t("meetings.library.clearSearch")}
          onChange={(e) => onQueryChange(e.target.value)}
          onClear={() => onQueryChange("")}
          className="w-full ps-9 font-normal!"
        />
      </div>
      <div className="ms-auto flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onRefresh}
          aria-label={t("meetings.library.refresh")}
          title={t("meetings.library.refresh")}
          className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-[10px] border border-border text-muted transition-colors duration-200 hover:bg-elevated hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
        >
          <RefreshCw
            className={`h-4 w-4 ${refreshing ? "animate-spin motion-reduce:animate-none" : ""}`}
            aria-hidden="true"
          />
        </button>
        <Button
          variant="primary"
          onClick={onNew}
          className="flex items-center gap-1.5"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          {t("meetings.list.new")}
        </Button>
      </div>
    </div>
  );
};
