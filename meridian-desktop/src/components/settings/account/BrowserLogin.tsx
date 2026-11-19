import React, { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { commands } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useSettings } from "@/hooks/useSettings";
import { useSyncStore } from "@/stores/syncStore";

const DEFAULT_SERVER_URL = "https://meridianai.ru";
const FIELD_CLASS = "w-full min-h-11 text-[16px]!";

/** Sign-in through the system browser; the server field hides under "Another server". */
interface BrowserLoginProps {
  /** "plain": no card border, title or hint (the host screen has its own). */
  variant?: "card" | "plain";
}

export const BrowserLogin: React.FC<BrowserLoginProps> = ({
  variant = "card",
}) => {
  const { t } = useTranslation();
  const { settings } = useSettings();
  const setAccount = useSyncStore((s) => s.setAccount);
  const [serverEdit, setServerEdit] = useState<string | null>(null);
  const [serverOpen, setServerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const cancelledRef = useRef(false);

  const serverUrl = serverEdit ?? (settings?.server_url || DEFAULT_SERVER_URL);

  const handleLogin = async () => {
    if (pending) return;
    setPending(true);
    setError(null);
    cancelledRef.current = false;
    try {
      const result = await commands.accountBrowserLogin(serverUrl);
      if (result.status === "ok") {
        setAccount(result.data);
      } else if (!cancelledRef.current) {
        setError(result.error);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setPending(false);
    }
  };

  const handleCancel = () => {
    cancelledRef.current = true;
    void commands.accountBrowserLoginCancel();
  };

  return (
    <div
      className={
        variant === "card"
          ? "flex flex-col gap-4 rounded-lg border border-mid-gray/20 p-4"
          : "flex flex-col gap-4"
      }
    >
      {variant === "card" && (
        <div>
          <h2 className="text-base font-semibold text-text">
            {t("account.login.title")}
          </h2>
          <p className="mt-1 text-sm text-muted">{t("account.login.hint")}</p>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <button
          type="button"
          aria-expanded={serverOpen}
          onClick={() => setServerOpen((open) => !open)}
          className="w-fit cursor-pointer text-sm text-muted underline-offset-2 hover:text-text hover:underline focus:outline-none focus-visible:ring-1 focus-visible:ring-logo-primary"
        >
          {t("account.login.anotherServer")}
        </button>
        {serverOpen && (
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">{t("account.login.server")}</span>
            <Input
              type="url"
              name="server"
              value={serverUrl}
              disabled={pending}
              onChange={(e) => setServerEdit(e.target.value)}
              onClear={() => setServerEdit("")}
              clearLabel={t("account.login.clearServer")}
              className={FIELD_CLASS}
            />
          </label>
        )}
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-lg bg-error/10 px-3 py-2 text-sm text-error"
        >
          {error}
        </p>
      )}

      {pending ? (
        <div className="flex flex-wrap items-center gap-3">
          <p role="status" className="text-sm text-muted">
            {t("account.login.waiting")}
          </p>
          <Button
            type="button"
            variant="secondary"
            size="lg"
            onClick={handleCancel}
            className="min-h-11"
          >
            {t("account.login.cancel")}
          </Button>
        </div>
      ) : (
        <Button
          type="button"
          variant="primary"
          size="lg"
          onClick={() => void handleLogin()}
          className="min-h-11 self-start"
        >
          {t("account.login.submit")}
        </Button>
      )}
    </div>
  );
};
