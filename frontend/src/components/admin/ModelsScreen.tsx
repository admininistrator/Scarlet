import { useState } from "react";

import { toApiError, useResource } from "../../features/admin/useResource";
import { ApiError, api, type ModelOut, type ReloadCatalogOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { TableScroll } from "../ui/TableScroll";
import { ErrorNotice, FailureReason, HealthDot, LoadingNote, ScreenTitle, TD, TH } from "./adminUi";
import { formatClock } from "./format";

/**
 * Man 1d "Model" — §16.3, ban T-HD7 · T-3.12.
 *
 * KH tham chieu: §16.3, §9.2, §9.3, UC-05, RR-5 · tasks.md T-2.19 (nut
 * reload), T-3.6 (`core/provider_health.py`), T-3.12.
 *
 * **Health tung provider doc tu `GET /models`**, cung nguon ma Model Picker
 * doc (`available` + `unavailable_reason`, §18.3) — hai man hinh noi hai
 * chuyen khac nhau ve cung mot provider la cach chac nhat de khong ai tin man
 * nao. Provider `always` KHONG duoc do (xem `provider_health.py`): chung luon
 * "hoat dong" o day, va man hinh noi ro dieu ay thay vi de nguoi doc tuong la
 * da kiem. Do tre / "kiem luc" cua ban ve server khong gui, nen o ay vang mat
 * (cung luat voi o tong cua man Chi phi).
 *
 * **Khong co cong tac bat/tat tung model.** §16.3 co hang ay va ban T-HD7 co
 * ve, nhung KHONG endpoint nao doi `enabled` cua mot model — catalog la file
 * (§9.2), doi bang cach sua `model_catalog.json` roi bam "Tai lai catalog".
 * Mot cong tac khong noi voi gi te hon khong co cong tac (Cam bay ③, cung ly
 * le). Ghi Backlog.
 */

interface ProviderCard {
  label: string;
  ok: boolean;
  reason: string | null;
}

/** Gom `GET /models` theo provider — provider hong khi CO model cua no bi xam. */
export function providerCards(models: readonly ModelOut[]): ProviderCard[] {
  const byProvider = new Map<string, ProviderCard>();
  for (const m of models) {
    const existing = byProvider.get(m.provider_id) ?? { label: m.provider, ok: true, reason: null };
    if (!m.available) {
      existing.ok = false;
      existing.reason = existing.reason ?? m.unavailable_reason;
    }
    byProvider.set(m.provider_id, existing);
  }
  return [...byProvider.values()];
}

export function ModelsScreen() {
  const models = useResource(api.listModels);
  const [reloading, setReloading] = useState(false);
  const [lastReload, setLastReload] = useState<{ at: number; result: ReloadCatalogOut } | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);

  const reload = async () => {
    setReloading(true);
    setActionError(null);
    try {
      const result = await api.adminReloadCatalog();
      setLastReload({ at: Date.now(), result });
      await models.reload();
    } catch (e) {
      setActionError(toApiError(e));
    } finally {
      setReloading(false);
    }
  };

  return (
    <>
      <ScreenTitle
        aside={
          <div className="flex flex-wrap items-center gap-3">
            {lastReload !== null && (
              <span className="text-xs text-muted">
                {t("admin.models.lastReloadPrefix")} <span className="tabular">{formatClock(lastReload.at)}</span>
                {" · "}
                <span className="tabular">{lastReload.result.models}</span> {t("admin.models.modelUnit")}
                {" · v"}
                <span className="tabular">{lastReload.result.version}</span>
              </span>
            )}
            <button
              type="button"
              onClick={() => void reload()}
              disabled={reloading}
              aria-busy={reloading || undefined}
              className="motion-press flex min-h-touch items-center gap-2 rounded-md border border-border-strong px-4 text-base font-medium text-foreground hover:bg-surface-hover disabled:opacity-70"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 18 18"
                fill="none"
                aria-hidden="true"
                className={reloading ? "motion-spin" : undefined}
              >
                <path
                  d="M15 9a6 6 0 1 1-1.8-4.3M15 2.5V6h-3.4"
                  className="stroke-current"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              {reloading ? t("admin.models.reloading") : t("admin.models.reload")}
            </button>
          </div>
        }
      >
        {t("admin.models.title")}
      </ScreenTitle>

      {actionError && <ErrorNotice title={t("admin.actionError")} error={actionError} />}
      {models.error && (
        <ErrorNotice title={t("admin.loadError")} error={models.error} onRetry={() => void models.reload()} />
      )}

      {models.data === null ? (
        models.loading && <LoadingNote />
      ) : (
        <>
          <h3 className="text-xl font-semibold text-foreground">{t("admin.models.providers")}</h3>
          <ul className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">
            {providerCards(models.data).map((p) => (
              <li
                key={p.label}
                className={
                  p.ok
                    ? "flex min-w-0 flex-col gap-2 rounded-lg border border-border bg-surface-panel p-4"
                    : "flex min-w-0 flex-col gap-2 rounded-lg border border-danger bg-surface-panel p-4"
                }
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm font-medium text-foreground">{p.label}</span>
                  <HealthDot ok={p.ok} />
                </div>
                {!p.ok && <FailureReason reason={p.reason} />}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted">{t("admin.models.healthNote")}</p>

          <h3 className="text-xl font-semibold text-foreground">{t("admin.models.catalog")}</h3>
          <TableScroll label={t("admin.models.catalog")}>
            <thead>
              <tr>
                <th scope="col" className={`${TH} sticky-col w-sticky-col`}>
                  {t("admin.col.model")}
                </th>
                <th scope="col" className={TH}>
                  {t("admin.col.provider")}
                </th>
              </tr>
            </thead>
            <tbody>
              {models.data.map((m) => (
                <tr key={m.id}>
                  <th scope="row" className={`${TD} sticky-col w-sticky-col text-left font-normal`}>
                    <span className="block font-semibold">{m.display_name}</span>
                    <span className="block font-mono text-xs text-muted">{m.id}</span>
                  </th>
                  <td className={`${TD} text-muted`}>{m.provider}</td>
                </tr>
              ))}
            </tbody>
          </TableScroll>
        </>
      )}
    </>
  );
}
