import { useEffect, useState, useRef, type ReactNode } from "react";
import { toast, Toaster } from "sonner";
import { useTranslation } from "react-i18next";
import { listen } from "@tauri-apps/api/event";
import { platform } from "@tauri-apps/plugin-os";
import { checkMicrophonePermission } from "tauri-plugin-macos-permissions-api";
import { ModelStateEvent, RecordingErrorEvent } from "./lib/types/events";
import "./App.css";
import Onboarding, {
  PermissionsOnboarding,
  ModelMigration,
} from "./components/onboarding";
import { type OnboardingPreviewStep } from "./components/settings";
import { AppShell } from "./components/shell/AppShell";
import type {
  AppSection,
  SettingsSection,
} from "./components/shell/settingsSections";
import { useMeetingEvents } from "./hooks/useMeetingEvents";
import { useSyncEvents } from "./hooks/useSyncEvents";
import { useUpdateWatcher } from "./hooks/useUpdateWatcher";
import { useMeetingStore } from "./stores/meetingStore";
import { useSettings } from "./hooks/useSettings";
import { UpdateDialog } from "./components/UpdateDialog";
import { useSettingsStore } from "./stores/settingsStore";
import { commands } from "@/bindings";
import { deleteRetiredModel } from "@/components/onboarding/retiredModels";
import { getLanguageDirection, initializeRTL } from "@/lib/utils/rtl";

type OnboardingStep = "permissions" | "migration" | "model" | "done";

// Stable identity so preview effects do not re-run due to callback changes.
const NOOP = () => {};

function App() {
  const { t, i18n } = useTranslation();
  const [onboardingStep, setOnboardingStep] = useState<OnboardingStep | null>(
    null,
  );
  const [onboardingPreview, setOnboardingPreview] =
    useState<OnboardingPreviewStep | null>(null);
  // Track if this is a returning user who just needs to grant permissions
  // (vs a new user who needs full onboarding including model selection)
  const [isReturningUser, setIsReturningUser] = useState(false);
  // Set when a returning user's selected model is a retired (ONNX) model that
  // is still on disk: they must update it before the app can transcribe.
  const [migrationModelId, setMigrationModelId] = useState<string | null>(null);
  const [currentSection, setCurrentSection] = useState<AppSection>("meetings");
  const [settingsTab, setSettingsTab] = useState<SettingsSection>("account");
  const { settings, updateSetting } = useSettings();
  const direction = getLanguageDirection(i18n.language);
  const refreshAudioDevices = useSettingsStore(
    (state) => state.refreshAudioDevices,
  );
  const hasCompletedPostOnboardingInit = useRef(false);
  useEffect(() => {
    checkOnboardingStatus();
  }, []);

  // Meeting events live as long as the main app does; a meeting that is
  // already recording (e.g. after a window reload) opens straight away.
  const showMeeting = (meetingId: string) => {
    setCurrentSection("meetings");
    void useMeetingStore.getState().openMeeting(meetingId);
  };
  useMeetingEvents(onboardingStep === "done", showMeeting);

  const openSettingsTab = (tab: SettingsSection) => {
    setSettingsTab(tab);
    setCurrentSection("settings");
  };

  useSyncEvents(onboardingStep === "done");

  // Проверки обновлений, уведомление и меню трея (D3).
  useUpdateWatcher(onboardingStep === "done");

  // Initialize RTL direction when language changes
  useEffect(() => {
    initializeRTL(i18n.language);
  }, [i18n.language]);

  // Refresh audio devices when main app loads
  useEffect(() => {
    if (onboardingStep === "done" && !hasCompletedPostOnboardingInit.current) {
      hasCompletedPostOnboardingInit.current = true;
      refreshAudioDevices();
    }
  }, [onboardingStep, refreshAudioDevices]);

  // Handle keyboard shortcuts for debug mode toggle
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Check for Ctrl+Shift+D (Windows/Linux) or Cmd+Shift+D (macOS)
      const isDebugShortcut =
        event.shiftKey &&
        event.key.toLowerCase() === "d" &&
        (event.ctrlKey || event.metaKey);

      if (isDebugShortcut) {
        event.preventDefault();
        const currentDebugMode = settings?.debug_mode ?? false;
        updateSetting("debug_mode", !currentDebugMode);
      }
    };

    // Add event listener when component mounts
    document.addEventListener("keydown", handleKeyDown);

    // Cleanup event listener when component unmounts
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [settings?.debug_mode, updateSetting]);

  // Listen for recording errors from the backend and show a toast
  useEffect(() => {
    const unlisten = listen<RecordingErrorEvent>("recording-error", (event) => {
      const { error_type, detail } = event.payload;

      if (error_type === "microphone_permission_denied") {
        const currentPlatform = platform();
        const platformKey = `errors.micPermissionDenied.${currentPlatform}`;
        const description = t(platformKey, {
          defaultValue: t("errors.micPermissionDenied.generic"),
        });
        toast.error(t("errors.micPermissionDeniedTitle"), { description });
      } else if (error_type === "no_input_device") {
        toast.error(t("errors.noInputDeviceTitle"), {
          description: t("errors.noInputDevice"),
        });
      } else {
        toast.error(
          t("errors.recordingFailed", { error: detail ?? "Unknown error" }),
        );
      }
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, [t]);

  // Listen for transcription failures and show a toast.
  // The payload is the backend error message (also logged to the log file).
  useEffect(() => {
    const unlisten = listen<string>("transcription-error", (event) => {
      toast.error(t("errors.transcriptionFailedTitle"), {
        description: event.payload,
      });
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, [t]);

  // Listen for model loading failures and show a toast
  useEffect(() => {
    const unlisten = listen<ModelStateEvent>("model-state-changed", (event) => {
      if (event.payload.event_type === "loading_failed") {
        toast.error(
          t("errors.modelLoadFailed", {
            model:
              event.payload.model_name || t("errors.modelLoadFailedUnknown"),
          }),
          {
            description: event.payload.error,
          },
        );
      }
    });
    return () => {
      unlisten.then((fn) => fn());
    };
  }, [t]);

  const revealMainWindowForPermissions = async () => {
    try {
      await commands.showMainWindowCommand();
    } catch (e) {
      console.warn("Failed to show main window for permission onboarding:", e);
    }
  };

  const getMigrationModelId = async (
    selectedModel: string,
  ): Promise<string | null> => {
    const retired = await commands.getRetiredModels();
    return retired.some((m) => m.id === selectedModel) ? selectedModel : null;
  };

  // Returning users land in the app unless their model needs updating. The
  // window may start hidden, so bring it forward for the update screen.
  const finishReturningUser = async (retiredModelId: string | null) => {
    if (retiredModelId) {
      await revealMainWindowForPermissions();
      setOnboardingStep("migration");
    } else {
      setOnboardingStep("done");
    }
  };

  const checkOnboardingStatus = async () => {
    try {
      const settingsResult = await commands.getAppSettings();
      const hasCompletedOnboarding =
        settingsResult.status === "ok" &&
        settingsResult.data.onboarding_completed === true;
      const currentPlatform = platform();

      if (hasCompletedOnboarding) {
        // Returning user - check if they need to grant permissions first
        setIsReturningUser(true);
        const retiredModelId = await getMigrationModelId(
          settingsResult.data.selected_model ?? "",
        );
        setMigrationModelId(retiredModelId);

        if (currentPlatform === "macos") {
          try {
            const hasMicrophone = await checkMicrophonePermission();
            if (!hasMicrophone) {
              await revealMainWindowForPermissions();
              setOnboardingStep("permissions");
              return;
            }
          } catch (e) {
            console.warn("Failed to check macOS permissions:", e);
            // If we can't check, proceed to main app and let them fix it there
          }
        }

        if (currentPlatform === "windows") {
          try {
            const microphoneStatus =
              await commands.getWindowsMicrophonePermissionStatus();
            if (
              microphoneStatus.supported &&
              microphoneStatus.overall_access === "denied"
            ) {
              await revealMainWindowForPermissions();
              setOnboardingStep("permissions");
              return;
            }
          } catch (e) {
            console.warn("Failed to check Windows microphone permissions:", e);
            // If we can't check, proceed to main app and let them fix it there
          }
        }

        await finishReturningUser(retiredModelId);
      } else {
        // New user - start full onboarding
        setIsReturningUser(false);
        setOnboardingStep("permissions");
      }
    } catch (error) {
      console.error("Failed to check onboarding status:", error);
      setOnboardingStep("permissions");
    }
  };

  const handlePermissionsComplete = () => {
    // Returning users already have models, skip to main app (unless their
    // model needs updating). New users need to select a model.
    if (isReturningUser) {
      finishReturningUser(migrationModelId);
    } else {
      setOnboardingStep("model");
    }
  };

  const handleModelSelected = async () => {
    // Coming from the model update: the user picked a different model instead
    // of updating, so the retired models left on disk can't run anymore.
    if (migrationModelId) {
      for (const model of await commands.getRetiredModels()) {
        await deleteRetiredModel(model.id);
      }
    }
    // Transition to main app - user has started a download
    setOnboardingStep("done");
  };

  // Rendered once around every step below (including onboarding) so
  // toast.error() calls surface to the user. sonner renders via a portal, so
  // its position in the tree doesn't affect layout. Without this, errors during
  // onboarding (e.g. a model download failing because the model host is
  // unreachable) are silently swallowed and the wizard just appears to "blink".
  const toaster = (
    <Toaster
      theme="system"
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            "bg-background border border-mid-gray/20 rounded-lg shadow-lg px-4 py-3 flex items-center gap-3 text-sm",
          title: "font-medium",
          description: "text-mid-gray",
          actionButton:
            "px-2 py-1 text-xs font-medium rounded-lg border bg-mid-gray/10 border-mid-gray/20 hover:bg-background-ui/30 hover:border-logo-primary cursor-pointer whitespace-nowrap",
        },
      }}
    />
  );

  // Still checking onboarding status
  if (onboardingStep === null) {
    return null;
  }

  // Select the content for the current step. The Toaster is rendered once, in a
  // stable wrapper around this node, so crossing between onboarding steps and
  // the main app never remounts it (which would drop any in-flight toast).
  let content: ReactNode;
  if (onboardingPreview) {
    // Render previews in the same top-level slot as real onboarding. Keeping
    // the settings layout unmounted ensures viewport overflow behaves exactly
    // as it does during first-run onboarding.
    content = (
      <>
        {onboardingPreview === "permissions" ? (
          <PermissionsOnboarding onComplete={NOOP} preview />
        ) : (
          <Onboarding onModelSelected={NOOP} preview />
        )}
        <button
          type="button"
          onClick={() => setOnboardingPreview(null)}
          className="fixed top-4 end-4 z-50 rounded-lg border border-mid-gray/20 bg-background px-4 py-2 text-sm font-medium text-text shadow-lg hover:bg-background-ui/30 cursor-pointer"
        >
          {t("settings.debug.onboardingPreview.exitButton")}
        </button>
      </>
    );
  } else if (onboardingStep === "permissions") {
    content = <PermissionsOnboarding onComplete={handlePermissionsComplete} />;
  } else if (onboardingStep === "migration" && migrationModelId) {
    content = (
      <ModelMigration
        inUseModelId={migrationModelId}
        onComplete={() => setOnboardingStep("done")}
        onChooseAnother={() => setOnboardingStep("model")}
      />
    );
  } else if (onboardingStep === "model") {
    content = (
      <Onboarding
        onModelSelected={handleModelSelected}
        onBack={
          migrationModelId ? () => setOnboardingStep("migration") : undefined
        }
      />
    );
  } else {
    content = (
      <div dir={direction}>
        <AppShell
          section={currentSection}
          settingsTab={settingsTab}
          onSectionChange={setCurrentSection}
          onSettingsTabChange={setSettingsTab}
          onOpenSettingsTab={openSettingsTab}
          onOpenMeeting={showMeeting}
          onPreviewOnboarding={setOnboardingPreview}
        />
      </div>
    );
  }

  return (
    <>
      {toaster}
      {content}
      <UpdateDialog />
    </>
  );
}

export default App;
