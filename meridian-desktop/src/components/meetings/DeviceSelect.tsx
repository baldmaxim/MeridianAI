import React from "react";
import { useTranslation } from "react-i18next";
import type { CaptureDevice } from "@/bindings";

interface DeviceSelectProps {
  label: string;
  /** Device id; empty string means "the default device". */
  value: string;
  devices: CaptureDevice[];
  disabled?: boolean;
  onChange: (id: string) => void;
}

export const DeviceSelect: React.FC<DeviceSelectProps> = ({
  label,
  value,
  devices,
  disabled = false,
  onChange,
}) => {
  const { t } = useTranslation();
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-mid-gray/60 bg-surface px-2 py-2 text-sm text-text focus:border-logo-primary focus:outline-none disabled:opacity-60"
      >
        <option value="">{t("meetings.newDialog.defaultDevice")}</option>
        {devices.map((device) => (
          <option key={device.id} value={device.id}>
            {device.name}
          </option>
        ))}
      </select>
    </label>
  );
};
