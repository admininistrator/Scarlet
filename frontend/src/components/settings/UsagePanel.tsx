import { CircleAlert, Clock, Gauge, Info } from "lucide";
import { useId } from "react";
import { Link } from "react-router";

import { useSession } from "../../app/Layout";
import { PATHS } from "../../app/paths";
import { Moment } from "../../features/quota/Moment";
import { useQuotaFill } from "../../features/quota/quotaFill";
import {
  WINDOW_LABEL,
  mergeReadings,
  quotaLevel,
  resetAt,
  type QuotaLevel,
  type QuotaReading,
} from "../../features/quota/quotaView";
import type { ProfileOut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { StaticIcon } from "../ui/Icon";

/**
 * Tab Muc su dung — hai cua so quota cua T-3.11 doi sang Cai dat. T-S.11,
 * ban T-HD9 E/H1/H2 (`SettingsUsage`, `QuotaCard`).
 *
 * KH tham chieu: UC-07, §10.3, §10.4 · NQ-114 · tasks.md T-3.11, T-S.10, T-S.11.
 *
 * - **Luat "het / sap het" la cua `quotaView.ts`** — cung `quotaLevel` ma dong
 *   han muc tren o nhap (T-S.10) va nut Gui doc, voi nguong
 *   `quota_warn_remaining_pct` cua `/auth/me` (khong literal 20 — A3).
 * - **Phan to = da dung, con so = phan con lai** (bang "Con so" cua ban ve).
 *   Thanh `aria-hidden`: chu o tren da mang toan bo thong tin.
 * - **Thanh chay tu 0 chi lan mo dau moi lan dang nhap** (`useQuotaFill`,
 *   NQ-114). Cac lan sau: `.motion-quota` (v1) — doi do rong thi truot, mount
 *   thi hien thang gia tri.
 * - **"Hoan lai luc" chi khi server noi duoc.** `retry_after` chi co khi da
 *   VUOT tran (`app/quota/snapshot.py`): cua so truot chua het thi khong co
 *   mot "luc hoan lai" nao. Ban ve ghi gio ca o cua so 64% — lech bi du lieu
 *   ep, da bao lai; cung luat "server khong gui thi o bien mat" cua T-3.12.
 *   Gio toi GIAY qua `Moment` (B-296: cung cach noi voi dong han muc).
 * - **`quota: null`** (Redis chop) ⇒ AN hai the, khong ve mot thanh rong
 *   (docstring `ProfileOut.quota`, T-3.11).
 * - **"Co hieu luc trong vong N giay"** — N la `limits_cache_ttl_s` cua
 *   `/auth/me` (`TIER_CACHE_TTL_S`, chot 2026-09-26), khong phai `60` go tay.
 *   Khong chu "da ap dung" nao (Cam bay ② cua T-3.11).
 */

const FILL: Record<QuotaLevel, string> = {
  normal: "bg-quota-normal",
  warning: "bg-quota-warning",
  empty: "bg-quota-empty",
};

const TONE: Record<QuotaLevel, string> = {
  normal: "text-foreground",
  warning: "text-warning-text",
  empty: "text-danger-text",
};

export function UsagePanel() {
  const session = useSession();
  const profile = session.profile;
  if (profile === null) {
    return null;
  }
  const readings = mergeReadings(profile.quota, session.profileReadAt, {});

  return (
    <div className="flex flex-col gap-4">
      {readings.length > 0 && <QuotaCards profile={profile} readings={readings} />}
      <div className="flex gap-3 rounded-lg border border-border px-4 pt-3.5 pb-1.5">
        <StaticIcon icon={Info} size={18} className="mt-0.5 shrink-0 text-muted" />
        <div className="flex min-w-0 flex-col items-start">
          <p className="text-base">{t("usage.byokNote")}</p>
          <Link to={PATHS.settingsApiKeys} className="inline-flex min-h-touch items-center text-base font-semibold">
            {t("usage.byokLink")}
          </Link>
        </div>
      </div>
      <p className="text-sm text-muted">
        {t("usage.adminNotePrefix")} <span className="tabular">{profile.limits_cache_ttl_s}</span>{" "}
        {t("usage.adminNoteSuffix")}
      </p>
    </div>
  );
}

/**
 * Mount CHI khi da co so lieu de ve: `useQuotaFill` quyet dinh (va ghi nho)
 * ngay lan mount, nen mount luc `quota: null` la "da chay" ma khong ai thay.
 */
function QuotaCards({ profile, readings }: { profile: ProfileOut; readings: QuotaReading[] }) {
  const fill = useQuotaFill(profile.last_login_at);
  const now = Date.now();
  return (
    <>
      {readings.map((reading) => (
        <QuotaCard
          key={reading.window.limit_type}
          reading={reading}
          warnPct={profile.quota_warn_remaining_pct}
          fill={fill}
          now={now}
        />
      ))}
    </>
  );
}

function QuotaCard({
  reading,
  warnPct,
  fill,
  now,
}: {
  reading: QuotaReading;
  warnPct: number;
  fill: boolean;
  now: number;
}) {
  const titleId = useId();
  const w = reading.window;
  const level = quotaLevel(w.remaining_pct, warnPct);
  const remaining = Math.min(100, Math.max(0, w.remaining_pct));
  const reset = resetAt(reading);

  return (
    <section
      aria-labelledby={titleId}
      data-level={level}
      className="flex flex-col gap-3 rounded-lg border border-border bg-surface-panel px-5 py-4.5"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 id={titleId} className="text-lg font-semibold">
            {t(WINDOW_LABEL[w.limit_type])}
          </h3>
          {level === "warning" && (
            <span className="flex items-center gap-1.5 text-sm text-warning-text">
              <StaticIcon icon={Gauge} size={15} className="shrink-0" />
              {t("usage.lowWarning")}
            </span>
          )}
          {level === "empty" && (
            <span className="flex items-center gap-1.5 text-sm text-danger-text">
              <StaticIcon icon={CircleAlert} size={15} className="shrink-0" />
              {t("usage.empty")}
            </span>
          )}
        </div>
        <p className="flex shrink-0 items-baseline gap-1.5">
          <span className="text-sm text-muted">{t("usage.remainingPrefix")}</span>
          <span className={`tabular text-2xl font-semibold ${TONE[level]}`}>{remaining}%</span>
        </p>
      </div>
      <div aria-hidden="true" className="h-quota-bar overflow-hidden rounded-full bg-quota-track">
        <div
          data-testid="quota-fill"
          className={`${fill ? "motion-quota-fill" : "motion-quota"} h-full rounded-full ${FILL[level]}`}
          style={{ width: `${100 - remaining}%` }}
        />
      </div>
      {(reset !== null || level === "empty") && (
        <p className="flex flex-wrap items-center gap-1.5 text-sm text-muted">
          <StaticIcon icon={Clock} size={15} className="shrink-0" />
          {reset === null ? (
            <span>{t("quota.resetUnknown")}</span>
          ) : (
            <>
              <span>{t("usage.resetAt")}</span>
              <Moment ms={reset} now={now} className="font-semibold text-foreground" />
            </>
          )}
        </p>
      )}
    </section>
  );
}
