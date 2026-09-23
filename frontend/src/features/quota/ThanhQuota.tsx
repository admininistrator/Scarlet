import type { LoaiHanMuc } from "../../lib/api";
import { t, type KhoaChu } from "../../lib/i18n";
import {
  formatUsd,
  quotaLevel,
  warningReading,
  type QuotaBlock,
  type QuotaLevel,
  type QuotaReading,
} from "./quotaView";

/**
 * Thanh quota cua UC-07 — hai cua so, canh bao ≤ N%, man het quota. T-3.11.
 *
 * KH tham chieu: UC-07, §10.3 · Design System (T-HD1) muc 05 "Thanh quota":
 * *"Ba muc khong chi khac mau: con so phan tram luon di kem, vi mau mot minh
 * khong phai la thong tin."* Rail 8 px bo tron, nhan 13 px trai, phan tram
 * `tabular` phai; muc canh bao/het them `font-semibold` + mau chu tuong ung.
 *
 * Component nay KHONG khoa nut gui: no chi noi. Nut gui nam trong `Composer`
 * va doc `isSendBlocked` cua `quotaView.ts` — cung `QuotaBlock` ma man hinh
 * nay ve, nen hai thu khong the noi hai chuyen khac nhau.
 *
 * Khong co chu "da ap dung" nao o day (Cam bay ②): doi han muc co hieu luc
 * trong ≤ 60 s chu khong tuc thi, va man hinh chi noi dieu no DA DOC, kem
 * gio doc.
 */

const WINDOW_LABEL: Record<LoaiHanMuc, KhoaChu> = {
  "5h": "quota.window.5h",
  weekly: "quota.window.weekly",
};

const FILL: Record<QuotaLevel, string> = {
  normal: "bg-quota-normal",
  warning: "bg-quota-warning",
  empty: "bg-quota-empty",
};

const PCT_TEXT: Record<QuotaLevel, string> = {
  normal: "text-muted",
  warning: "font-semibold text-warning-text",
  empty: "font-semibold text-danger-text",
};

/**
 * Moc gio DAY DU toi giay — UC-07 doi *"thoi diem chinh xac"*, va DoD so no
 * voi `Retry-After` trong ±2 s. Khac ngay thi them thu + ngay: cua so 7 ngay
 * co the hoan lai vao mot ngay khac.
 */
function formatMoment(ms: number, now: number): string {
  const luc = new Date(ms);
  const cungNgay = new Date(now).toDateString() === luc.toDateString();
  return luc.toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    ...(cungNgay ? {} : { weekday: "long", day: "2-digit", month: "2-digit" }),
  });
}

function Moment({ ms, now }: { ms: number; now: number }) {
  return (
    <time dateTime={new Date(ms).toISOString()} className="tabular">
      {formatMoment(ms, now)}
    </time>
  );
}

function windowNames(windows: LoaiHanMuc[]): string {
  return windows.map((w) => t(WINDOW_LABEL[w])).join(` ${t("quota.and")} `);
}

export function QuotaBar({
  readings,
  warnPct,
  block,
  byokCovered,
  now = Date.now(),
}: {
  readings: QuotaReading[];
  /** `quota_warn_remaining_pct` cua `/auth/me`; `null` ⇒ khong ve gi. */
  warnPct: number | null;
  block: QuotaBlock | null;
  /** Model dang chon di bang khoa BYOK — het quota van gui duoc (Cam bay ①). */
  byokCovered: boolean;
  /** Tiem duoc de test on dinh; mac dinh la luc render. */
  now?: number;
}) {
  // `quota: null` = chua do duoc (Redis chop) — an thanh, KHONG ve mot thanh
  // rong (docstring `HoSoRa.quota`).
  if (readings.length === 0 || warnPct === null) {
    return null;
  }
  const canhBao = block === null ? warningReading(readings, warnPct) : null;
  // Moc CU NHAT: "so lieu luc X" la mot can duoi trung thuc cho ca hai hang.
  const docLuc = Math.min(...readings.map((r) => r.readAt));

  return (
    <section aria-label={t("quota.label")} className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {readings.map(({ window: w }) => {
          const muc = quotaLevel(w.remaining_pct, warnPct);
          const nhan = t(WINDOW_LABEL[w.limit_type]);
          return (
            <div key={w.limit_type} className="flex min-w-0 flex-col gap-1.5" data-level={muc}>
              <div className="flex justify-between gap-2 text-sm">
                <span className="truncate">{nhan}</span>
                <span className={`tabular ${PCT_TEXT[muc]}`}>{w.remaining_pct}%</span>
              </div>
              <div
                role="meter"
                aria-label={`${t("quota.label")} ${nhan}`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={w.remaining_pct}
                className="h-2 overflow-hidden rounded-full bg-quota-track"
              >
                <div
                  className={`motion-quota h-full ${FILL[muc]}`}
                  style={{ width: `${w.remaining_pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {block !== null && !byokCovered && (
        <div
          role="alert"
          className="rounded-md border border-border bg-danger-subtle px-3 py-2 text-sm text-danger-text"
        >
          <span className="font-semibold">
            {t("quota.exhausted")} {windowNames(block.windows)}.
          </span>{" "}
          {block.resetAt === null ? (
            t("quota.resetUnknown")
          ) : (
            <>
              {t("quota.resetAt")} <Moment ms={block.resetAt} now={now} />.
            </>
          )}
        </div>
      )}

      {block !== null && byokCovered && (
        <p role="status" className="text-sm text-muted">
          {t("quota.exhausted")} {windowNames(block.windows)}. {t("quota.byok")}
        </p>
      )}

      {canhBao !== null && (
        <div
          role="status"
          className="rounded-md border border-border bg-warning-subtle px-3 py-2 text-sm text-warning-text"
        >
          <span className="font-semibold">
            {t("quota.warning")} {t(WINDOW_LABEL[canhBao.window.limit_type])}:
          </span>{" "}
          {t("quota.remaining")} {formatUsd(canhBao.window.remaining_usd)} (
          {canhBao.window.remaining_pct}%). {t("quota.stillSend")}
        </div>
      )}

      <p className="text-xs text-muted">
        {t("quota.readAt")} <Moment ms={docLuc} now={now} />
      </p>
    </section>
  );
}
