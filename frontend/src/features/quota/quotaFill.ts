import { useEffect, useState } from "react";

/**
 * Thanh han muc chay tu 0 — CHI lan mo dau trong mot lan dang nhap. T-S.11.
 *
 * KH tham chieu: §24.2b·S10 · NQ-114 · tasks.md T-S.11 (Cam bay ②), NQ-125 ·
 * ban T-HD5-v2 muc 4 (`.motion-quota-fill`).
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  "MOT LAN DANG NHAP" = MOT GIA TRI `last_login_at`                     ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `sessionStorage` chay lai o moi tab moi, `useRef` chay lai sau moi F5. Chi
 * `last_login_at` cua `/auth/me` doi DUNG luc nguoi dung dang nhap lai (ghi o
 * `POST /auth/login`, KHONG o `refresh` — NQ-125). Nen `localStorage` giu
 * gia tri da chay gan nhat; khac ⇒ chay va ghi lai, giong ⇒ khong chay.
 *
 * Moi loi cua `localStorage` (che do rieng tu nem `SecurityError`) ⇒ KHONG
 * chay, va van render — cung cach `ThemeToggle` boc. Hoat anh la trang tri;
 * mot thanh chay lai MOI lan mo vi khong nho duoc thi sai hon mot thanh
 * khong bao gio chay.
 *
 * `last_login_at: null` (tai khoan chua dang nhap lan nao tu khi cot duoc
 * ghi) ⇒ KHONG chay: khong co gia tri nao phan biet duoc hai lan dang nhap.
 */

const STORAGE_KEY = "scarlet-quota-fill";

/** Doc THUAN — khong ghi gi. `true` = lan mo nay chay thanh tu 0. */
export function shouldFill(lastLoginAt: string | null): boolean {
  if (lastLoginAt === null) {
    return false;
  }
  try {
    return localStorage.getItem(STORAGE_KEY) !== lastLoginAt;
  } catch {
    return false;
  }
}

function markFilled(lastLoginAt: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, lastLoginAt);
  } catch {
    // che do rieng tu — `shouldFill` cung da tra `false`, khong co gi de nho
  }
}

/**
 * Quyet dinh MOT lan luc mount (bo khoi tao cua `useState`, doc thuan), ghi
 * trong effect. Ghi ngay trong bo khoi tao thi `StrictMode` goi no hai lan va
 * lan thu hai doc lai chinh gia tri vua ghi ⇒ khong bao gio chay o dev.
 *
 * Component goi hook nay phai mount KHI da co ho so — quyet dinh tren
 * `last_login_at` chua ve la quyet dinh tren `null`.
 */
export function useQuotaFill(lastLoginAt: string | null): boolean {
  const [fill] = useState(() => shouldFill(lastLoginAt));
  useEffect(() => {
    if (fill && lastLoginAt !== null) {
      markFilled(lastLoginAt);
    }
  }, [fill, lastLoginAt]);
  return fill;
}
