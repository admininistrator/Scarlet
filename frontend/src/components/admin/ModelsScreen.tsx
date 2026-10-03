import { useState } from "react";

import { toApiError, useResource } from "../../features/admin/useResource";
import { ApiError, api, type AdminModelOut, type ReloadCatalogOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { TableScroll } from "../ui/TableScroll";
import { ErrorNotice, FailureReason, HealthDot, LoadingNote, ScreenTitle, TD, TH } from "./adminUi";
import { formatClock } from "./format";

/**
 * Man 1e "Model" — §16.3, ban T-HD7-v2 · T-3.12 → T-S.17.
 *
 * KH tham chieu: §16.3, §9.2, §9.5, §24.2b·S3a · tasks.md T-2.19 (nut
 * reload), T-S.8 (`GET /admin/models`), T-S.17, B-262 ④, NQ-119.
 *
 * **Health thuoc ve DUONG DI** (§9.5): doc `GET /admin/models` — hang + duong
 * di that + luot do nen gan nhat cua duong ay. `GET /models` cua nguoi dung co
 * y giau duong trung gian (NQ-119), nen man nay KHONG doc no nua: "Google AI
 * xam" chi hieu duoc khi biet no di qua 9Router.
 *
 * **"qua <duong>" chi hien cho duong AN voi nguoi dung** (`route.user_visible
 * === false`). Nhan duong la nguyen van `providers[].label` cua catalog
 * ("9Router (local)"). Backend khong phan biet "goi thang" voi "self-host",
 * va so chuoi hang voi nhan duong khong dung duoc ("DeepSeek" / "DeepSeek AI")
 * — nen the duong di chi ghi loai "Trung gian" cho duong an (T-S.17, nguoi
 * dung chot).
 *
 * T-4.5 (NQ-139): cot "Doc anh" — ghi de co `vision` qua `PATCH /admin/models/{id}`.
 *
 * B-262 ④ theo ban v2: the khong co do tre, bang khong co cot "Bat" — khong
 * endpoint nao cho hai thu ay (B-258). "Kiem luc" la `checked_at` cua server.
 * Model `enabled: false` van co mat (server tra ca model tat): hang ghi "Dang
 * tat" thay cho tinh trang duong — mot model tat khong "hoat dong" du duong
 * cua no song.
 */

interface RouteCard {
  id: string;
  label: string;
  intermediary: boolean;
  ok: boolean;
  reason: string | null;
  /** Ten hien thi cua cac model DANG BAT di qua duong nay. */
  serves: string[];
}

/** Gom `GET /admin/models` theo duong di, giu thu tu xuat hien trong catalog. */
export function routeCards(models: readonly AdminModelOut[]): RouteCard[] {
  const byRoute = new Map<string, RouteCard>();
  for (const m of models) {
    const card = byRoute.get(m.route.id) ?? {
      id: m.route.id,
      label: m.route.label,
      intermediary: !m.route.user_visible,
      ok: true,
      reason: null,
      serves: [],
    };
    if (!m.health.available) {
      card.ok = false;
      card.reason = card.reason ?? m.health.reason;
    }
    if (m.enabled) {
      card.serves.push(m.display_name);
    }
    byRoute.set(m.route.id, card);
  }
  return [...byRoute.values()];
}

/** "Google AI · qua 9Router (local)" — hang va duong la hai manh rieng. */
function VendorRoute({ model }: { model: AdminModelOut }) {
  return (
    <span>
      <span className="font-medium">{model.provider}</span>
      {!model.route.user_visible && (
        <>
          <span className="text-muted"> · {t("admin.models.via")} </span>
          <span className="font-medium">{model.route.label}</span>
        </>
      )}
    </span>
  );
}

function RouteHealth({ model }: { model: AdminModelOut }) {
  if (!model.enabled) {
    return <span className="text-sm text-muted">{t("admin.models.disabled")}</span>;
  }
  return (
    <>
      <HealthDot ok={model.health.available} />
      {!model.health.available && (
        <span className="block text-xs text-foreground">
          {t("admin.models.failedOnRoute")} <strong>{model.route.label}</strong>
        </span>
      )}
    </>
  );
}

const isFailed = (m: AdminModelOut) => m.enabled && !m.health.available;

const VISION_CHOICES = [
  { value: "catalog", label: "admin.models.vision.catalog" },
  { value: "on", label: "admin.models.vision.on" },
  { value: "off", label: "admin.models.vision.off" },
] as const;

/**
 * T-4.5 (NQ-139) — o chon "Doc anh": theo file catalog, hoac ghi de bat/tat.
 * `<select>` that chu khong cong tac: co BA trang thai, va "theo catalog" phai
 * chon lai duoc. Chu "Co"/"Khong" ben canh la gia tri DANG AP DUNG.
 */
function VisionSelect({
  model,
  busy,
  onChange,
}: {
  model: AdminModelOut;
  busy: boolean;
  onChange: (vision: boolean | null) => void;
}) {
  const value = model.vision_override === null ? "catalog" : model.vision_override ? "on" : "off";
  return (
    <span className="flex items-center gap-2">
      <select
        aria-label={`${t("admin.col.vision")} — ${model.display_name}`}
        value={value}
        disabled={busy}
        onChange={(e) => onChange(e.target.value === "catalog" ? null : e.target.value === "on")}
        className="motion-control min-h-touch rounded-md border border-border-strong bg-background px-3 text-sm text-foreground"
      >
        {VISION_CHOICES.map((c) => (
          <option key={c.value} value={c.value}>
            {t(c.label)}
          </option>
        ))}
      </select>
      <span className="text-sm text-muted">{t(model.vision ? "admin.yes" : "admin.no")}</span>
    </span>
  );
}

export function ModelsScreen() {
  const models = useResource(api.adminModels);
  const [reloading, setReloading] = useState(false);
  const [lastReload, setLastReload] = useState<{ at: number; result: ReloadCatalogOut } | null>(null);
  const [actionError, setActionError] = useState<ApiError | null>(null);
  const [savingVision, setSavingVision] = useState(false);

  const setVision = async (modelId: string, vision: boolean | null) => {
    setSavingVision(true);
    setActionError(null);
    try {
      await api.adminUpdateModel(modelId, { vision });
      await models.reload();
    } catch (e) {
      setActionError(toApiError(e));
    } finally {
      setSavingVision(false);
    }
  };

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

  const checkedAt = models.data?.checked_at ?? null;

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
        // Ban v2 muc 1i: duoi `md` danh sach model dung TRUOC the duong di —
        // cau hoi thuong gap la "model nao dang hong".
        <div className="flex min-w-0 flex-col gap-5">
          <section className="order-2 flex min-w-0 flex-col gap-3 md:order-1">
            <h3 className="text-lg font-semibold text-foreground md:text-xl">{t("admin.models.routes")}</h3>
            <ul className="grid min-w-0 grid-cols-1 gap-2 md:grid-cols-2 md:gap-3 lg:grid-cols-3">
              {routeCards(models.data.models).map((p) => (
                <li
                  key={p.id}
                  className={
                    p.ok
                      ? "flex min-w-0 flex-col gap-1.5 rounded-lg border border-border bg-surface-panel px-3.5 py-3 md:gap-2 md:p-4"
                      : "flex min-w-0 flex-col gap-1.5 rounded-lg border border-danger bg-surface-panel px-3.5 py-3 md:gap-2 md:p-4"
                  }
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="flex min-w-0 flex-wrap items-baseline gap-x-1 md:flex-col md:gap-0.5">
                      <span className="text-base font-semibold text-foreground md:text-body">{p.label}</span>
                      {p.intermediary && (
                        <span className="text-xs text-muted">
                          <span aria-hidden="true" className="md:hidden">
                            ·{" "}
                          </span>
                          {t("admin.models.kind.intermediary")}
                        </span>
                      )}
                    </span>
                    <HealthDot ok={p.ok} />
                  </div>
                  {!p.ok && <FailureReason reason={p.reason} />}
                  <p className="hidden text-xs text-muted md:block">
                    {t("admin.models.servesPrefix")}{" "}
                    <span className="text-foreground">{p.serves.length > 0 ? p.serves.join(", ") : "—"}</span>
                  </p>
                  {checkedAt !== null && (
                    <p className="hidden text-xs text-muted md:block">
                      {t("admin.system.checkedAtPrefix")} <span className="tabular">{formatClock(checkedAt)}</span>
                    </p>
                  )}
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted">{t("admin.models.healthNote")}</p>
          </section>

          <section className="order-1 flex min-w-0 flex-col gap-3 md:order-2">
            <h3 className="text-lg font-semibold text-foreground md:sr-only">{t("admin.models.catalog")}</h3>
            <div className="hidden min-w-0 md:block">
              <TableScroll label={t("admin.models.catalog")}>
                <thead>
                  <tr>
                    <th scope="col" className={TH}>
                      {t("admin.col.model")}
                    </th>
                    <th scope="col" className={TH}>
                      {t("admin.col.vendorRoute")}
                    </th>
                    <th scope="col" className={TH}>
                      {t("admin.col.routeHealth")}
                    </th>
                    <th scope="col" className={TH}>
                      {t("admin.col.vision")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {models.data.models.map((m) => (
                    <tr key={m.id} className={isFailed(m) ? "bg-danger-subtle" : undefined}>
                      <th scope="row" className={`${TD} py-3 text-left font-semibold`}>
                        {m.display_name}
                      </th>
                      <td className={`${TD} py-3`}>
                        <VendorRoute model={m} />
                      </td>
                      <td className={`${TD} py-3`}>
                        <RouteHealth model={m} />
                      </td>
                      <td className={`${TD} py-2`}>
                        <VisionSelect model={m} busy={savingVision} onChange={(v) => void setVision(m.id, v)} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </TableScroll>
            </div>
            <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface-panel md:hidden">
              {models.data.models.map((m) => (
                <li
                  key={m.id}
                  className={`flex flex-col gap-1 px-3.5 py-3 text-sm ${isFailed(m) ? "bg-danger-subtle" : ""}`}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-base font-semibold text-foreground">{m.display_name}</span>
                    <span className="flex-none">
                      {m.enabled ? (
                        <HealthDot ok={m.health.available} />
                      ) : (
                        <span className="text-sm text-muted">{t("admin.models.disabled")}</span>
                      )}
                    </span>
                  </div>
                  <VendorRoute model={m} />
                  {isFailed(m) && (
                    <span className="text-xs text-foreground">
                      {t("admin.models.failedOnRoute")} <strong>{m.route.label}</strong>
                    </span>
                  )}
                  <VisionSelect model={m} busy={savingVision} onChange={(v) => void setVision(m.id, v)} />
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted">{t("admin.models.vision.note")}</p>
          </section>
        </div>
      )}
    </>
  );
}
