import React from "react";
import { useTranslation } from "react-i18next";
import type { ProjectCustomer } from "@/bindings";

interface ProjectPickerProps {
  customers: ProjectCustomer[];
  customerId: number | null;
  objectId: number | null;
  disabled?: boolean;
  onChange: (customerId: number | null, objectId: number | null) => void;
}

const SELECT_CLASS =
  "rounded-[10px] border border-border bg-surface px-2 py-2 text-sm text-text focus:border-logo-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-60";

const toId = (value: string): number | null => (value ? Number(value) : null);

/** Customer, then an object of that customer; both are optional. */
export const ProjectPicker: React.FC<ProjectPickerProps> = ({
  customers,
  customerId,
  objectId,
  disabled = false,
  onChange,
}) => {
  const { t } = useTranslation();
  const objects = customers.find((c) => c.id === customerId)?.objects ?? [];

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("meetings.project.customer")}</span>
        <select
          value={customerId ?? ""}
          disabled={disabled}
          onChange={(e) => onChange(toId(e.target.value), null)}
          className={SELECT_CLASS}
        >
          <option value="">{t("meetings.project.noCustomer")}</option>
          {customers.map((customer) => (
            <option key={customer.id} value={customer.id}>
              {customer.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("meetings.project.object")}</span>
        <select
          value={objectId ?? ""}
          disabled={disabled || customerId === null}
          onChange={(e) => onChange(customerId, toId(e.target.value))}
          className={SELECT_CLASS}
        >
          <option value="">{t("meetings.project.noObject")}</option>
          {objects.map((object) => (
            <option key={object.id} value={object.id}>
              {object.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
};
