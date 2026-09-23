import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";

import { t } from "../../lib/i18n";

/** Khung dialog cua ban T-HD7 (dialog ghi de han muc), dung chung cho ca ba. */
export function AdminDialog({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="motion-scrim fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className="motion-panel fixed inset-x-gutter top-1/2 z-50 mx-auto flex max-h-sheet-max max-w-dialog -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-lg border border-border bg-surface-panel p-5 shadow-popover">
          <div className="flex flex-col gap-0.5">
            <Dialog.Title className="text-xl font-semibold text-foreground">{title}</Dialog.Title>
            <Dialog.Description className="break-all text-sm text-muted">{subtitle}</Dialog.Description>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Hang nut cuoi dialog. "Huy" doi thanh "Dong" sau khi luu — khong con gi de
 * huy nua (ban T-HD7).
 */
export function DialogButtons({
  saved,
  saving,
  onSave,
}: {
  saved: boolean;
  saving: boolean;
  onSave: () => void;
}) {
  return (
    <div className="flex flex-wrap justify-end gap-2">
      <Dialog.Close className="motion-press min-h-touch rounded-md border border-border-strong px-4 text-base font-medium text-foreground hover:bg-surface-hover">
        {saved ? t("admin.close") : t("admin.cancel")}
      </Dialog.Close>
      <button
        type="button"
        disabled={saving}
        onClick={onSave}
        className="motion-press min-h-touch rounded-md bg-accent px-4 text-base font-semibold text-accent-foreground hover:bg-accent-hover disabled:opacity-50"
      >
        {saving ? t("admin.saving") : t("admin.save")}
      </button>
    </div>
  );
}
