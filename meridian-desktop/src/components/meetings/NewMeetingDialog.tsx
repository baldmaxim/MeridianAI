import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown } from "lucide-react";
import { commands, type CaptureDevices, type CaptureMode } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { useLibraryStore } from "@/stores/libraryStore";
import { useMeetingStore } from "@/stores/meetingStore";
import { formatTitleDate, isModelError } from "@/lib/utils/meetingFormat";
import { resolveProject } from "@/lib/utils/projects";
import { DeviceSelect } from "./DeviceSelect";
import {
  EMPTY_MEETING_CONTEXT,
  MeetingContextForm,
  toNullable,
  type MeetingContextValue,
} from "./MeetingContextForm";
import { ProjectPicker } from "./ProjectPicker";

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
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [objectId, setObjectId] = useState<number | null>(null);
  const [context, setContext] = useState<MeetingContextValue>(
    EMPTY_MEETING_CONTEXT,
  );
  const [contextOpen, setContextOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const customers = useLibraryStore((s) => s.snapshot?.projects);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setTitle(
      t("meetings.newDialog.defaultTitle", {
        date: formatTitleDate(new Date()),
      }),
    );
    // The project filter of the library pre-fills the project.
    const filter = useLibraryStore.getState().filter;
    setCustomerId(
      filter.kind === "customer" || filter.kind === "object"
        ? filter.customerId
        : null,
    );
    setObjectId(filter.kind === "object" ? filter.objectId : null);
    setContext(EMPTY_MEETING_CONTEXT);
    setContextOpen(false);
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
        // The last chosen computer-sound device, if it is still there.
        void commands.getAppSettings().then((settings) => {
          if (cancelled || settings.status !== "ok") return;
          const saved = settings.data.meeting_system_device;
          if (saved && result.data.system_sources.some((d) => d.id === saved)) {
            setSystemId(saved);
          }
        });
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
  const projectList = customers ?? [];

  const handleSystemChange = (id: string) => {
    setSystemId(id);
    void commands.setMeetingSystemDevice(id || null).then((result) => {
      if (result.status === "error") setError(result.error);
    });
  };

  const handleStart = async () => {
    setStarting(true);
    setError(null);
    const project = resolveProject(projectList, customerId, objectId);
    const failure = await useMeetingStore.getState().startMeeting({
      title: title.trim(),
      capture_mode: mode,
      mic_device_id: micId || null,
      system_device_id: mode === "online" && systemId ? systemId : null,
      customer_id: project.customerId,
      object_id: project.objectId,
      customer_name: project.customerName,
      object_name: project.objectName,
      negotiation_type: toNullable(context.negotiationType),
      key_terms: toNullable(context.keyTerms),
      opponent_weaknesses: toNullable(context.opponentWeaknesses),
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

        {projectList.length > 0 && (
          <ProjectPicker
            customers={projectList}
            customerId={customerId}
            objectId={objectId}
            disabled={starting}
            onChange={(customer, object) => {
              setCustomerId(customer);
              setObjectId(object);
            }}
          />
        )}

        <div className="flex flex-col gap-2">
          <button
            type="button"
            aria-expanded={contextOpen}
            onClick={() => setContextOpen((v) => !v)}
            className="flex cursor-pointer items-center gap-1.5 self-start rounded-lg py-1 text-sm text-muted transition-colors duration-200 hover:text-text focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary motion-reduce:transition-none"
          >
            <ChevronDown
              className={`h-4 w-4 transition-transform duration-200 motion-reduce:transition-none ${
                contextOpen ? "" : "-rotate-90 rtl:rotate-90"
              }`}
              aria-hidden="true"
            />
            {t("meetings.context.sectionTitle")}
          </button>
          {contextOpen && (
            <MeetingContextForm
              value={context}
              onChange={setContext}
              disabled={starting}
            />
          )}
        </div>

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
                onChange={handleSystemChange}
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
