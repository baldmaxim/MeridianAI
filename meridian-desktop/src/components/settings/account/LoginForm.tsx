import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { commands } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useSettings } from "@/hooks/useSettings";
import { useSyncStore } from "@/stores/syncStore";

const DEFAULT_SERVER_URL = "https://meridianai.ru";
const FIELD_CLASS = "w-full min-h-11 text-[16px]!";

/** Sign-in form; the server field hides under "Another server". */
export const LoginForm: React.FC = () => {
  const { t } = useTranslation();
  const { settings } = useSettings();
  const setAccount = useSyncStore((s) => s.setAccount);
  const [serverEdit, setServerEdit] = useState<string | null>(null);
  const [serverOpen, setServerOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const serverUrl = serverEdit ?? (settings?.server_url || DEFAULT_SERVER_URL);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await commands.accountLogin({
        server_url: serverUrl,
        email,
        password,
      });
      if (result.status === "ok") {
        setPassword("");
        setAccount(result.data);
      } else {
        setError(result.error);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      className="flex flex-col gap-4 rounded-lg border border-mid-gray/20 p-4"
    >
      <div>
        <h2 className="text-base font-semibold text-text">
          {t("account.login.title")}
        </h2>
        <p className="mt-1 text-sm text-muted">{t("account.login.hint")}</p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("account.login.email")}</span>
        <Input
          type="email"
          name="email"
          autoComplete="username"
          value={email}
          disabled={submitting}
          onChange={(e) => setEmail(e.target.value)}
          onClear={() => setEmail("")}
          clearLabel={t("account.login.clearEmail")}
          className={FIELD_CLASS}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">{t("account.login.password")}</span>
        <Input
          type="password"
          name="password"
          autoComplete="current-password"
          value={password}
          disabled={submitting}
          onChange={(e) => setPassword(e.target.value)}
          onClear={() => setPassword("")}
          clearLabel={t("account.login.clearPassword")}
          className={FIELD_CLASS}
        />
      </label>

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
              disabled={submitting}
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

      <Button
        type="submit"
        variant="primary"
        size="lg"
        disabled={submitting || !email.trim() || !password}
        className="min-h-11 self-start"
      >
        {submitting ? t("account.login.submitting") : t("account.login.submit")}
      </Button>
    </form>
  );
};
