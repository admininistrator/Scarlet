/**
 * State cua thanh quota — T-3.11. Luat nam o `quotaView.ts`; day chi giu
 * nhung gi phai song qua nhieu lan render.
 *
 * KH tham chieu: UC-07, §10.3, §10.5 · tasks.md T-3.11, B-209.
 *
 * Ba thu, khong hon:
 *
 *   1. Cac `quota_warning` cua `202` (nguon thu hai — xem `mergeReadings`).
 *   2. Tap provider nguoi nay co khoa BYOK dung duoc (`GET /settings/keys`),
 *      hoi MOT lan luc mount: khoa chi doi o trang Cai dat, tuc mot route
 *      khac, va quay lai day la mount lai.
 *   3. MOT hen gio dung luc quota hoan lai, de nut gui tu mo ma khong can F5.
 *      Day KHONG phai bo dem lam tuoi cua B-209: no ban dung mot lan, vao dung
 *      thoi diem con so tren server doi — va huy ngay khi `resetAt` doi.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import type { Phien } from "../auth/usePhien";
import { api, type LoaiHanMuc, type QuotaWarning } from "../../lib/api";
import { mergeReadings, quotaBlock, type QuotaBlock, type QuotaReading } from "./quotaView";

/**
 * Hen gio toi thieu, ms. Khong phai mot han muc san pham (A3) ma mot chot an
 * toan: `retry_after` da qua (mang cham, may ngu) cho ra do tre am, va neu
 * `/auth/me` van bao het (cache tier 60 s — Cam bay ②) thi khong co chot nay
 * se thanh mot vong goi lien tuc.
 */
const MIN_REFRESH_DELAY_MS = 1000;

export interface QuotaState {
  readings: QuotaReading[];
  /** Nguong "con <= N%" tu `/auth/me` — `null` khi chua co ho so. */
  warnPct: number | null;
  block: QuotaBlock | null;
  /** `null` = chua biet (dang tai hoac loi) — xem `isSendBlocked`. */
  byokProviders: ReadonlySet<string> | null;
  /** Nguoi nghe `onQuotaWarning` cua `useChat`. */
  noteWarning: (warning: QuotaWarning) => void;
}

type Warnings = Partial<Record<LoaiHanMuc, { warning: QuotaWarning; readAt: number }>>;

export function useQuota(
  session: Pick<Phien, "hoSo" | "profileReadAt" | "refreshProfile">,
): QuotaState {
  const { hoSo, profileReadAt, refreshProfile } = session;
  const [warnings, setWarnings] = useState<Warnings>({});
  const [byokProviders, setByokProviders] = useState<ReadonlySet<string> | null>(null);

  useEffect(() => {
    let conGan = true;
    api
      .listProviderKeys()
      .then((ra) => {
        if (conGan) {
          // `usable === false` = khoa khong giai ma duoc: backend roi ve
          // system key va TRU quota (`credentials._byok_key`), nen no khong
          // mo khoa nut gui.
          setByokProviders(new Set(ra.keys.filter((k) => k.usable).map((k) => k.provider)));
        }
      })
      .catch(() => {
        // De `null` — "chua biet" mo nut chu khong khoa nut (Cam bay ①).
      });
    return () => {
      conGan = false;
    };
  }, []);

  const noteWarning = useCallback((warning: QuotaWarning) => {
    setWarnings((cu) => ({ ...cu, [warning.limit_type]: { warning, readAt: Date.now() } }));
  }, []);

  const readings = useMemo(
    () => mergeReadings(hoSo?.quota ?? null, profileReadAt, warnings),
    [hoSo, profileReadAt, warnings],
  );
  const block = useMemo(() => quotaBlock(readings), [readings]);
  const moc = block?.resetAt ?? null;

  useEffect(() => {
    if (moc === null) {
      return;
    }
    const id = window.setTimeout(
      () => void refreshProfile(),
      Math.max(moc - Date.now(), MIN_REFRESH_DELAY_MS),
    );
    return () => window.clearTimeout(id);
  }, [moc, refreshProfile]);

  return {
    readings,
    warnPct: hoSo?.quota_warn_remaining_pct ?? null,
    block,
    byokProviders,
    noteWarning,
  };
}
