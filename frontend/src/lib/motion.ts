import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";

/**
 * Hoat anh phia JS — T-3.9, theo ban T-HD5.
 *
 * KH tham chieu: §19.1 · tasks.md T-3.9 · CLAUDE.md A3.
 *
 * ╔════════════════════════════════════════════════════════════════════════╗
 * ║  CSS LAM GAN HET; FILE NAY CHI LO PHAN CSS KHONG VOI TOI               ║
 * ╚════════════════════════════════════════════════════════════════════════╝
 *
 * `theme.css` tat moi `transition`/`animation` duoi
 * `@media (prefers-reduced-motion: reduce)`. Con lai hai viec CSS khong lam
 * duoc, ca hai deu o sidebar:
 *
 *   1. **Hen gio go khoi DOM.** Ban T-HD2 noi sidebar dong = 0 px, khong con
 *      gi — nen sau khi thu chieu rong ve 0 thi component phai unmount, va JS
 *      phai biet cho bao lau. Con so doc tu TOKEN (`--duration-normal`), khong
 *      viet tay: doi token la doi luon thoi gian cho.
 *   2. **Noi ro "khong hoat anh" bang mot thuoc tinh.** `useReducedMotion()`
 *      dua component mot `boolean`; component dat `data-motion="none"` va bo
 *      han class `motion-sidebar`, nen dong/mo la tuc thi ke ca khi mot trinh
 *      duyet nao do bo qua khoi `@media`.
 *
 * `REDUCED_MOTION_QUERY` phai la DUNG chuoi trong `theme.css`; `HoatAnh.test.tsx`
 * kiem dieu do, nen hai noi khong the lech nhau ma khong ai biet.
 */

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function queryList(): MediaQueryList | null {
  // `matchMedia` vang mat trong vai WebView cu — coi nhu khong xin giam.
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return null;
  }
  return window.matchMedia(REDUCED_MOTION_QUERY);
}

function subscribe(listener: () => void): () => void {
  const list = queryList();
  if (list === null) {
    return () => {};
  }
  list.addEventListener("change", listener);
  return () => list.removeEventListener("change", listener);
}

function getSnapshot(): boolean {
  return queryList()?.matches ?? false;
}

/** `true` khi nguoi dung xin tat chuyen dong. Tu cap nhat khi ho doi cai dat. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}

/**
 * Doc mot token thoi luong (`--duration-*`) ra mili-giay.
 *
 * Tra `0` khi token rong — jsdom khong nap CSS, va mot trinh duyet chua nap
 * xong stylesheet cung vay. `0` nghia la "khong cho", tuc hanh vi an toan:
 * thay doi hien ra ngay, khong co gi treo.
 */
export function readDurationMs(token: string): number {
  if (typeof window === "undefined") {
    return 0;
  }
  const raw = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  const match = /^(-?[\d.]+)(ms|s)$/.exec(raw);
  if (match === null) {
    return 0;
  }
  const value = Number.parseFloat(match[1]);
  return match[2] === "s" ? value * 1000 : value;
}

export type PresenceState = "open" | "closed";

/**
 * Giu mot phan tu trong DOM du lau de no chay het hoat anh dong, roi go no ra.
 *
 * - Mount lan dau o trang thai mo ⇒ `open` ngay, KHONG hoat anh (F5 khong
 *   duoc lam sidebar truot vao).
 * - Mo ⇒ dung mot khung `closed` truoc, ep trinh duyet tinh style cua no
 *   (`offsetWidth`) roi moi chuyen `open` — khong co khung dau ay thi
 *   `transition` khong co diem xuat phat va phan tu hien ra mot cuc.
 * - Dong ⇒ `closed` ngay, go khoi DOM sau `exitToken` mili-giay. Giam chuyen
 *   dong, hoac token rong/0 ⇒ go ngay trong cung luot.
 */
export function usePresence<T extends HTMLElement>(open: boolean, exitToken: string) {
  const reduced = useReducedMotion();
  const ref = useRef<T>(null);
  const [mounted, setMounted] = useState(open);
  const [state, setState] = useState<PresenceState>(open ? "open" : "closed");

  useEffect(() => {
    if (open) {
      setMounted(true);
      return undefined;
    }
    setState("closed");
    const delay = reduced ? 0 : readDurationMs(exitToken);
    if (delay === 0) {
      setMounted(false);
      return undefined;
    }
    const timer = window.setTimeout(() => setMounted(false), delay);
    return () => window.clearTimeout(timer);
  }, [open, reduced, exitToken]);

  useLayoutEffect(() => {
    if (!open || !mounted || state === "open") {
      return;
    }
    if (!reduced) {
      // Doc de ep style cua khung `closed` duoc tinh truoc khi doi sang `open`.
      void ref.current?.offsetWidth;
    }
    setState("open");
  }, [open, mounted, state, reduced]);

  return { ref, mounted, state, reduced };
}
