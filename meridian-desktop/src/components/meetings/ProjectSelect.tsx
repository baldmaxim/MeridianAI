import React from "react";
import { useTranslation } from "react-i18next";
import type { ProjectFilter, ProjectNode } from "@/lib/utils/library";

interface ProjectSelectProps {
  tree: ProjectNode[];
  totalCount: number;
  noProjectCount: number;
  filter: ProjectFilter;
  onChange: (filter: ProjectFilter) => void;
}

const withCount = (name: string, count: number): string =>
  count > 0 ? `${name} (${count})` : name;

const toValue = (filter: ProjectFilter): string => {
  switch (filter.kind) {
    case "all":
      return "all";
    case "none":
      return "none";
    case "customer":
      return `c:${filter.customerId}`;
    case "object":
      return `o:${filter.customerId}:${filter.objectId}`;
  }
};

const fromValue = (value: string): ProjectFilter => {
  const [kind, customer, object] = value.split(":");
  if (kind === "c") return { kind: "customer", customerId: Number(customer) };
  if (kind === "o") {
    return {
      kind: "object",
      customerId: Number(customer),
      objectId: Number(object),
    };
  }
  return kind === "none" ? { kind: "none" } : { kind: "all" };
};

/** The projects panel of a narrow window: one drop-down above the list. */
export const ProjectSelect: React.FC<ProjectSelectProps> = ({
  tree,
  totalCount,
  noProjectCount,
  filter,
  onChange,
}) => {
  const { t } = useTranslation();
  return (
    <label className="flex flex-col gap-1 text-xs text-muted min-[1000px]:hidden">
      <span>{t("meetings.library.projects")}</span>
      <select
        value={toValue(filter)}
        onChange={(e) => onChange(fromValue(e.target.value))}
        className="rounded-[10px] border border-border bg-surface px-2 py-2 text-sm text-text focus:border-logo-primary focus:outline-none"
      >
        <option value="all">
          {`${t("meetings.library.allMeetings")} (${totalCount})`}
        </option>
        <option value="none">
          {`${t("meetings.library.noProject")} (${noProjectCount})`}
        </option>
        {tree.map((customer) => (
          <optgroup key={customer.id} label={customer.name}>
            <option value={`c:${customer.id}`}>
              {withCount(customer.name, customer.count)}
            </option>
            {customer.objects.map((object) => (
              <option key={object.id} value={`o:${customer.id}:${object.id}`}>
                {withCount(object.name, object.count)}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
};
