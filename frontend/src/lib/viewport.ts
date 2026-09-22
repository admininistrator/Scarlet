import { useSyncExternalStore } from "react";

/**
 * Be rong man hinh o phia JS — T-3.10, theo ban T-HD2.
 *
 * KH tham chieu: §2.3 (S8) · tasks.md T-3.10.
 *
 * Ban T-HD2 noi sidebar la **drawer duoi 1024 px** (`--spacing-drawer`), tuc
 * dung moc `lg` cua Tailwind (`64rem`). Bo cuc thuan CSS thi cac class `lg:`
 * lo; nhung drawer con can JS biet minh dang o che do nao — Esc, cham ra
 * ngoai, khoa cuon phia sau, tra tieu diem ve nut mo — nen chuoi truy van phai
 * ton tai o day, va phai la DUNG moc `lg` (`max-width` = `64rem` tru 1 px).
 * `Drawer.test.tsx` doc hang so nay, khong go lai chuoi.
 */
export const DRAWER_QUERY = "(max-width: 1023px)";

/** `true` khi truy van khop. Theo doi song — xoay may, keo cua so. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (listener) => {
      // `matchMedia` vang mat trong vai WebView cu — coi nhu khong khop.
      if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
        return () => {};
      }
      const list = window.matchMedia(query);
      list.addEventListener("change", listener);
      return () => list.removeEventListener("change", listener);
    },
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia(query).matches,
    () => false,
  );
}

/** Man hinh hep: sidebar la drawer phu len, khong phai cot day bo cuc. */
export function useDrawerMode(): boolean {
  return useMediaQuery(DRAWER_QUERY);
}
