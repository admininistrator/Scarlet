import { DISPLAY_LOCALE } from "../../lib/i18n";

/**
 * Moc gio DAY DU toi giay — UC-07 doi *"thoi diem chinh xac"*, va DoD cua
 * T-3.11 so no voi `Retry-After` trong ±2 s. Khac ngay thi them thu + ngay:
 * cua so 7 ngay co the hoan lai vao mot ngay khac.
 *
 * Tach khoi `QuotaBar.tsx` o T-S.10: dong han muc tren o nhap (`QuotaNotice`)
 * va hai thanh o Cai dat (T-S.11) phai noi CUNG mot moc theo cung mot cach.
 */
export function formatMoment(ms: number, now: number): string {
  const at = new Date(ms);
  const sameDay = new Date(now).toDateString() === at.toDateString();
  return at.toLocaleString(DISPLAY_LOCALE, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    ...(sameDay ? {} : { weekday: "long", day: "2-digit", month: "2-digit" }),
  });
}

export function Moment({ ms, now, className }: { ms: number; now: number; className?: string }) {
  return (
    <time dateTime={new Date(ms).toISOString()} className={`tabular ${className ?? ""}`}>
      {formatMoment(ms, now)}
    </time>
  );
}
