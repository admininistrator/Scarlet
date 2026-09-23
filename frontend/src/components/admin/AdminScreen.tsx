import { useCallback, useState } from "react";
import { useSearchParams } from "react-router";

import { useSession } from "../../app/Layout";
import { toApiError, useResource } from "../../features/admin/useResource";
import { ApiError, api } from "../../lib/api";
import { t, type TextKey } from "../../lib/i18n";
import { ApprovalsScreen } from "./ApprovalsScreen";
import { AuditScreen } from "./AuditScreen";
import { CostScreen } from "./CostScreen";
import { ErrorNotice, LoadingNote } from "./adminUi";
import { ModelsScreen } from "./ModelsScreen";
import { SystemScreen } from "./SystemScreen";
import { UsersScreen } from "./UsersScreen";

/**
 * Man `/admin` — sau man cua §16.3 theo ban T-HD7 (T-3.12).
 *
 * KH tham chieu: §16.3, §18.5 · tasks.md T-2.19, T-2.20, T-3.12 · ban T-HD7
 * (`Scarlet Quan tri.dc.html` + `AdminPanel.tsx`).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  AN MAN NAY DI KHONG PHAI LA PHAN QUYEN                                ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Cam bay cua T-2.19, nguyen van: *"an menu o FE KHONG phai phan quyen. Kiem
 * o server la bat buoc"*. `AdminOnly` day nguoi khong phai admin ra khoi
 * `/admin` — mot phep lich su, khong phai mot lop bao ve: moi endpoint
 * `/admin/*` tra `403 ADMIN_REQUIRED` tu `require_admin` o tang router cua
 * backend (T-2.16), va DoD cua T-3.12 do lai dieu ay bang `curl`. Component
 * nay vi vay KHONG kiem quyen lan nua; no goi API nhu moi man khac va hien
 * nguyen van loi neu server tu choi.
 *
 * ── Mot cot dieu huong, khong dashboard tong quan ─────────────────────────
 *
 * Ban ve: *"Sau man cho mot nguoi quan tri. Mot cot dieu huong, khong
 * dashboard tong quan, khong bo loc nang cao."* ≥ 1024 px la cot 216 px ben
 * trai; duoi do la mot HANG tab cuon ngang rieng (khung cuon, trang khong
 * cuon). Man dang mo nam trong `?screen=` de F5 va nut Back giu dung cho —
 * khong them route moi vao bang cua T-3.1a.
 *
 * Danh sach cho duyet duoc nap o DAY (khong trong `ApprovalsScreen`) vi nut
 * dieu huong can dem so don tren moi man.
 */

export type AdminScreenName = "approvals" | "users" | "cost" | "models" | "system" | "audit";
const SCREENS: readonly AdminScreenName[] = ["approvals", "users", "cost", "models", "system", "audit"];
const NAV_LABEL: Record<AdminScreenName, TextKey> = {
  approvals: "admin.nav.approvals",
  users: "admin.nav.users",
  cost: "admin.nav.cost",
  models: "admin.nav.models",
  system: "admin.nav.system",
  audit: "admin.nav.audit",
};
const SCREEN_PARAM = "screen";

function screenFrom(value: string | null): AdminScreenName {
  return SCREENS.find((s) => s === value) ?? "approvals";
}

export function AdminScreen() {
  const session = useSession();
  const [params, setParams] = useSearchParams();
  const screen = screenFrom(params.get(SCREEN_PARAM));

  const loadPending = useCallback(
    async () => (await api.adminListUsers("pending_approval")).users,
    [],
  );
  const pending = useResource(loadPending);
  const [deciding, setDeciding] = useState<string | null>(null);
  const [decideError, setDecideError] = useState<ApiError | null>(null);

  const decide = async (userId: string, decision: "approve" | "reject") => {
    setDeciding(userId);
    setDecideError(null);
    try {
      await api.adminChangeStatus(userId, decision);
    } catch (e) {
      setDecideError(toApiError(e));
    } finally {
      // Luat 1 cua T-2.19: DOC LAI tu server, ke ca khi loi (409 = man da cu).
      await pending.reload();
      setDeciding(null);
    }
  };

  const pendingCount = pending.data?.length ?? 0;

  return (
    <div className="flex min-h-full min-w-0 flex-col lg:flex-row">
      <nav
        aria-label={t("admin.navLabel")}
        className="min-w-0 border-b border-border lg:w-admin-nav lg:shrink-0 lg:border-r lg:border-b-0"
      >
        <p className="hidden px-6 pt-4 pb-2.5 text-xs font-semibold uppercase tracking-wider text-muted lg:block">
          {t("admin.tieuDe")}
        </p>
        <ul className="flex gap-1 overflow-x-auto px-gutter py-2 lg:flex-col lg:overflow-visible lg:px-3 lg:pt-0 lg:pb-4">
          {SCREENS.map((s) => (
            <li key={s} className="shrink-0">
              <button
                type="button"
                onClick={() => setParams({ [SCREEN_PARAM]: s })}
                aria-current={s === screen ? "page" : undefined}
                className={
                  s === screen
                    ? "motion-press flex min-h-touch w-full items-center justify-between gap-2 rounded-md bg-accent-subtle px-3 text-base font-semibold whitespace-nowrap text-accent-text"
                    : "motion-press flex min-h-touch w-full items-center justify-between gap-2 rounded-md px-3 text-base whitespace-nowrap text-foreground hover:bg-surface-hover"
                }
              >
                {t(NAV_LABEL[s])}
                {s === "approvals" && pendingCount > 0 && (
                  <span className="min-w-5 rounded-full bg-accent px-1.5 text-center text-2xs font-semibold text-accent-foreground">
                    <span className="tabular">{pendingCount}</span>
                    <span className="sr-only"> {t("admin.nav.pendingCount")}</span>
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <main className="flex min-w-0 flex-1 flex-col gap-6 px-gutter py-6 lg:px-gutter-lg">
        {screen === "approvals" && (
          <>
            {pending.error && (
              <ErrorNotice
                title={t("admin.loadError")}
                error={pending.error}
                onRetry={() => void pending.reload()}
              />
            )}
            {decideError && <ErrorNotice title={t("admin.actionError")} error={decideError} />}
            {pending.data === null ? (
              pending.loading && <LoadingNote />
            ) : (
              <ApprovalsScreen
                signups={pending.data}
                busyId={deciding}
                onDecide={(id, decision) => void decide(id, decision)}
              />
            )}
          </>
        )}
        {screen === "users" && <UsersScreen currentUserId={session.user?.id ?? null} />}
        {screen === "cost" && <CostScreen />}
        {screen === "models" && <ModelsScreen />}
        {screen === "system" && <SystemScreen />}
        {screen === "audit" && <AuditScreen />}
      </main>
    </div>
  );
}
