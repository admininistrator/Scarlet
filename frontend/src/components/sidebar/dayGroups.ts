import { useEffect, useState } from "react";

import type { ConversationOut } from "../../lib/api";
import { t } from "../../lib/i18n";

/**
 * Nhom hang hoi thoai theo ngay — T-S.13, ban T-HD2-v2 (`ShellSidebar`).
 *
 * KH tham chieu: §24.2b·S8 · NQ-112 · tasks.md T-S.13 (Cam bay ①).
 *
 *   Da ghim · Hom nay · Hom qua · 21/9/2026 · 20/9/2026 …
 *
 * Nhom theo `updated_at` — lan hoat dong gan nhat, dung khoa `ORDER BY` va
 * con tro phan trang cua server (NQ-112), nen cac nhom noi tiep nhau dung thu
 * tu server tra va "Tai them" chi noi them vao nhom cuoi hoac mo nhom moi.
 * Muc "Da ghim" KHONG di qua day: no la nguon rieng (`?pinned=true`).
 *
 * ── Gio MAY NGUOI DUNG, ngay LICH ─────────────────────────────────────────
 *
 * "Hom qua" la ngay lich lien truoc, khong phai "24 gio truoc": 23:50 va 00:10
 * cach nhau hai muoi phut nhung la hai ngay. `localDay` cat gio theo mui gio
 * cua trinh duyet (`getFullYear/Month/Date`), nen `2026-09-22T17:30:00Z` la
 * 00:30 ngay 23/9 o +07 — "Hom nay" khi dong ho la 23/9 (DoD dong 1).
 *
 * ── "Hom nay" la ham cua THOI GIAN (Cam bay ①) ────────────────────────────
 *
 * Tinh mot lan luc render dau thi app mo qua dem van goi hom qua la "Hom nay".
 * `useToday` doc lai dong ho moi khi tab lay lai tieu diem (`focus`, hoac
 * `visibilitychange` sang `visible`) va chi doi gia tri — tuc chi render lai —
 * khi NGAY da doi.
 */

const MS_PER_DAY = 86_400_000;

export interface DayGroup {
  /** Khoa React on dinh: `today`, `yesterday` hoac `d/m/yyyy`. */
  key: string;
  label: string;
  items: ConversationOut[];
}

/** 00:00 gio may cua ngay chua `date`, tinh bang ms. */
function localDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/**
 * Nhan nhom cua mot moc `updated_at` so voi `now`.
 *
 * `Math.round` chu khong chia chan: hai nua dem cach nhau 23 hoac 25 gio o
 * ngay doi gio mua he. Moc TUONG LAI (dong ho may lech so voi server) roi vao
 * "Hom nay" chu khong thanh mot ngay mai khong ai hieu.
 */
export function dayGroupOf(updatedAt: string, now: Date): Pick<DayGroup, "key" | "label"> {
  const date = new Date(updatedAt);
  const daysAgo = Math.round((localDay(now) - localDay(date)) / MS_PER_DAY);
  if (daysAgo <= 0) {
    return { key: "today", label: t("sidebar.today") };
  }
  if (daysAgo === 1) {
    return { key: "yesterday", label: t("sidebar.yesterday") };
  }
  // §24.2b·S8: "ngay viet thang d/m/yyyy" — khong so 0 dung dau.
  const label = `${date.getDate()}/${date.getMonth() + 1}/${date.getFullYear()}`;
  return { key: label, label };
}

/**
 * Chia danh sach (da sap moi nhat truoc) thanh nhom theo ngay, giu thu tu.
 *
 * Gom theo khoa chu khong chi theo hang lien ke: mot hang "tut" giua hai lan
 * nap trang (B-228) van vao dung nhom cua no, khong mo mot nhom trung ten.
 */
export function groupByDay(items: readonly ConversationOut[], now: Date): DayGroup[] {
  const groups = new Map<string, DayGroup>();
  for (const item of items) {
    const { key, label } = dayGroupOf(item.updated_at, now);
    const group = groups.get(key);
    if (group === undefined) {
      groups.set(key, { key, label, items: [item] });
    } else {
      group.items.push(item);
    }
  }
  return [...groups.values()];
}

/** Dong ho cua `groupByDay` — doc lai khi tab lay lai tieu diem (Cam bay ①). */
export function useToday(): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const refresh = () => {
      setNow((previous) => {
        const next = new Date();
        // Cung ngay ⇒ giu nguyen object cu: React bo qua lan render nay.
        return localDay(next) === localDay(previous) ? previous : next;
      });
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        refresh();
      }
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  return now;
}
