import React from "react";
import { useTranslation } from "react-i18next";
import { FileText } from "lucide-react";
import type { ViewDocument } from "@/bindings";

interface DocumentsPaneProps {
  documents: ViewDocument[];
}

/** Documents attached to a site meeting: name, type, pages. */
export const DocumentsPane: React.FC<DocumentsPaneProps> = ({ documents }) => {
  const { t } = useTranslation();
  if (documents.length === 0) {
    return (
      <p className="px-6 py-8 text-center text-sm text-muted">
        {t("meetings.server.documentsEmpty")}
      </p>
    );
  }
  return (
    <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto overscroll-contain px-4 py-3">
      {documents.map((doc, index) => {
        const type = doc.doc_type_label || doc.doc_type;
        return (
          <li
            key={index}
            className="flex items-start gap-3 rounded-xl border border-border bg-card px-3 py-2.5"
          >
            <FileText
              className="mt-0.5 h-4 w-4 shrink-0 text-logo-primary"
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <p className="break-words text-sm font-medium text-text">
                {doc.filename || t("meetings.server.documentUnnamed")}
              </p>
              <p className="flex flex-wrap gap-x-3 text-xs text-muted">
                {type && <span>{type}</span>}
                {doc.page_count !== null && (
                  <span className="font-mono tabular-nums">
                    {t("meetings.server.pages", { count: doc.page_count })}
                  </span>
                )}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
};
