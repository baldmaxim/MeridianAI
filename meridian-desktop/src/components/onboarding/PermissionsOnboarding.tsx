import { useEffect, useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { platform } from "@tauri-apps/plugin-os";
import {
  checkMicrophonePermission,
  requestMicrophonePermission,
} from "tauri-plugin-macos-permissions-api";
import { toast } from "sonner";
import { commands } from "@/bindings";
import { useSettingsStore } from "@/stores/settingsStore";
import { OnboardingLayout } from "./OnboardingLayout";
import { Mic, Check, Loader2 } from "lucide-react";

interface PermissionsOnboardingProps {
  onComplete: () => void;
  preview?: boolean;
}

type PermissionStatus = "checking" | "needed" | "waiting" | "granted";
type PermissionPlatform = "macos" | "windows" | "other";

interface PermissionsState {
  microphone: PermissionStatus;
}

const PermissionsOnboarding: React.FC<PermissionsOnboardingProps> = ({
  onComplete,
  preview = false,
}) => {
  const { t } = useTranslation();
  const refreshAudioDevices = useSettingsStore(
    (state) => state.refreshAudioDevices,
  );
  const [permissionPlatform, setPermissionPlatform] =
    useState<PermissionPlatform | null>(null);
  const [permissions, setPermissions] = useState<PermissionsState>({
    microphone: "checking",
  });
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const errorCountRef = useRef<number>(0);
  const MAX_POLLING_ERRORS = 3;

  const isMacOS = permissionPlatform === "macos";
  const isWindows = permissionPlatform === "windows";
  const showMicrophonePermission = isMacOS || isWindows;

  const allGranted = showMicrophonePermission
    ? permissions.microphone === "granted"
    : true;

  const completeOnboarding = useCallback(async () => {
    await refreshAudioDevices();
    timeoutRef.current = setTimeout(() => onComplete(), 300);
  }, [onComplete, refreshAudioDevices]);

  const hasWindowsMicrophoneAccess = useCallback(async (): Promise<boolean> => {
    const microphoneStatus =
      await commands.getWindowsMicrophonePermissionStatus();

    if (!microphoneStatus.supported) {
      return true;
    }

    return microphoneStatus.overall_access !== "denied";
  }, []);

  // Check platform and permission status on mount
  useEffect(() => {
    const currentPlatform = platform();
    const nextPlatform: PermissionPlatform =
      currentPlatform === "macos"
        ? "macos"
        : currentPlatform === "windows"
          ? "windows"
          : "other";

    setPermissionPlatform(nextPlatform);

    // Debug previews are intentionally inert: show the permission request UI
    // without checking or changing operating-system permissions.
    if (preview) {
      setPermissions({
        microphone: nextPlatform === "other" ? "granted" : "needed",
      });
      return;
    }

    // Skip immediately on unsupported platforms
    if (nextPlatform === "other") {
      onComplete();
      return;
    }

    const checkInitial = async () => {
      if (nextPlatform === "macos") {
        try {
          const microphoneGranted = await checkMicrophonePermission();

          setPermissions({
            microphone: microphoneGranted ? "granted" : "needed",
          });

          if (microphoneGranted) {
            await completeOnboarding();
          }
        } catch (error) {
          console.error("Failed to check macOS permissions:", error);
          toast.error(t("onboarding.permissions.errors.checkFailed"));
          setPermissions({ microphone: "needed" });
        }

        return;
      }

      try {
        const microphoneGranted = await hasWindowsMicrophoneAccess();

        setPermissions({
          microphone: microphoneGranted ? "granted" : "needed",
        });

        if (microphoneGranted) {
          await completeOnboarding();
        }
      } catch (error) {
        console.warn("Failed to check Windows microphone permissions:", error);
        setPermissions({ microphone: "granted" });
        await completeOnboarding();
      }
    };

    checkInitial();
  }, [completeOnboarding, hasWindowsMicrophoneAccess, onComplete, preview, t]);

  // Polling for permissions after user clicks a button
  const startPolling = useCallback(() => {
    if (pollingRef.current || permissionPlatform === null) return;

    pollingRef.current = setInterval(async () => {
      try {
        if (permissionPlatform === "windows") {
          const microphoneGranted = await hasWindowsMicrophoneAccess();

          if (microphoneGranted) {
            setPermissions((prev) => ({ ...prev, microphone: "granted" }));

            if (pollingRef.current) {
              clearInterval(pollingRef.current);
              pollingRef.current = null;
            }

            await completeOnboarding();
          }

          errorCountRef.current = 0;
          return;
        }

        const microphoneGranted = await checkMicrophonePermission();

        if (microphoneGranted) {
          setPermissions((prev) => ({ ...prev, microphone: "granted" }));

          // Stop polling, refresh audio devices, and proceed
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
          await completeOnboarding();
        }

        // Reset error count on success
        errorCountRef.current = 0;
      } catch (error) {
        console.error("Error checking permissions:", error);
        errorCountRef.current += 1;

        if (errorCountRef.current >= MAX_POLLING_ERRORS) {
          // Stop polling after too many consecutive errors
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
          toast.error(t("onboarding.permissions.errors.checkFailed"));
        }
      }
    }, 1000);
  }, [completeOnboarding, hasWindowsMicrophoneAccess, permissionPlatform, t]);

  // Cleanup polling and timeouts on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const handleGrantMicrophone = async () => {
    if (preview) return;

    try {
      if (isWindows) {
        await commands.openMicrophonePrivacySettings();
      } else {
        await requestMicrophonePermission();
      }

      setPermissions((prev) => ({ ...prev, microphone: "waiting" }));
      startPolling();
    } catch (error) {
      console.error("Failed to request microphone permission:", error);
      toast.error(t("onboarding.permissions.errors.requestFailed"));
    }
  };

  const isChecking =
    permissionPlatform === null ||
    (showMicrophonePermission && permissions.microphone === "checking");

  // Still checking platform/initial permissions
  if (isChecking) {
    return (
      <div className="h-screen w-full flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-text/50" />
      </div>
    );
  }

  // All permissions granted - show success briefly
  if (allGranted) {
    return (
      <div className="h-screen w-full flex flex-col items-center justify-center gap-4">
        <div className="p-4 rounded-full bg-emerald-500/20">
          <Check className="w-12 h-12 text-emerald-400" />
        </div>
        <p className="text-lg font-medium text-text">
          {t("onboarding.permissions.allGranted")}
        </p>
      </div>
    );
  }

  // Show permissions request screen
  return (
    <OnboardingLayout>
      <div className="h-full w-full flex flex-col p-6 gap-6 items-center justify-center">
        <div className="max-w-md w-full flex flex-col items-center gap-4">
          <div className="text-center mb-2">
            <h2 className="text-xl font-semibold text-text mb-2">
              {t("onboarding.permissions.title")}
            </h2>
            <p className="text-text/70">
              {t("onboarding.permissions.description")}
            </p>
          </div>

          {/* Microphone Permission Card */}
          {showMicrophonePermission && (
            <div className="w-full p-4 rounded-xl bg-surface border border-border">
              <div className="flex items-center gap-4">
                <div className="p-3 rounded-full bg-logo-primary/20 shrink-0">
                  <Mic className="w-6 h-6 text-logo-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-medium text-text">
                    {t("onboarding.permissions.microphone.title")}
                  </h3>
                  <p className="text-sm text-text/60 mb-3">
                    {t("onboarding.permissions.microphone.description")}
                  </p>
                  {permissions.microphone === "granted" ? (
                    <div className="flex items-center gap-2 text-emerald-400 text-sm">
                      <Check className="w-4 h-4" />
                      {t("onboarding.permissions.granted")}
                    </div>
                  ) : permissions.microphone === "waiting" ? (
                    <div className="flex items-center gap-2 text-text/50 text-sm">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      {t("onboarding.permissions.waiting")}
                    </div>
                  ) : (
                    <button
                      onClick={handleGrantMicrophone}
                      className="px-4 py-2 rounded-lg bg-logo-primary hover:bg-logo-primary/90 text-on-accent text-sm font-medium transition-colors"
                    >
                      {isWindows
                        ? t("accessibility.openSettings")
                        : t("onboarding.permissions.grant")}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </OnboardingLayout>
  );
};

export default PermissionsOnboarding;
