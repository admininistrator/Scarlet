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

/**
 * FLIP cua khung o nhap — T-S.10, ban T-HD5-v2 muc 1 (`.motion-dock`).
 *
 * Man nhap dat o nhap GIUA man, trong hoi thoai thi o DAY; `docked` doi la
 * bo cuc doi mot phat. Hook nay do dinh khung o moi lan commit, va khi `docked`
 * vua doi thi ghi hieu so (vi tri cu − vi tri moi) vao `--dock-from` roi gan
 * `data-dock="run"`: keyframe `scarlet-dock` dua khung tu cho cu ve cho moi
 * bang `transform`. CHI khung co hoat anh — khong phan tu chu dang stream nao
 * (Cam bay ② cua T-S.10, T-3.9 ①).
 *
 * Do o MOI lan commit (effect khong mang deps), khong chi luc `docked` doi: vi
 * tri "cu" phai la vi tri ngay truoc lan doi, ma o nhap tu gian ra theo chu go,
 * dong han muc hien/an — mot lan do tu luc mount da cu tu lau.
 *
 * Giam chuyen dong ⇒ KHONG gan `data-dock`: khung nhay thang xuong day (DoD
 * dong 4). `theme.css` cung tat animation o `@media`, nhung khong gan gi ca
 * thi phep do trong jsdom (khong nap CSS) moi co nghia.
 */
export function useDock<T extends HTMLElement>(docked: boolean) {
  const reduced = useReducedMotion();
  const ref = useRef<T>(null);
  const lastTop = useRef<number | null>(null);
  const lastDocked = useRef(docked);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el === null) {
      return;
    }
    const top = el.getBoundingClientRect().top;
    const from = lastTop.current;
    const changed = lastDocked.current !== docked;
    lastTop.current = top;
    lastDocked.current = docked;
    if (!changed || from === null || reduced) {
      return;
    }
    el.style.setProperty("--dock-from", `${from - top}px`);
    // Go roi gan lai, ep tinh style o giua: hai lan doi lien tiep (nhap → hoi
    // thoai → nhap) phai chay lai keyframe tu dau, khong noi tiep lan truoc.
    el.removeAttribute("data-dock");
    void el.offsetWidth;
    el.setAttribute("data-dock", "run");
  });

  /** Gan vao `onAnimationEnd` cua chinh khung. */
  const onAnimationEnd = (event: { target: EventTarget; currentTarget: HTMLElement }) => {
    // Su kien noi bot tu con (va tu portal cua tooltip) — chi keyframe cua khung.
    if (event.target === event.currentTarget) {
      event.currentTarget.removeAttribute("data-dock");
    }
  };

  return { ref, onAnimationEnd };
}

/**
 * Loi chao go tung ky tu — T-S.10, ban T-HD5-v2 muc 1b.
 *
 * Nhip la token `--duration-type` (`theme.css`); file nay chi DOC. Giam chuyen
 * dong ⇒ token = 0 ⇒ hien du ngay; jsdom (khong nap CSS) cung ra 0, nen test
 * thay cau day du. `runKey` doi ⇒ go lai tu dau ("Hoi thoai moi").
 */
export function useTypewriter(text: string, runKey: number) {
  const chars = Array.from(text);
  const total = chars.length;
  const [count, setCount] = useState(total);

  useEffect(() => {
    const step = readDurationMs("--duration-type");
    if (step <= 0) {
      setCount(total);
      return undefined;
    }
    setCount(0);
    let typed = 0;
    const id = window.setInterval(() => {
      typed += 1;
      setCount(typed);
      if (typed >= total) {
        window.clearInterval(id);
      }
    }, step);
    return () => window.clearInterval(id);
  }, [total, runKey]);

  return { typed: chars.slice(0, count).join(""), typing: count < total };
}

/**
 * Lo xo cua icon bien hinh — T-S.9, ban T-HD5-v2 (`springs.ts`), NQ-117.
 *
 * Loai token chuyen dong phia JS: icon chay bang vat ly lo xo cua `morphicons`
 * chu khong bang CSS, nen khong co so mili-giay nao — thoi gian la he qua cua
 * `stiffness`/`damping`. Ti so can ζ = damping / (2·√stiffness): ζ < 1 hoi
 * vot, ζ ≥ 1 khong vot. Doi gia tri o DAY; `components/ui/Icon.tsx` la noi
 * duy nhat doc chung.
 *
 * Ban ve con mot ham `springFor()` tra `null` khi giam chuyen dong, voi y
 * "null = doi tuc thi". `morphicons` 1.7.1 KHONG hieu nhu the: `null` roi ve
 * lo xo `snappy` mac dinh cua thu vien va icon VAN bay. Giam chuyen dong vi
 * vay la viec cua `reducedMotion="user"` trong `Icon`, khong phai cua file nay.
 */
export type SpringConfig = { stiffness: number; damping: number };

/** Doi trang thai do bam: toi nhanh, vot nhe bao "da nhan". ζ ≈ 0.79 */
export const SPRING_SNAPPY: SpringConfig = { stiffness: 520, damping: 36 };
/** Doi hinh lon, khong duoc vot (vot la thay meo). ζ ≈ 1.01 */
export const SPRING_SETTLE: SpringConfig = { stiffness: 300, damping: 35 };
/** Phan hoi re chuot, dao chieu lien tuc: mem, khong vot thay duoc. ζ ≈ 0.88 */
export const SPRING_GENTLE: SpringConfig = { stiffness: 220, damping: 26 };

/** Moi cho icon bien hinh — ten theo VAI TRO, cung loi ten token cua `theme.css`. */
export const SPRINGS = {
  sendStop: SPRING_SNAPPY,
  sidebarToggle: SPRING_SNAPPY,
  themeToggle: SPRING_SETTLE,
  submenuChevron: SPRING_GENTLE,
  accountMenuItemHover: SPRING_GENTLE,
} as const satisfies Record<string, SpringConfig>;

export type SpringRole = keyof typeof SPRINGS;

/**
 * T-S.12 — quang duong icon "nhich" khi re chuot / dua tieu diem ban phim len
 * mot muc menu tai khoan: ban T-HD5-v2 muc 6 (*"Re chuot tren tung muc: icon
 * nhich 3 px theo lo xo gentle"*), NQ-128 a. Lo xo la `SPRINGS.accountMenuItemHover`;
 * con so nay song canh no vi ca hai la token chuyen dong phia JS.
 */
export const ACCOUNT_MENU_NUDGE_PX = 3;
