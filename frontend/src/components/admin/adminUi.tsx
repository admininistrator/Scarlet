import type { ReactNode } from "react";

import type { ApiError } from "../../lib/api";
import { t } from "../../lib/i18n";
import { formatCount, padMoney } from "./format";

/**
 * Manh dung chung cua sau man quan tri — chep khuon tu `AdminPanel.tsx` cua
 * ban T-HD7 (T-3.12). Class la cua ban ve; component chi noi state vao.
 *
 * KH tham chieu: §16.3, §10.4, C16 · tasks.md T-3.12 (Cam bay ②), NQ-51.
 */

export const TH =
  "border-b border-border px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-muted";
export const TH_NUMBER =
  "border-b border-border px-3 py-2 text-right text-2xs font-semibold uppercase tracking-wider text-muted";
export const TD = "border-b border-border px-3 py-2 align-middle text-foreground";

export function ScreenTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <header className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h2 className="text-2xl font-semibold text-foreground">{children}</h2>
      {aside}
    </header>
  );
}

/** O tien: chuoi nguyen van, can phai, sau chu so thap phan (xem `padMoney`). */
export function MoneyCell({ value }: { value: string }) {
  return <td className={`${TD} money`}>{padMoney(value)}</td>;
}

export function CountCell({ value }: { value: number }) {
  return <td className={`${TD} money`}>{formatCount(value)}</td>;
}

/**
 * Nhan "Cho hieu luc · Da luu luc hh:mm:ss" tren HANG vua doi (ban T-HD7).
 * Cam bay ② cua T-3.12: doi han muc KHONG co hieu luc ngay (NQ-51, TTL cache)
 * — nhan nay la cach man hinh noi dieu that ay tai dung cho no xay ra.
 */
export function PendingBadge({ savedAtLabel }: { savedAtLabel: string }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1 rounded-sm bg-warning-subtle px-1.5 py-0.5 text-2xs font-medium text-warning-text">
      <span>{t("admin.pending")}</span>
      <span aria-hidden="true">·</span>
      <span>{t("admin.savedAtPrefix")}</span>
      <span className="tabular">{savedAtLabel}</span>
    </span>
  );
}

/**
 * "Da luu luc … · Co hieu luc trong vong N giay." — KHONG BAO GIO "da ap dung".
 *
 * `N` la `limits_cache_ttl_s` cua `GET /admin/tiers` (tuc `TIER_CACHE_TTL_S`
 * cua `.env`), khong phai mot so go trong `vi.json` (A3). Chua biet `N` thi
 * cau thu hai vang mat thay vi bia mot con so.
 *
 * Vung `role=status` giu san chieu cao `min-h-touch` ke ca khi rong (ban
 * T-HD7): cau hien ra thi nut ben duoi khong nhay.
 */
export function EffectNotice({
  savedAtLabel,
  ttlSeconds,
}: {
  savedAtLabel?: string;
  ttlSeconds: number | null;
}) {
  return (
    <div role="status" aria-live="polite" className="min-h-touch">
      {savedAtLabel ? (
        <p className="flex flex-wrap items-center gap-x-2 rounded-md border border-warning bg-warning-subtle px-3 py-2 text-sm text-warning-text">
          <span className="font-semibold">
            {t("admin.savedAtPrefix")} <span className="tabular">{savedAtLabel}</span>
          </span>
          {ttlSeconds !== null && (
            <span>
              {t("admin.effectNoticePrefix")} <span className="tabular">{ttlSeconds}</span>{" "}
              {t("admin.effectNoticeSuffix")}
            </span>
          )}
        </p>
      ) : null}
    </div>
  );
}

export function Switch({
  checked,
  label,
  onChange,
  disabled,
}: {
  checked: boolean;
  label: string;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="motion-press group flex size-touch items-center justify-center rounded-md disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span
        className={
          checked
            ? "flex h-6 w-10 items-center justify-end rounded-full bg-accent p-0.5"
            : "flex h-6 w-10 items-center justify-start rounded-full border border-border-strong bg-background p-0.5"
        }
      >
        <span
          className={checked ? "size-5 rounded-full bg-accent-foreground" : "size-4 rounded-full bg-border-strong"}
        />
      </span>
    </button>
  );
}

/** Dau tron = tot, dau thoi = hong: phan biet duoc khong can mau (ban T-HD7). */
export function HealthDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={
        ok
          ? "inline-flex items-center gap-1.5 text-sm font-medium text-success-text"
          : "inline-flex items-center gap-1.5 text-sm font-semibold text-danger-text"
      }
    >
      <span aria-hidden="true" className={ok ? "size-2 rounded-full bg-success" : "size-2 rotate-45 bg-danger"} />
      {ok ? t("admin.health.ok") : t("admin.health.down")}
    </span>
  );
}

/**
 * Ly do hong — B-193 phia man hinh. Chuoi rong / chi khoang trang VAN phai
 * noi duoc dieu gi do: kieu nghieng, mau phu, de phan biet voi ly do that.
 */
export function FailureReason({ reason }: { reason: string | null | undefined }) {
  const isEmpty = reason === null || reason === undefined || reason.trim() === "";
  return (
    <p className={isEmpty ? "text-sm italic text-muted" : "text-sm break-words text-foreground"}>
      <span className="font-semibold not-italic text-danger-text">{t("admin.system.reasonLabel")}: </span>
      {isEmpty ? t("admin.system.reasonEmpty") : reason}
    </p>
  );
}

/**
 * Loi cua `/admin/*` hien NGUYEN VAN ma loi (T-2.19, luat 3 cua `useQuanTri`
 * cu): `401`/`403` o day la server tu choi, va mot bang rong doc y het "khong
 * co ai". `message` cua backend la tieng Viet khong dau, nhung day la man
 * cua nguoi van hanh — `code` moi la thu ho can de tra log.
 */
export function ErrorNotice({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: ApiError;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-danger bg-danger-subtle px-3 py-2 text-sm text-danger-text"
    >
      <p className="min-w-0 break-words">
        <span className="font-semibold">{title}:</span> {error.code} — {error.message}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="motion-press min-h-touch rounded-md border border-border-strong px-3 text-base font-medium text-foreground hover:bg-surface-hover"
        >
          {t("admin.retry")}
        </button>
      )}
    </div>
  );
}

export function LoadingNote() {
  return <p className="text-sm text-muted">{t("admin.dangTai")}</p>;
}
