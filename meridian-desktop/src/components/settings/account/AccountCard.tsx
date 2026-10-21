import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { commands, type AccountInfo } from "@/bindings";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { useSyncStore } from "@/stores/syncStore";

interface AccountCardProps {
  account: AccountInfo;
}

/** Who is signed in, to which server, and the sign-out button. */
export const AccountCard: React.FC<AccountCardProps> = ({ account }) => {
  const { t } = useTranslation();
  const setAccount = useSyncStore((s) => s.setAccount);
  const [unsent, setUnsent] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const signOut = async () => {
    setBusy(true);
    const result = await commands.accountLogout();
    setBusy(false);
    setUnsent(null);
    if (result.status === "error") {
      toast.error(t("account.logoutFailed"), { description: result.error });
      return;
    }
    setAccount(null);
  };

  const handleLogoutClick = async () => {
    // The count is read now: the stored status may be a pass behind.
    const status = await commands.getSyncStatus();
    if (status.pending_count > 0) setUnsent(status.pending_count);
    else await signOut();
  };

  const name = account.user.display_name?.trim();
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-mid-gray/20 p-4">
      <div className="min-w-0">
        {name && (
          <p className="break-words text-base font-semibold text-text">
            {name}
          </p>
        )}
        <p className="break-all text-sm text-text">{account.user.email}</p>
        <p className="mt-1 break-all text-xs text-muted">
          {t("account.server")}: {account.server_url}
        </p>
      </div>
      <Button
        variant="secondary"
        disabled={busy}
        onClick={() => void handleLogoutClick()}
        className="min-h-11 self-start"
      >
        {t("account.logout.button")}
      </Button>
      <Dialog
        open={unsent !== null}
        onOpenChange={(open) => !open && !busy && setUnsent(null)}
        title={t("account.logout.confirmTitle")}
        closeLabel={t("common.close")}
        dismissible={!busy}
        contentFades={false}
        footer={
          <>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => setUnsent(null)}
            >
              {t("meetings.actions.cancel")}
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => void signOut()}
            >
              {t("account.logout.confirm")}
            </Button>
          </>
        }
      >
        <p className="text-sm text-text">
          {t("account.logout.unsent", { count: unsent ?? 0 })}
        </p>
      </Dialog>
    </div>
  );
};
