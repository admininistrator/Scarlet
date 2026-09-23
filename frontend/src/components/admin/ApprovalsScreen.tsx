import type { AdminUserRa } from "../../lib/api";
import { t } from "../../lib/i18n";
import { ScreenTitle } from "./adminUi";
import { formatDateTime } from "./format";

/**
 * Man 1a "Duyet nguoi dung" — §16.3, ban T-HD7.
 *
 * §16.3 doi dung ba thu: *"danh sach pending_approval, nut Duyet/Tu choi, xem
 * email + thoi diem dang ky"*. Khong cot nao khac (ban ve: *"chi co email +
 * thoi diem dang ky, dung nhung gi server co"*). Email dai xuong dong
 * (`break-all`) thay vi day hai nut ra ngoai; "Duyet" la nut nhan duy nhat.
 *
 * Danh sach do `AdminScreen` nap (nut dieu huong can dem so don) va nap LAI
 * sau moi lan bam — luat 1 cua `useQuanTri` cu (T-2.19): hang vua duyet phai
 * roi khoi tap loc, va mot hang khac co the vua roi VAO no.
 */
export function ApprovalsScreen({
  signups,
  busyId,
  onDecide,
}: {
  signups: AdminUserRa[];
  busyId: string | null;
  onDecide: (userId: string, decision: "approve" | "reject") => void;
}) {
  return (
    <>
      <ScreenTitle
        aside={
          <p className="text-sm text-muted">
            <span className="tabular font-semibold text-foreground">{signups.length}</span>{" "}
            {t("admin.approvals.countSuffix")}
          </p>
        }
      >
        {t("admin.approvals.title")}
      </ScreenTitle>
      {signups.length === 0 ? (
        <p className="rounded-lg border border-border px-4 py-6 text-base text-muted">
          {t("admin.approvals.empty")}
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-lg border border-border bg-surface-panel">
          {signups.map((s) => (
            <li key={s.id} className="flex min-w-0 flex-wrap items-center gap-3 px-4 py-3">
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="break-all text-base font-semibold text-foreground">{s.email}</span>
                <span className="text-xs text-muted">
                  {t("admin.approvals.registeredAt")}{" "}
                  <span className="tabular">{formatDateTime(s.created_at)}</span>
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={busyId !== null}
                  onClick={() => onDecide(s.id, "reject")}
                  className="motion-press min-h-touch rounded-md border border-border-strong px-4 text-base font-medium text-foreground hover:bg-surface-hover disabled:opacity-50"
                >
                  {t("admin.approvals.reject")}
                </button>
                <button
                  type="button"
                  disabled={busyId !== null}
                  onClick={() => onDecide(s.id, "approve")}
                  className="motion-press min-h-touch rounded-md bg-accent px-4 text-base font-semibold text-accent-foreground hover:bg-accent-hover disabled:opacity-50"
                >
                  {t("admin.approvals.approve")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
