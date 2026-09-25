/**
 * Dinh dang cho man quan tri — THUAN, khong React (T-3.12, ban T-HD7).
 *
 * KH tham chieu: §16.3, §9.5, C16 · tasks.md T-2.19, T-3.11 (Cam bay ③).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  TIEN LA CHUOI, VA O DAY NO VAN LA CHUOI                               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * Ban T-HD7: *"Tien la chuoi nguyen van tu DB, can phai, tabular-nums, cung 6
 * chu so thap phan nen dau cham thang hang. Khong co o nao do giao dien tu
 * cong."* `padMoney` chi THEM so 0 vao duoi phan thap phan — mot phep noi
 * chuoi, khong mot phep doi sang `number` nao — nen `"0"` (tong rong cua
 * server) va `"0.1"` (gia tri go tay) dung thang cot voi `"0.000109"` ma
 * khong chu so nao bi lam tron. Chuoi dai hon sau chu so giu nguyen.
 */

import { DISPLAY_LOCALE } from "../../lib/i18n";

/** So chu so thap phan cua cot `NUMERIC(12,6)` — `usage_events.cost_usd`. */
export const MONEY_SCALE = 6;

export function padMoney(amount: string, scale: number = MONEY_SCALE): string {
  const [whole, fraction = ""] = amount.split(".");
  if (fraction.length >= scale) {
    return amount;
  }
  return `${whole}.${fraction.padEnd(scale, "0")}`;
}

const numberFormat = new Intl.NumberFormat(DISPLAY_LOCALE);

/** So nguyen (so hoi thoai, token, luot goi) — khong phai tien. */
export function formatCount(value: number): string {
  return numberFormat.format(value);
}

/**
 * Ngay/gio theo DUNG thu tu cua ban T-HD7 (`22/09/2026 09:14`, `22/09 14:32`).
 *
 * Lap tu `formatToParts` chu khong dung `format()` tron: ICU cua `vi-VN` dat
 * GIO truoc NGAY va doi dau `/` thanh `-` tuy phien ban (do tren Chromium
 * 2026-09-23: `04:37 23-09`) — mot man hinh doi dinh dang theo trinh duyet la
 * mot cot "Luc nao" khong so thang duoc giua hai may.
 */
const partsFormat = new Intl.DateTimeFormat(DISPLAY_LOCALE, {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function parts(iso: string): Record<"day" | "month" | "year" | "hour" | "minute", string> {
  const output = { day: "", month: "", year: "", hour: "", minute: "" };
  for (const p of partsFormat.formatToParts(new Date(iso))) {
    if (p.type in output) {
      output[p.type as keyof typeof output] = p.value;
    }
  }
  return output;
}

/** `22/09/2026 09:14` — thoi diem dang ky (man Duyet), kiem khoa (Cai dat). */
export function formatDateTime(iso: string): string {
  const p = parts(iso);
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}`;
}

/** `09:14 · 12/09/2026` — "Them luc" cua khoa API (ban T-HD9). */
export function formatClockDate(iso: string): string {
  const p = parts(iso);
  return `${p.hour}:${p.minute} · ${p.day}/${p.month}/${p.year}`;
}

/** `22/09 14:32` — cot "Luc nao" cua so audit. */
export function formatShortDateTime(iso: string): string {
  const p = parts(iso);
  return `${p.day}/${p.month} ${p.hour}:${p.minute}`;
}

const clockFormat = new Intl.DateTimeFormat(DISPLAY_LOCALE, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/** `14:32:05` — "Da luu luc", "Kiem luc". */
export function formatClock(value: string | number | Date): string {
  return clockFormat.format(new Date(value));
}

/**
 * Khoa cua truc "theo ngay" (`2026-09-16`) → `16/9`.
 *
 * Tach chuoi chu khong `new Date(...)`: mot ngay ISO khong kem gio bi JS doc
 * la nua dem UTC, va o mui gio am no lui ve ngay hom truoc.
 */
export function formatDayKey(key: string): string {
  const [, month, day] = key.split("-");
  if (month === undefined || day === undefined) {
    return key;
  }
  return `${Number(day)}/${Number(month)}`;
}

/** 8 ky tu dau cua mot id — de tra log khi nguoi ay da xoa (ban T-HD7). */
export function shortId(id: string): string {
  return id.slice(0, 8);
}
