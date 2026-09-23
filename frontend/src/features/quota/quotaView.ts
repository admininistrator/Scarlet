/**
 * Thanh quota cua UC-07 — phan THUAN tinh toan (T-3.11).
 *
 * KH tham chieu: UC-07, §10.3, §10.5 · tasks.md T-3.0, T-3.11, B-209.
 *
 * Khong React, khong fetch: moi luat "hien gi, chan gi" nam o day de kiem
 * duoc bang mot bang so, va `QuotaBar` + `ChatScreen` doc CUNG mot ham — nut
 * gui va thanh quota khong the tu nghi ra hai dinh nghia "het" khac nhau.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  HAI NGUON, MOT CON SO MOI CUA SO (Cam bay ④)                          ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `/auth/me` (`quota`) va `202` (`quota_warning`) doc cua so o hai thoi diem
 * khac nhau, nen chung LECH — va lech la dung. Thu phai tranh la hien hai con
 * so cua cung mot cua so canh nhau. Luat o day: moi cua so giu DUNG MOT lan
 * doc, lan doc MOI HON thang, va man hinh ghi ro "so lieu luc ...".
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  TIEN LA CHUOI (Cam bay ③)                                             ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * File nay KHONG cong, tru hay so sanh mot con so tien nao. Moi quyet dinh di
 * bang `remaining_pct` (so nguyen server da lam tron XUONG) va `retry_after`
 * (so giay nguyen). `formatUsd` la cho duy nhat doi chuoi sang so, va no doi
 * de HIEN.
 */

import type { QuotaWindow, LimitType, ModelOut, QuotaWarning } from "../../lib/api";

/** Ba muc cua ban Design System muc 05 — moi muc mot token `--color-quota-*`. */
export type QuotaLevel = "normal" | "warning" | "empty";

/** Mot lan doc mot cua so, kem thoi diem no ve toi trinh duyet. */
export interface QuotaReading {
  window: QuotaWindow;
  /** `Date.now()` luc response ve — moc cua `retry_after`. */
  readAt: number;
}

/**
 * Cua so nao dang chan nut gui, va luc nao het chan.
 *
 * `resetAt === null` = biet la het nhung KHONG biet luc nao hoan lai (tier
 * co han muc 0, hoac `remaining_pct` da tron ve 0 ma chi tieu chua vuot tran).
 * Man hinh noi dung nhu vay, khong bia mot moc gio.
 */
export interface QuotaBlock {
  windows: LimitType[];
  resetAt: number | null;
}

/**
 * UC-07 dong 1 + dong 2 tren MOT truc: `0` ⇒ het, `<= warnPct` ⇒ canh bao.
 *
 * `<=` chu khong `<`: chu cua UC-07 la *"con ≤ 20%"*, va `estimator._warning`
 * cua backend bo qua cua so khi `phan_tram > nguong` — tuc 20 dung bang nguong
 * LA canh bao o ca hai phia.
 */
export function quotaLevel(remainingPct: number, warnPct: number): QuotaLevel {
  if (remainingPct <= 0) {
    return "empty";
  }
  return remainingPct <= warnPct ? "warning" : "normal";
}

/**
 * Ghep hai nguon thanh MOT lan doc moi cua so — lan doc moi hon thang.
 *
 * `warnings` la cac `quota_warning` cua `202` ke tu khi mo man hinh. Mot canh
 * bao cu hon lan doc `/auth/me` hien tai bi bo qua: sau `done` FE doc lai
 * `/auth/me`, va con so ay da tinh ca luot vua sinh.
 *
 * `retry_after: null` cho ban lay tu `202`: mot `202` nghia la luot do da QUA
 * cua chan, tuc chua co gi de cho.
 */
export function mergeReadings(
  snapshot: QuotaWindow[] | null,
  snapshotReadAt: number | null,
  warnings: Partial<Record<LimitType, { warning: QuotaWarning; readAt: number }>>,
): QuotaReading[] {
  if (snapshot === null || snapshotReadAt === null) {
    return [];
  }
  return snapshot.map((window) => {
    const next = warnings[window.limit_type];
    if (next === undefined || next.readAt <= snapshotReadAt) {
      return { window, readAt: snapshotReadAt };
    }
    return { window: { ...next.warning, retry_after: null }, readAt: next.readAt };
  });
}

/** `retry_after` (giay, tinh tu `readAt`) → moc gio tuyet doi, hoac `null`. */
export function resetAt(reading: QuotaReading): number | null {
  const seconds = reading.window.retry_after;
  return seconds === null ? null : reading.readAt + seconds * 1000;
}

/**
 * Cac cua so da het, va moc hoan lai MUON NHAT trong so chung.
 *
 * Muon nhat chu khong som nhat: het ca 5 gio lan 7 ngay thi 5 gio hoan lai
 * truoc van chua gui duoc — nut chi mo khi CA HAI da nha.
 */
export function quotaBlock(readings: QuotaReading[]): QuotaBlock | null {
  const exhausted = readings.filter((r) => r.window.remaining_pct <= 0);
  if (exhausted.length === 0) {
    return null;
  }
  const resets = exhausted.map(resetAt);
  const known = resets.every((m): m is number => m !== null);
  return {
    windows: exhausted.map((r) => r.window.limit_type),
    resetAt: known ? Math.max(...resets) : null,
  };
}

/**
 * Nut gui co bi khoa vi quota khong — Cam bay ① cua T-3.11.
 *
 * BYOK van gui duoc khi het quota system key (UC-07 dong 4, §10.5): backend
 * bo qua han cua chan khi model thuoc mot provider ma nguoi nay co khoa rieng
 * giai ma duoc. `byokProviders === null` = chua biet (dang tai hoac loi) ⇒
 * KHONG khoa. Khoa nham mot nguoi dang tu tra tien la hong that; mo nham mot
 * nut thi server van tra `429` va man hinh noi ly do.
 */
export function isSendBlocked(
  block: QuotaBlock | null,
  byokProviders: ReadonlySet<string> | null,
  provider: string | null,
): boolean {
  if (block === null) {
    return false;
  }
  if (byokProviders === null) {
    return false;
  }
  return !byokCovers(byokProviders, provider);
}

/** Model dang chon co di bang khoa rieng cua nguoi dung khong. */
export function byokCovers(byokProviders: ReadonlySet<string> | null, provider: string | null) {
  return byokProviders !== null && provider !== null && byokProviders.has(provider);
}

/**
 * Khoa provider cua model SE GUI — ve thu hai cua `byokCovers`/`isSendBlocked`.
 *
 * B-257: `provider_id` (khoa catalog, `deepseek`), KHONG phai `provider` (nhan,
 * `DeepSeek AI`). Tap `byokProviders` den tu `ProviderKey.provider`, tuc la
 * khoa; so voi nhan thi khong bao gio khop va nguoi co khoa rieng bi khoa nut
 * gui dung luc Cam bay ① cua T-3.11 hua la khong.
 */
export function selectedProviderId(
  models: readonly Pick<ModelOut, "id" | "provider_id">[],
  modelId: string | null,
): string | null {
  return models.find((m) => m.id === modelId)?.provider_id ?? null;
}

/**
 * Cua so can canh bao (UC-07 dong 1): cua so con IT phan tram nhat trong
 * so nhung cua so o muc `warning` — cung luat chon `min` cua
 * `estimator._warning`, vi do la cua so se chan nguoi dung truoc.
 */
export function warningReading(readings: QuotaReading[], warnPct: number): QuotaReading | null {
  const warnings = readings.filter((r) => quotaLevel(r.window.remaining_pct, warnPct) === "warning");
  if (warnings.length === 0) {
    return null;
  }
  return warnings.reduce((a, b) => (b.window.remaining_pct < a.window.remaining_pct ? b : a));
}

/** `Decimal` cua backend la CHUOI — doi sang so DUNG MOT LAN, de hien. */
export function formatUsd(amount: string): string {
  return Number(amount).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 4,
  });
}
