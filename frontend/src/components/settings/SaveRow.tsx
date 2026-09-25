import { CircleCheck } from "lucide";

import { t } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";

/**
 * Hang nut Luu — dung chung cho Tai khoan, Giao dien, Model (ban T-HD9).
 *
 * Luu tat (`disabled`) khi khong co gi thay doi. "Da luu" nam trong mot
 * `role="status"` CO SAN tu dau, nen trinh doc man hinh doc duoc khi chu
 * xuat hien. Khong dung chu "da ap dung" (bang "Con so" cua ban ve).
 */
export function SaveRow({
  dirty,
  saving,
  saved,
  error,
}: {
  dirty: boolean;
  saving: boolean;
  saved: boolean;
  error: string | null;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-touch items-center gap-3">
        <button
          type="submit"
          disabled={!dirty || saving}
          className="control-disabled motion-press min-h-touch rounded-md bg-accent px-5.5 text-base font-semibold text-accent-foreground enabled:hover:bg-accent-hover"
        >
          {t("settings.save")}
        </button>
        <p role="status" className="flex items-center gap-1.5 text-sm font-medium text-success-text">
          {saved && !dirty && (
            <span className="motion-enter flex items-center gap-1.5">
              <StaticIcon icon={CircleCheck} size={16} className="shrink-0" />
              {t("settings.saved")}
            </span>
          )}
        </p>
      </div>
      {error !== null && (
        <p role="alert" className="text-sm text-danger-text">
          {error}
        </p>
      )}
    </div>
  );
}
