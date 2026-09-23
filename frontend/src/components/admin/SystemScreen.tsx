import { useCallback, useEffect, useState } from "react";

import { toApiError, useResource } from "../../features/admin/useResource";
import { ApiError, api, type DeepHealth, type HealthCheck } from "../../lib/api";
import { t } from "../../lib/i18n";
import { ErrorNotice, FailureReason, HealthDot, LoadingNote, ScreenTitle } from "./adminUi";
import { formatClock, formatCount } from "./format";

/**
 * Man 1e "He thong" — §16.3, §21.2, ban T-HD7 · T-2.20 → T-3.12.
 *
 * KH tham chieu: §16.3, §18.6, §21.2, C21 · tasks.md T-2.7, T-2.20, T-3.12
 * (Cam bay ①), B-190, B-192, B-193.
 *
 * ── B-192: so lieu co the cu vai giay, va man hinh NOI ra ───────────────────
 *
 * `GET /admin/system` nho ket qua healthcheck `ADMIN_HEALTH_CACHE_TTL_S` giay
 * o server (mot tab, hai tab, hai admin, chuoi F5 — cung MOT luot do). Moi
 * muc in "Kiem luc hh:mm:ss" theo `health_checked_at` cua server, khong theo
 * luc trinh duyet nhan response. Hang doi va stream thi luon doc tuoi.
 *
 * ── B-193: ly do hong khong bao gio la khoang trang ─────────────────────────
 *
 * Server da sua (`describe_error`), va `FailureReason` van giu duong lui cua
 * ban T-HD7 cho chuoi rong: kieu nghieng, mau phu, "Xem log cua dich vu nay".
 *
 * ── Cam bay ① / B-190: Redis chet thi chinh man nay bi `503` ────────────────
 *
 * `require_app_access` tra blacklist o Redis va C21 chot *"Redis chet ⇒ 503,
 * KHONG cho qua"* — lop chan dung TRUOC `/admin/system`. Man nay KHONG thiet
 * ke quanh mot cau tra loi khong toi duoc, va KHONG tu noi C21: gap loi
 * `5xx` (hoac mat mang) no hien nguyen van loi ay, roi hoi `GET /health/deep`
 * — endpoint cong khai san co (§18.6), do tuoi, khong di qua Redis — va ve
 * cung danh sach healthcheck tu do. Nguoi van hanh doc duoc "redis — Loi — Ly
 * do: …" dung luc can, ma khong cua nao duoc mo them.
 */

function isServerFailure(error: ApiError): boolean {
  return error.status === 0 || error.status >= 500;
}

export function SystemScreen() {
  const status = useResource(api.adminSystem);
  const [fallback, setFallback] = useState<{ health: DeepHealth; at: number } | null>(null);
  const [fallbackError, setFallbackError] = useState<ApiError | null>(null);

  const loadFallback = useCallback(async () => {
    try {
      const health = await api.healthDeep();
      setFallback({ health, at: Date.now() });
      setFallbackError(null);
    } catch (e) {
      setFallbackError(toApiError(e));
    }
  }, []);

  useEffect(() => {
    if (status.error !== null && isServerFailure(status.error)) {
      void loadFallback();
    } else {
      setFallback(null);
    }
  }, [status.error, loadFallback]);

  const data = status.data;
  return (
    <>
      <ScreenTitle>{t("admin.system.title")}</ScreenTitle>

      {status.error && (
        <ErrorNotice title={t("admin.loadError")} error={status.error} onRetry={() => void status.reload()} />
      )}

      {status.error !== null && isServerFailure(status.error) ? (
        <>
          <div className="flex flex-col gap-1 rounded-lg border border-warning bg-warning-subtle px-4 py-3 text-sm text-warning-text">
            <p className="font-semibold">{t("admin.system.fallbackTitle")}</p>
            <p>{t("admin.system.fallbackBody")}</p>
          </div>
          {fallbackError && <ErrorNotice title={t("admin.loadError")} error={fallbackError} />}
          {fallback !== null && <HealthList checks={fallback.health.checks} checkedAt={fallback.at} />}
        </>
      ) : data === null ? (
        status.loading && <LoadingNote />
      ) : (
        <>
          <dl className="grid min-w-0 grid-cols-2 gap-3 sm:grid-cols-3">
            <StatTile
              label={t("admin.system.queue")}
              value={data.queue_depth === null ? null : formatCount(data.queue_depth)}
              unit={t("admin.system.queueUnit")}
            />
            <StatTile
              label={t("admin.system.streams")}
              value={data.streams_dang_chay === null ? null : formatCount(data.streams_dang_chay)}
            />
            <div className="col-span-2 flex min-w-0 flex-col gap-1 rounded-lg border border-border bg-surface-panel p-4 sm:col-span-1">
              <dt className="text-sm text-muted">{t("admin.system.version")}</dt>
              <dd className="break-all font-mono text-lg font-medium text-foreground">{data.version}</dd>
            </div>
          </dl>
          <HealthList checks={data.health} checkedAt={data.health_checked_at} />
        </>
      )}
    </>
  );
}

/** `null` = nguon ay khong tra loi — KHONG hien `0` (mot `0` doc la "rong"). */
function StatTile({ label, value, unit }: { label: string; value: string | null; unit?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-lg border border-border bg-surface-panel p-4">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="flex items-baseline gap-1.5 text-foreground">
        {value === null ? (
          <span className="text-sm italic text-muted">{t("admin.system.unknown")}</span>
        ) : (
          <>
            <span className="tabular text-2xl font-semibold">{value}</span>
            {unit ? <span className="text-sm text-muted">{unit}</span> : null}
          </>
        )}
      </dd>
    </div>
  );
}

function HealthList({
  checks,
  checkedAt,
}: {
  checks: Record<string, HealthCheck>;
  checkedAt: string | number;
}) {
  const at = formatClock(checkedAt);
  return (
    <>
      <h3 className="text-xl font-semibold text-foreground">{t("admin.system.healthcheck")}</h3>
      <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface-panel">
        {Object.entries(checks).map(([name, check]) => (
          <li
            key={name}
            className={
              check.ok ? "flex min-w-0 flex-col gap-1.5 px-4 py-3" : "flex min-w-0 flex-col gap-1.5 bg-danger-subtle px-4 py-3"
            }
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-sm font-medium text-foreground">{name}</span>
              <HealthDot ok={check.ok} />
            </div>
            {check.ok ? null : <FailureReason reason={check.error} />}
            <p className="flex flex-wrap gap-x-3 text-xs text-muted">
              <span>
                <span className="tabular">{formatCount(check.latency_ms)}</span> {t("admin.system.elapsedSuffix")}
              </span>
              <span>
                {t("admin.system.checkedAtPrefix")} <span className="tabular">{at}</span>
              </span>
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}
