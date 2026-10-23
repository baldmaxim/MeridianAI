import React from "react";
import { useTranslation } from "react-i18next";
import {
  Calculator,
  FileSignature,
  FileText,
  ListChecks,
  Mail,
  Stamp,
  Tag,
  type LucideIcon,
} from "lucide-react";
import type { ServerDocument } from "@/bindings";
import { isSettled } from "@/hooks/useMeetingSources";

const TYPE_ICONS: Record<string, LucideIcon> = {
  letter: Mail,
  contract: FileSignature,
  supplement: FileSignature,
  estimate: Calculator,
  bor: Calculator,
  offer: Tag,
  specification: ListChecks,
  act: Stamp,
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}/;

const formatMetaDate = (value: string, language: string): string => {
  if (!ISO_DATE.test(value)) return value;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(language);
};

interface SourceRowProps {
  doc: ServerDocument;
  onToggle: (doc: ServerDocument, included: boolean) => void;
}

/** A document of the meeting: icon, name, detected type and tags, "in context". */
export const SourceRow: React.FC<SourceRowProps> = ({ doc, onToggle }) => {
  const { t, i18n } = useTranslation();
  const Icon = (doc.doc_type && TYPE_ICONS[doc.doc_type]) || FileText;
  const name = doc.name || t("meetings.sources.unnamed");
  const typeLabel = doc.doc_type_label || doc.doc_type;
  const meta = [
    doc.doc_meta?.number
      ? t("meetings.sources.number", { number: doc.doc_meta.number })
      : null,
    doc.doc_meta?.date
      ? formatMetaDate(doc.doc_meta.date, i18n.language)
      : null,
    doc.doc_meta?.counterparty_name || null,
    doc.page_count !== null
      ? t("meetings.sources.pages", { count: doc.page_count })
      : null,
  ].filter((part): part is string => Boolean(part));

  return (
    <li className="flex items-start gap-2.5 rounded-xl border border-border bg-card px-2.5 py-2">
      <Icon
        className="mt-0.5 h-4 w-4 shrink-0 text-logo-primary"
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-text" title={name}>
          {name}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          {doc.status === "error" ? (
            <span className="text-xs text-error">
              {t("meetings.sources.processingFailed")}
            </span>
          ) : typeLabel ? (
            <span className="rounded-full bg-logo-primary/15 px-2 py-0.5 text-[11px] font-medium text-text">
              {typeLabel}
            </span>
          ) : (
            !isSettled(doc) && (
              <span className="text-xs text-muted">
                {t("meetings.sources.detecting")}
              </span>
            )
          )}
          {doc.doc_tags.map((tag) => (
            <span
              key={tag.key}
              className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted"
            >
              {tag.label}
            </span>
          ))}
        </div>
        {meta.length > 0 && (
          <p
            className="mt-1 truncate text-xs text-muted"
            title={meta.join(" · ")}
          >
            {meta.join(" · ")}
          </p>
        )}
      </div>
      <label
        className="-m-1 flex shrink-0 cursor-pointer items-center p-1"
        title={t("meetings.sources.include")}
      >
        <input
          type="checkbox"
          checked={doc.included}
          onChange={(e) => onToggle(doc, e.target.checked)}
          aria-label={t("meetings.sources.include")}
          className="h-4 w-4 cursor-pointer accent-logo-primary"
        />
      </label>
    </li>
  );
};
