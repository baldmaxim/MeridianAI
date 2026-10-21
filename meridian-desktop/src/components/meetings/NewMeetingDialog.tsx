import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { commands, type CaptureDevices, type CaptureMode } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { useMeetingStore } from "@/stores/meetingStore";
import { formatTitleDate, isModelError } from "@/lib/utils/meetingFormat";
import { DeviceSelect } from "./DeviceSelect";

interface NewMeetingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenModelSettings: () => void;
}

export const NewMeetingDialog: React.FC<NewMeetingDialogProps> = ({
  open,
  onOpenChange,
  onOpenModelSettings,
}) => {
  const { t } = useTranslation();
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<CaptureMode>("in_person");
  const [devices, setDevices] = useState<CaptureDevices | null>(null);
  const [micId, setMicId] = useState("");
  const [systemId, setSystemId] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setTitle(
      t("meetings.newDialog.defaultTitle", {
        date: formatTitleDate(new Date()),
      }),
    );
    setMicId("");
    setSystemId("");
    setError(null);
    setStarting(false);
    setDevices(null);
    setMode("in_person");
    void commands.listCaptureDevices().then((result) => {
      if (cancelled) return;
      if (result.status === "ok") {
        setDevices(result.data);
        if (result.data.system_supported) setMode("online");
      } else {
        setError(result.error);
      }
    });
    return () => {
      cancelled = true;
    };
    // The default title is computed once per opening.
  }, [open]);

  const systemSupported = devices?.system_supported ?? false;

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    const failure = await useMeetingStore.getState().startMeeting({
      title: title.trim(),
      capture_mode: mode,
      mic_device_id: micId || null,
      system_device_id: mode === "online" && systemId ? systemId : null,
    });
    setStarting(false);
    if (failure) {
      setError(failure);
    } else {
      onOpenChange(false);
    }
  };

  const modeOption = (value: CaptureMode, label: string, disabled: boolean) => (
    <label
      className={`flex items-center gap-2 rounded-lg border p-2.5 text-sm ${
        mode === value
          ? "border-logo-primary bg-logo-primary/10"
          : "border-mid-gray/30"
      } ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
    >
      <input
        type="radio"
        name="capture-mode"
        value={value}
        checked={mode === value}
        disabled={disabled || starting}
        onChange={() => setMode(value)}
        className="accent-logo-primary"
      />
      {label}
    </label>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("meetings.newDialog.title")}
      closeLabel={t("meetings.newDialog.close")}
      dismissible={!starting}
      contentFades={false}
      footer={
        <>
          <Button
            variant="secondary"
            disabled={starting}
            onClick={() => onOpenChange(false)}
          >
            {t("meetings.actions.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={starting || devices === null}
            onClick={() => void handleStart()}
          >
            {starting
              ? t("meetings.newDialog.starting")
              : t("meetings.newDialog.start")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">
            {t("meetings.newDialog.titleLabel")}
          </span>
          <Input
            type="text"
            value={title}
            disabled={starting}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing && devices) {
                void handleStart();
              }
            }}
          />
        </label>

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm text-muted">
            {t("meetings.newDialog.modeLabel")}
          </legend>
          {modeOption(
            "online",
            t("meetings.newDialog.modeOnline"),
            !systemSupported,
          )}
          {devices && !systemSupported && (
            <p className="text-xs text-muted">
              {t("meetings.newDialog.systemUnsupported")}
            </p>
          )}
          {modeOption("in_person", t("meetings.newDialog.modeInPerson"), false)}
        </fieldset>

        {devices === null && !error && (
          <p className="text-sm text-muted">
            {t("meetings.newDialog.loadingDevices")}
          </p>
        )}
        {devices && (
          <>
            <DeviceSelect
              label={t("meetings.newDialog.micLabel")}
              value={micId}
              devices={devices.inputs}
              disabled={starting}
              onChange={setMicId}
            />
            {mode === "online" && (
              <DeviceSelect
                label={t("meetings.newDialog.systemLabel")}
                value={systemId}
                devices={devices.system_sources}
                disabled={starting}
                onChange={setSystemId}
              />
            )}
          </>
        )}

        {error && (
          <div
            role="alert"
            className="flex flex-col items-start gap-2 rounded-lg bg-error/10 p-3 text-sm text-error"
          >
            <p className="break-words">{error}</p>
            {isModelError(error) && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  onOpenChange(false);
                  onOpenModelSettings();
                }}
              >
                {t("meetings.newDialog.openModelSettings")}
              </Button>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
};
