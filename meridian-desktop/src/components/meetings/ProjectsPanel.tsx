import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";
import type { ProjectFilter, ProjectNode } from "@/lib/utils/library";
import { ProjectRow } from "./ProjectRow";

interface ProjectsPanelProps {
  tree: ProjectNode[];
  totalCount: number;
  noProjectCount: number;
  filter: ProjectFilter;
  onChange: (filter: ProjectFilter) => void;
}

/** Left panel: all meetings, no project, customers with their objects. */
export const ProjectsPanel: React.FC<ProjectsPanelProps> = ({
  tree,
  totalCount,
  noProjectCount,
  filter,
  onChange,
}) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggle = (id: number) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const activeCustomerId =
    filter.kind === "customer" || filter.kind === "object"
      ? filter.customerId
      : null;

  return (
    <nav
      aria-label={t("meetings.library.projects")}
      className="hidden w-[240px] shrink-0 flex-col gap-1 overflow-y-auto overscroll-contain border-e border-border bg-deep px-3 py-4 min-[1000px]:flex"
    >
      <h2 className="mb-1 px-2.5 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
        {t("meetings.library.projects")}
      </h2>
      <div className="flex">
        <ProjectRow
          label={t("meetings.library.allMeetings")}
          count={totalCount}
          active={filter.kind === "all"}
          onClick={() => onChange({ kind: "all" })}
        />
      </div>
      <div className="flex">
        <ProjectRow
          label={t("meetings.library.noProject")}
          count={noProjectCount}
          active={filter.kind === "none"}
          onClick={() => onChange({ kind: "none" })}
        />
      </div>
      {tree.map((customer, index) => {
        const firstEmpty =
          customer.count === 0 && index > 0 && tree[index - 1].count > 0;
        const open =
          expanded.has(customer.id) || activeCustomerId === customer.id;
        return (
          <div key={customer.id} className="flex flex-col gap-1">
            {firstEmpty && (
              <div
                role="separator"
                className="mt-2 flex items-center gap-2 px-2.5 font-mono text-[10px] uppercase tracking-wider text-muted"
              >
                <span className="h-px flex-1 bg-border" aria-hidden="true" />
                {t("meetings.library.noMeetings")}
                <span className="h-px flex-1 bg-border" aria-hidden="true" />
              </div>
            )}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => toggle(customer.id)}
                aria-expanded={open}
                aria-label={t("meetings.library.toggleObjects", {
                  name: customer.name,
                })}
                disabled={customer.objects.length === 0}
                className="flex h-7 w-6 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted transition-colors duration-200 hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary disabled:cursor-default disabled:opacity-30 motion-reduce:transition-none"
              >
                <ChevronRight
                  className={`h-4 w-4 transition-transform duration-200 motion-reduce:transition-none ${
                    open ? "rotate-90" : ""
                  }`}
                  aria-hidden="true"
                />
              </button>
              <ProjectRow
                label={customer.name}
                count={customer.count}
                folder={open ? "open" : "closed"}
                active={
                  filter.kind === "customer" &&
                  filter.customerId === customer.id
                }
                onClick={() => {
                  setExpanded((current) => new Set(current).add(customer.id));
                  onChange({ kind: "customer", customerId: customer.id });
                }}
              />
            </div>
            {open &&
              customer.objects.map((object) => (
                <div key={object.id} className="ms-7 flex">
                  <ProjectRow
                    indented
                    folder="closed"
                    label={object.name}
                    count={object.count}
                    active={
                      filter.kind === "object" && filter.objectId === object.id
                    }
                    onClick={() =>
                      onChange({
                        kind: "object",
                        customerId: customer.id,
                        objectId: object.id,
                      })
                    }
                  />
                </div>
              ))}
          </div>
        );
      })}
    </nav>
  );
};
